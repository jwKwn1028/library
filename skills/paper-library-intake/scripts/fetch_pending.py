#!/usr/bin/env python3
"""Discover and stage accessible PDFs for pending bibliography records."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from paperlib.bibtex import (  # noqa: E402
    BibtexError,
    normalize_doi,
    parse_bibliography,
    plain_text,
    title_identity,
)
from paperlib.media import MediaError, sha256, validate_media  # noqa: E402
from intake_papers import IntakeError, library_lock  # noqa: E402


CROSSREF_API = "https://api.crossref.org/works/"
OPENALEX_API = "https://api.openalex.org/works"
UNPAYWALL_API = "https://api.unpaywall.org/v2/"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
JSON_MAX_BYTES = 5 * 1024 * 1024
USER_AGENT = "paper-library-fetch/1.0"


class FetchError(RuntimeError):
    """A pending-document lookup or download could not be completed safely."""


@dataclass(frozen=True)
class PendingRecord:
    citation_key: str
    title: str
    doi: str
    author: str
    topic: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    source: str
    url: str
    metadata_url: str


@dataclass(frozen=True)
class FetchResult:
    record: PendingRecord
    candidates: tuple[Candidate, ...]
    lookup_errors: tuple[str, ...]
    status: str
    destination: Path | None = None
    digest: str | None = None
    selected: Candidate | None = None
    download_errors: tuple[str, ...] = ()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover or stage accessible PDFs for existing pending bibliography "
            "records. Network lookup occurs in both modes; only --apply writes Inbox/."
        )
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--key",
        action="append",
        dest="keys",
        metavar="CITATION_KEY",
        help="pending citation key to fetch; repeat for several records",
    )
    selection.add_argument(
        "--all", action="store_true", help="try every pending record with a DOI"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="library root")
    parser.add_argument(
        "--apply", action="store_true", help="download verified PDFs into Inbox/"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable result"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="per-request timeout (default: 30)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        metavar="BYTES",
        help="maximum accepted PDF size (default: 104857600)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        metavar="SECONDS",
        help="delay between records to limit API load (default: 0.2)",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="seconds to wait for the library lock (default: 5)",
    )
    return parser.parse_args()


def validate_options(args: argparse.Namespace) -> None:
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise FetchError("--timeout must be a finite, positive number")
    if args.max_bytes < 5:
        raise FetchError("--max-bytes must be at least 5")
    if not math.isfinite(args.delay) or args.delay < 0:
        raise FetchError("--delay must be a finite, non-negative number")
    if args.keys and len(set(args.keys)) != len(args.keys):
        raise FetchError("the same --key was supplied more than once")


def safe_web_url(value: str, context: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise FetchError(f"{context} returned an invalid URL") from error
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        raise FetchError(f"{context} returned a non-HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise FetchError(f"{context} returned a URL containing credentials")
    return value


def display_url(value: str) -> str:
    """Omit query strings because publisher links can carry transient tokens."""
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def read_limited(stream: BinaryIO, maximum: int, context: str) -> bytes:
    content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise FetchError(f"{context} exceeded {maximum} bytes")
    return content


class NetworkClient:
    def __init__(self, timeout: float):
        self.timeout = timeout

    def open(self, url: str, accept: str):
        safe_web_url(url, "network candidate")
        request = Request(
            url,
            headers={"Accept": accept, "User-Agent": USER_AGENT},
        )
        try:
            response = urlopen(request, timeout=self.timeout)  # noqa: S310
        except HTTPError as error:
            raise FetchError(f"HTTP {error.code}") from error
        except (TimeoutError, URLError) as error:
            reason = getattr(error, "reason", error)
            raise FetchError(f"network request failed: {reason}") from error
        try:
            safe_web_url(response.geturl(), "network redirect")
        except Exception:
            response.close()
            raise
        return response

    def json(self, url: str, source: str) -> dict[str, Any]:
        with self.open(url, "application/json") as response:
            data = read_limited(response, JSON_MAX_BYTES, f"{source} response")
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FetchError(f"{source} returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise FetchError(f"{source} returned a non-object JSON response")
        return parsed


def load_pending_records(root: Path) -> list[PendingRecord]:
    bibliography = root / "library.bib"
    if not bibliography.is_file():
        raise FetchError("the library root must contain library.bib")
    try:
        entries = parse_bibliography(
            bibliography.read_text(encoding="utf-8"), require_entries=False
        )
    except (OSError, UnicodeError, BibtexError) as error:
        raise FetchError(f"cannot parse library.bib: {error}") from error

    records: list[PendingRecord] = []
    for entry in entries:
        if entry.fields.get("file", "").strip():
            continue
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            continue
        records.append(
            PendingRecord(
                citation_key=entry.citation_key,
                title=plain_text(entry.fields.get("title", "")),
                doi=normalize_doi(doi),
                author=plain_text(entry.fields.get("author", "")),
                topic=entry.topic or (),
            )
        )
    return sorted(records, key=lambda record: record.citation_key)


def select_records(
    records: list[PendingRecord], keys: list[str] | None
) -> list[PendingRecord]:
    if keys is None:
        return records
    by_key = {record.citation_key: record for record in records}
    missing = [key for key in keys if key not in by_key]
    if missing:
        raise FetchError(
            "citation key is not a DOI-backed pending record: " + ", ".join(missing)
        )
    return [by_key[key] for key in keys]


def unpaywall_candidates(
    record: PendingRecord, client: NetworkClient, email: str
) -> list[Candidate]:
    endpoint = f"{UNPAYWALL_API}{quote(record.doi, safe='')}?" + urlencode(
        {"email": email}
    )
    payload = client.json(endpoint, "Unpaywall")
    locations: list[Any] = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    others = payload.get("oa_locations")
    if isinstance(others, list):
        locations.extend(others)

    candidates: list[Candidate] = []
    metadata_url = f"https://unpaywall.org/{quote(record.doi, safe='/')}"
    for location in locations:
        if not isinstance(location, dict):
            continue
        url = location.get("url_for_pdf")
        if not isinstance(url, str) or not url.strip():
            continue
        version = location.get("version")
        source = "Unpaywall" + (f" ({version})" if isinstance(version, str) else "")
        candidates.append(
            Candidate(source, safe_web_url(url, "Unpaywall"), metadata_url)
        )
    return candidates


def crossref_candidates(
    record: PendingRecord, client: NetworkClient, email: str | None
) -> list[Candidate]:
    endpoint = f"{CROSSREF_API}{quote(record.doi, safe='')}"
    if email:
        endpoint += "?" + urlencode({"mailto": email})
    payload = client.json(endpoint, "Crossref")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise FetchError("Crossref response has no work metadata")
    links = message.get("link")
    if not isinstance(links, list):
        return []

    candidates: list[Candidate] = []
    metadata_url = f"{CROSSREF_API}{quote(record.doi, safe='')}"
    for link in links:
        if not isinstance(link, dict):
            continue
        url = link.get("URL")
        content_type = str(link.get("content-type", "")).casefold()
        if not isinstance(url, str) or "pdf" not in content_type:
            continue
        version = link.get("content-version")
        source = "Crossref full text"
        if isinstance(version, str) and version:
            source += f" ({version})"
        candidates.append(
            Candidate(source, safe_web_url(url, "Crossref"), metadata_url)
        )
    return candidates


def openalex_candidates(
    record: PendingRecord, client: NetworkClient
) -> list[Candidate]:
    endpoint = (
        OPENALEX_API
        + "?"
        + urlencode({"filter": f"doi:https://doi.org/{record.doi}", "per-page": "1"})
    )
    payload = client.json(endpoint, "OpenAlex")
    results = payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return []
    work = results[0]
    returned_doi = work.get("doi")
    if (
        not isinstance(returned_doi, str)
        or normalize_doi(returned_doi).casefold() != record.doi.casefold()
    ):
        raise FetchError("OpenAlex returned a work with a different DOI")

    locations: list[Any] = []
    best = work.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    others = work.get("locations")
    if isinstance(others, list):
        locations.extend(others)

    work_id = work.get("id")
    metadata_url = (
        work_id
        if isinstance(work_id, str) and work_id.startswith("https://openalex.org/")
        else "https://openalex.org"
    )
    candidates: list[Candidate] = []
    for location in locations:
        if not isinstance(location, dict) or location.get("is_oa") is not True:
            continue
        url = location.get("pdf_url")
        if not isinstance(url, str) or not url.strip():
            continue
        source_data = location.get("source")
        source_name = (
            source_data.get("display_name") if isinstance(source_data, dict) else None
        )
        version = location.get("version")
        details = [
            value
            for value in (version, source_name)
            if isinstance(value, str) and value
        ]
        source = "OpenAlex OA" + (f" ({'; '.join(details)})" if details else "")
        candidates.append(
            Candidate(source, safe_web_url(url, "OpenAlex"), metadata_url)
        )
    return candidates


def discover_candidates(
    record: PendingRecord, client: NetworkClient, email: str | None
) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    errors: list[str] = []
    if email:
        try:
            candidates.extend(unpaywall_candidates(record, client, email))
        except FetchError as error:
            errors.append(f"Unpaywall: {error}")
    try:
        candidates.extend(openalex_candidates(record, client))
    except FetchError as error:
        errors.append(f"OpenAlex: {error}")
    try:
        candidates.extend(crossref_candidates(record, client, email))
    except FetchError as error:
        errors.append(f"Crossref: {error}")

    candidates.append(
        Candidate(
            "DOI resolver",
            f"https://doi.org/{quote(record.doi, safe='/')}",
            f"https://doi.org/{quote(record.doi, safe='/')}",
        )
    )
    unique: list[Candidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        unique.append(candidate)
    return unique, errors


def normalized_words(value: str) -> list[str]:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return re.findall(r"[a-z0-9]+", ascii_value.casefold())


def first_author_family(author: str) -> str:
    first = author.split(" and ", 1)[0].strip()
    family = first.split(",", 1)[0] if "," in first else first.split()[-1]
    return "".join(normalized_words(family))


def verify_pdf_identity(path: Path, record: PendingRecord) -> None:
    extractor = shutil.which("pdftotext")
    if not extractor:
        raise FetchError("pdftotext is required to verify downloaded PDF identity")
    extraction = subprocess.run(
        [extractor, "-f", "1", "-l", "2", str(path), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=45,
    )
    if extraction.returncode != 0:
        raise FetchError("pdftotext could not inspect the downloaded PDF")
    text = extraction.stdout
    compact_text = re.sub(r"\s+", "", text.casefold())
    doi_match = record.doi.casefold() in compact_text
    expected_identity = title_identity(record.title)
    text_identity = title_identity(text)
    exact_title_match = bool(expected_identity and expected_identity in text_identity)

    expected_words = set(normalized_words(record.title))
    actual_words = set(normalized_words(text))
    coverage = (
        len(expected_words & actual_words) / len(expected_words)
        if expected_words
        else 0.0
    )
    family = first_author_family(record.author) if record.author.strip() else ""
    author_match = not family or family in "".join(normalized_words(text))
    approximate_title_match = (
        len(expected_words) >= 4 and coverage >= 0.85 and author_match
    )
    if not (doi_match or exact_title_match or approximate_title_match):
        raise FetchError("downloaded PDF title/DOI does not match the pending record")


def stream_pdf(
    response: BinaryIO, destination: Path, maximum: int, context: str
) -> None:
    total = 0
    signature = bytearray()
    with destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise FetchError(f"{context} exceeded {maximum} bytes")
            if len(signature) < 5:
                signature.extend(chunk[: 5 - len(signature)])
            output.write(chunk)
    if bytes(signature) != b"%PDF-":
        raise FetchError("response is not a PDF (often a landing or login page)")


def existing_inbox_pdf(root: Path, record: PendingRecord) -> tuple[Path, str] | None:
    destination = root / "Inbox" / f"{record.citation_key}.pdf"
    if not destination.exists() and not destination.is_symlink():
        return None
    if destination.is_symlink() or not destination.is_file():
        raise FetchError(f"unsafe Inbox destination already exists: {destination}")
    try:
        validate_media(destination)
    except MediaError as error:
        raise FetchError(str(error)) from error
    verify_pdf_identity(destination, record)
    return destination, sha256(destination)


def download_record(
    root: Path,
    record: PendingRecord,
    candidates: list[Candidate],
    client: NetworkClient,
    maximum: int,
) -> tuple[Path | None, str | None, Candidate | None, list[str], str]:
    existing = existing_inbox_pdf(root, record)
    if existing is not None:
        return existing[0], existing[1], None, [], "already-staged"

    inbox = root / "Inbox"
    if inbox.is_symlink():
        raise FetchError("Inbox must not be a symlink")
    inbox.mkdir(parents=True, exist_ok=True)
    destination = inbox / f"{record.citation_key}.pdf"
    failures: list[str] = []
    for candidate in candidates:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{record.citation_key}.", suffix=".pdf", dir=inbox
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with client.open(
                candidate.url, "application/pdf,application/octet-stream;q=0.5"
            ) as response:
                stream_pdf(response, temporary, maximum, candidate.source)
            validate_media(temporary)
            verify_pdf_identity(temporary, record)
            digest = sha256(temporary)
            os.chmod(temporary, 0o664)
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise FetchError(
                    f"Inbox destination appeared: {destination}"
                ) from error
            return destination, digest, candidate, failures, "downloaded"
        except (FetchError, MediaError, OSError, subprocess.SubprocessError) as error:
            failures.append(f"{candidate.source}: {error}")
        finally:
            temporary.unlink(missing_ok=True)
    return None, None, None, failures, "unavailable"


def result_dict(root: Path, result: FetchResult) -> dict[str, Any]:
    selected = result.selected
    return {
        "citation_key": result.record.citation_key,
        "title": result.record.title,
        "doi": result.record.doi,
        "topic": list(result.record.topic),
        "status": result.status,
        "destination": (
            result.destination.relative_to(root).as_posix()
            if result.destination is not None
            else None
        ),
        "sha256": result.digest,
        "selected_source": selected.source if selected else None,
        "selected_url": display_url(selected.url) if selected else None,
        "candidates": [
            {"source": candidate.source, "url": display_url(candidate.url)}
            for candidate in result.candidates
        ],
        "lookup_errors": list(result.lookup_errors),
        "download_errors": list(result.download_errors),
    }


def print_results(root: Path, results: list[FetchResult], apply: bool) -> None:
    print(
        "FETCH APPLY — verified downloads were staged in Inbox"
        if apply
        else "FETCH DRY RUN — network lookup only; no files changed"
    )
    for result in results:
        print()
        print(f"KEY    {result.record.citation_key}")
        print(f"DOI    {result.record.doi}")
        print(f"TITLE  {result.record.title}")
        for candidate in result.candidates:
            print(f"FOUND  {candidate.source}: {display_url(candidate.url)}")
        for error in result.lookup_errors:
            print(f"NOTICE {error}")
        if result.destination is not None:
            print(f"{result.status.upper():<7}{result.destination.relative_to(root)}")
            print(f"SHA256 {result.digest}")
            if result.selected is not None:
                print(f"SOURCE {result.selected.source}")
        elif apply:
            print("STATUS UNAVAILABLE")
            for error in result.download_errors:
                print(f"TRY    {error}")

    downloaded = sum(result.status == "downloaded" for result in results)
    existing = sum(result.status == "already-staged" for result in results)
    unavailable = sum(result.status == "unavailable" for result in results)
    print()
    if apply:
        print(
            f"Result: {downloaded} downloaded, {existing} already staged, "
            f"{unavailable} unavailable."
        )
        if downloaded or existing:
            print(
                "Review each staged PDF, then attach it with a reviewed "
                "intake manifest."
            )
    else:
        print(
            f"Result: {len(results)} pending record(s) checked. "
            "Re-run with --apply to try the candidates."
        )


def run(args: argparse.Namespace) -> int:
    validate_options(args)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise FetchError(f"library root does not exist: {root}")
    client = NetworkClient(args.timeout)
    email = os.environ.get("PAPER_LIBRARY_FETCH_EMAIL", "").strip() or None

    with library_lock(root, args.lock_timeout):
        records = select_records(load_pending_records(root), args.keys)
        results: list[FetchResult] = []
        for index, record in enumerate(records):
            if index and args.delay:
                time.sleep(args.delay)
            candidates, lookup_errors = discover_candidates(record, client, email)
            if args.apply:
                destination, digest, selected, failures, status = download_record(
                    root, record, candidates, client, args.max_bytes
                )
            else:
                destination = None
                digest = None
                selected = None
                failures = []
                status = "candidates-found" if candidates else "unavailable"
            results.append(
                FetchResult(
                    record=record,
                    candidates=tuple(candidates),
                    lookup_errors=tuple(lookup_errors),
                    status=status,
                    destination=destination,
                    digest=digest,
                    selected=selected,
                    download_errors=tuple(failures),
                )
            )

    if args.json:
        print(json.dumps([result_dict(root, result) for result in results], indent=2))
    else:
        print_results(root, results, args.apply)
        if not email:
            print(
                "NOTICE Unpaywall was skipped; set PAPER_LIBRARY_FETCH_EMAIL "
                "at runtime to enable it."
            )
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except (FetchError, IntakeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
