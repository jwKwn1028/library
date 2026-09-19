#!/usr/bin/env python3
"""Discover, stage, or hand off PDFs for pending bibliography records."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import webbrowser


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from paperlib.bibtex import (  # noqa: E402
    BibtexError,
    is_audiovisual,
    normalize_doi,
    parse_bibliography,
    plain_text,
    title_identity,
)
from paperlib.media import MediaError, sha256, validate_media  # noqa: E402
from intake_papers import IntakeError, library_lock  # noqa: E402
from stage_papers import (  # noqa: E402
    StageError,
    StagePlan,
    copy_plans,
    existing_media_hashes,
)


CROSSREF_API = "https://api.crossref.org/works/"
OPENALEX_API = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/"
UNPAYWALL_API = "https://api.unpaywall.org/v2/"
DOI_HANDLE_API = "https://doi.org/api/handles/"
ARXIV_PDF = "https://arxiv.org/pdf/"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
JSON_MAX_BYTES = 5 * 1024 * 1024
LANDING_MAX_BYTES = 2 * 1024 * 1024
RATE_LIMIT_PAUSES = (1.5, 4.0)
USER_AGENT = "paper-library-fetch/1.0"
PDF_ACCEPT = "application/pdf,application/octet-stream;q=0.5"
EMAIL_ENV = "PAPER_LIBRARY_FETCH_EMAIL"
PROXY_ENV = "PAPER_LIBRARY_PROXY_PREFIX"
BROWSER_ENV = "PAPER_LIBRARY_BROWSER"
ARXIV_ID_RE = re.compile(
    r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?", re.IGNORECASE
)
MATCH_LEVELS = {3: "DOI", 2: "title", 1: "approximate title"}


class FetchError(RuntimeError):
    """A pending-document lookup or download could not be completed safely."""


class RateLimitedError(FetchError):
    """A metadata service asked the client to slow down."""


class NotPdfResponse(FetchError):
    """A candidate returned HTML or another non-PDF body."""

    def __init__(self, body: bytes):
        super().__init__("response is not a PDF (often a landing or login page)")
        self.body = body


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
    follow_landing: bool = True


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


@dataclass(frozen=True)
class MatchResult:
    source: Path
    status: str
    record: PendingRecord | None = None
    level: int = 0
    destination: Path | None = None
    digest: str | None = None
    detail: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover or stage accessible PDFs for existing pending bibliography "
            "records, open their publisher pages in your browser, or identify "
            "browser-downloaded PDFs. Only --apply writes Inbox/."
        )
    )
    selection = parser.add_mutually_exclusive_group()
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--browser",
        action="store_true",
        help=(
            f"open each unresolved record's publisher page in a browser "
            f"(${BROWSER_ENV}), prefixed by ${PROXY_ENV} when set; with --apply, "
            "only records that could not be downloaded are opened"
        ),
    )
    mode.add_argument(
        "--match",
        nargs="+",
        type=Path,
        metavar="PATH",
        help=(
            "identify PDF files, or PDFs directly inside directories, against "
            "pending records; --apply copies unique matches into Inbox/"
        ),
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="library root")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="download or copy verified PDFs into Inbox/",
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
        help="delay between records or browser tabs to limit load (default: 0.2)",
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
    if not args.match and not (args.keys or args.all):
        raise FetchError("select pending records with --key or --all")
    if args.json and (args.browser or args.match):
        raise FetchError("--json is available only for lookup and download runs")


def safe_web_url(value: str, context: str) -> str:
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError as error:
        raise FetchError(f"{context} returned an invalid URL") from error
    if parts.scheme.casefold() not in {"http", "https"} or not hostname:
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
            if error.code == 429:
                raise RateLimitedError("HTTP 429 (rate limited)") from error
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
        for pause in (*RATE_LIMIT_PAUSES, None):
            try:
                with self.open(url, "application/json") as response:
                    data = read_limited(response, JSON_MAX_BYTES, f"{source} response")
                break
            except RateLimitedError:
                if pause is None:
                    raise
                time.sleep(pause)
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
        # Albums and films are never PDFs, even when a film carries an EIDR DOI.
        if is_audiovisual(entry.entry_type):
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


def semantic_scholar_candidates(
    record: PendingRecord, client: NetworkClient
) -> tuple[list[Candidate], list[Candidate]]:
    """Return open-access copies and arXiv preprints known to Semantic Scholar."""
    endpoint = f"{SEMANTIC_SCHOLAR_API}DOI:{quote(record.doi, safe='/')}?" + urlencode(
        {"fields": "externalIds,openAccessPdf"}
    )
    payload = client.json(endpoint, "Semantic Scholar")
    external = payload.get("externalIds")
    if not isinstance(external, dict):
        external = {}
    returned_doi = external.get("DOI")
    if (
        not isinstance(returned_doi, str)
        or normalize_doi(returned_doi).casefold() != record.doi.casefold()
    ):
        raise FetchError("Semantic Scholar returned a work with a different DOI")

    paper_id = payload.get("paperId")
    metadata_url = (
        f"https://www.semanticscholar.org/paper/{paper_id}"
        if isinstance(paper_id, str) and re.fullmatch(r"[0-9a-f]{40}", paper_id)
        else "https://www.semanticscholar.org"
    )
    open_access: list[Candidate] = []
    location = payload.get("openAccessPdf")
    url = location.get("url") if isinstance(location, dict) else None
    if isinstance(url, str) and url.strip():
        status = location.get("status")
        source = "Semantic Scholar OA"
        if isinstance(status, str) and status:
            source += f" ({status.casefold()})"
        open_access.append(
            Candidate(
                source, safe_web_url(url.strip(), "Semantic Scholar"), metadata_url
            )
        )

    preprints: list[Candidate] = []
    arxiv_id = external.get("ArXiv")
    if isinstance(arxiv_id, str) and ARXIV_ID_RE.fullmatch(arxiv_id.strip()):
        identifier = arxiv_id.strip()
        preprints.append(
            Candidate(
                f"arXiv ({identifier})",
                f"{ARXIV_PDF}{identifier}",
                f"https://arxiv.org/abs/{identifier}",
            )
        )
    return open_access, preprints


def discover_candidates(
    record: PendingRecord, client: NetworkClient, email: str | None
) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    preprints: list[Candidate] = []
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
        open_access, preprints = semantic_scholar_candidates(record, client)
        candidates.extend(open_access)
    except FetchError as error:
        errors.append(f"Semantic Scholar: {error}")
    try:
        candidates.extend(crossref_candidates(record, client, email))
    except FetchError as error:
        errors.append(f"Crossref: {error}")

    # Preprints follow every version-of-record and accepted-manuscript source.
    candidates.extend(preprints)
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


class _CitationPdfParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.url is not None or tag.casefold() != "meta":
            return
        values = {name.casefold(): value for name, value in attrs if value is not None}
        content = values.get("content", "").strip()
        if values.get("name", "").casefold() == "citation_pdf_url" and content:
            self.url = content


def landing_pdf_url(body: bytes, base_url: str) -> str | None:
    """Return a landing page's standard citation_pdf_url, when it declares one."""
    parser = _CitationPdfParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    if parser.url is None:
        return None
    try:
        return safe_web_url(urljoin(base_url, parser.url), "landing page")
    except FetchError:
        return None


def normalized_words(value: str) -> list[str]:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return re.findall(r"[a-z0-9]+", ascii_value.casefold())


def first_author_family(author: str) -> str:
    first = author.split(" and ", 1)[0].strip()
    family = first.split(",", 1)[0] if "," in first else first.split()[-1]
    return "".join(normalized_words(family))


def pdf_text(path: Path) -> str:
    extractor = shutil.which("pdftotext")
    if not extractor:
        raise FetchError("pdftotext is required to verify PDF identity")
    extraction = subprocess.run(
        [extractor, "-f", "1", "-l", "2", str(path), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=45,
    )
    if extraction.returncode != 0:
        raise FetchError("pdftotext could not inspect the PDF")
    return extraction.stdout


def identity_score(text: str, record: PendingRecord) -> tuple[int, float]:
    """Rate first-page text as a DOI (3), title (2), approximate (1), or no match."""
    compact_text = re.sub(r"\s+", "", text.casefold())
    doi = record.doi.casefold()
    # A trailing digit would mean a longer DOI that merely shares this prefix.
    if doi and re.search(re.escape(doi) + r"(?!\d)", compact_text):
        return 3, 1.0
    expected_identity = title_identity(record.title)
    if expected_identity and expected_identity in title_identity(text):
        return 2, 1.0

    expected_words = set(normalized_words(record.title))
    actual_words = set(normalized_words(text))
    coverage = (
        len(expected_words & actual_words) / len(expected_words)
        if expected_words
        else 0.0
    )
    family = first_author_family(record.author) if record.author.strip() else ""
    author_match = not family or family in "".join(normalized_words(text))
    if len(expected_words) >= 4 and coverage >= 0.85 and author_match:
        return 1, coverage
    return 0, coverage


def verify_pdf_identity(path: Path, record: PendingRecord) -> None:
    if identity_score(pdf_text(path), record)[0] == 0:
        raise FetchError("downloaded PDF title/DOI does not match the pending record")


def stream_pdf(
    response: BinaryIO, destination: Path, maximum: int, context: str
) -> None:
    first = response.read(1024 * 1024)
    if not first.startswith(b"%PDF-"):
        remainder = response.read(max(0, LANDING_MAX_BYTES - len(first)))
        raise NotPdfResponse((first + remainder)[:LANDING_MAX_BYTES])
    total = len(first)
    if total > maximum:
        raise FetchError(f"{context} exceeded {maximum} bytes")
    with destination.open("wb") as output:
        output.write(first)
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise FetchError(f"{context} exceeded {maximum} bytes")
            output.write(chunk)


def staged_destination(root: Path, record: PendingRecord) -> Path:
    return root / "Inbox" / f"{record.citation_key}.pdf"


def existing_inbox_pdf(root: Path, record: PendingRecord) -> tuple[Path, str] | None:
    destination = staged_destination(root, record)
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
    destination = staged_destination(root, record)
    failures: list[str] = []
    queue = list(candidates)
    index = 0
    while index < len(queue):
        candidate = queue[index]
        index += 1
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{record.citation_key}.", suffix=".pdf", dir=inbox
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with client.open(candidate.url, PDF_ACCEPT) as response:
                final_url = response.geturl()
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
        except NotPdfResponse as error:
            failures.append(f"{candidate.source}: {error}")
            # Follow a repository landing page's declared PDF link once.
            follow = (
                landing_pdf_url(error.body, final_url)
                if candidate.follow_landing
                else None
            )
            if follow and all(item.url != follow for item in queue):
                queue.insert(
                    index,
                    Candidate(
                        f"{candidate.source} landing-page PDF",
                        follow,
                        candidate.metadata_url,
                        follow_landing=False,
                    ),
                )
        except (FetchError, MediaError, OSError, subprocess.SubprocessError) as error:
            failures.append(f"{candidate.source}: {error}")
        finally:
            temporary.unlink(missing_ok=True)
    return None, None, None, failures, "unavailable"


def publisher_landing_url(record: PendingRecord, client: NetworkClient) -> str:
    """Resolve a DOI's registered landing page without contacting the publisher."""
    fallback = f"https://doi.org/{quote(record.doi, safe='/')}"
    try:
        payload = client.json(
            f"{DOI_HANDLE_API}{quote(record.doi, safe='/')}?type=URL", "DOI handle"
        )
    except FetchError:
        return fallback
    values = payload.get("values")
    if not isinstance(values, list):
        return fallback
    for value in values:
        if not isinstance(value, dict) or value.get("type") != "URL":
            continue
        data = value.get("data")
        url = data.get("value") if isinstance(data, dict) else None
        if isinstance(url, str):
            try:
                return safe_web_url(url, "DOI handle")
            except FetchError:
                return fallback
    return fallback


def proxy_prefix() -> str | None:
    value = os.environ.get(PROXY_ENV, "").strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        hostname = None
    if (
        not hostname
        or parts.scheme.casefold() not in {"http", "https"}
        or parts.username is not None
        or parts.password is not None
    ):
        raise FetchError(
            f"{PROXY_ENV} must be an HTTP(S) URL prefix without credentials"
        )
    return value


def browser_command() -> list[str] | None:
    value = os.environ.get(BROWSER_ENV, "").strip()
    if not value:
        return None
    try:
        command = shlex.split(value)
    except ValueError as error:
        raise FetchError(f"{BROWSER_ENV} is not a valid command: {error}") from error
    if not command or shutil.which(command[0]) is None:
        raise FetchError(f"{BROWSER_ENV} command was not found: {value}")
    return command


def open_in_browser(url: str, command: list[str] | None) -> None:
    """Hand a URL to the user's browser; this process never reads browser state."""
    if command is None:
        if not webbrowser.open_new_tab(url):
            raise FetchError(f"no web browser is available; set {BROWSER_ENV}")
        return
    try:
        subprocess.Popen(
            [*command, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise FetchError(f"could not start the browser: {error}") from error


def open_publisher_pages(
    root: Path,
    records: list[PendingRecord],
    client: NetworkClient,
    delay: float,
) -> None:
    prefix = proxy_prefix()
    command = browser_command()
    waiting = [
        record for record in records if not staged_destination(root, record).exists()
    ]
    print()
    print(
        f"BROWSER — opening {len(waiting)} publisher page(s) "
        + (f"through {PROXY_ENV}" if prefix else "directly")
    )
    for index, record in enumerate(waiting):
        if index and delay:
            time.sleep(delay)
        landing = publisher_landing_url(record, client)
        open_in_browser(f"{prefix}{landing}" if prefix else landing, command)
        print(f"OPEN   {record.citation_key}  {display_url(landing)}")
    if waiting:
        print(
            "Download each PDF in the browser, then identify the downloads with:\n"
            "  ./scripts/fetch-pending --match <download-directory>\n"
            "and repeat with --apply to copy unique matches into Inbox/."
        )


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


def match_sources(paths: list[Path]) -> list[Path]:
    sources: list[Path] = []
    for value in paths:
        expanded = value.expanduser()
        candidate = expanded if expanded.is_absolute() else Path.cwd() / expanded
        if candidate.is_symlink():
            raise FetchError(f"match path must not be a symlink: {value}")
        if candidate.is_dir():
            sources.extend(
                sorted(
                    child
                    for child in candidate.iterdir()
                    if child.suffix.casefold() == ".pdf"
                    and child.is_file()
                    and not child.is_symlink()
                )
            )
        elif candidate.is_file() and candidate.suffix.casefold() == ".pdf":
            sources.append(candidate)
        else:
            raise FetchError(f"match path is not a PDF or directory: {value}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for source in sources:
        resolved = source.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def identify_pdf(
    source: Path, records: list[PendingRecord]
) -> tuple[str, PendingRecord | None, int, str]:
    try:
        text = pdf_text(source)
    except (FetchError, subprocess.SubprocessError) as error:
        return "unreadable", None, 0, str(error)
    if not text.strip():
        return "unmatched", None, 0, "no extractable text; the PDF may be a scan"
    scored = sorted(
        ((identity_score(text, record), record) for record in records),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored or scored[0][0][0] == 0:
        return "unmatched", None, 0, "no pending DOI or title found on the first pages"
    best, record = scored[0]
    ties = [item[1].citation_key for item in scored if item[0] == best]
    if len(ties) > 1:
        return "ambiguous", None, best[0], "matches " + ", ".join(ties)
    return "matched", record, best[0], ""


def plan_matches(
    root: Path, sources: list[Path], records: list[PendingRecord]
) -> list[MatchResult]:
    existing_hashes = existing_media_hashes(root)
    results: list[MatchResult] = []
    claimed: dict[str, int] = {}
    batch_hashes: dict[str, Path] = {}
    for source in sources:
        try:
            validate_media(source)
        except MediaError as error:
            results.append(MatchResult(source, "invalid", detail=str(error)))
            continue
        digest = sha256(source)
        status, record, level, detail = identify_pdf(source, records)
        if record is None:
            results.append(
                MatchResult(source, status, level=level, digest=digest, detail=detail)
            )
            continue
        destination = staged_destination(root, record)
        duplicate = existing_hashes.get(digest) or batch_hashes.get(digest)
        if duplicate is not None:
            status, detail = "duplicate", f"same content as {duplicate}"
        elif destination.exists() or destination.is_symlink():
            status, detail = "already-staged", f"{destination.relative_to(root)} exists"
        elif record.citation_key in claimed:
            earlier = claimed[record.citation_key]
            results[earlier] = replace(
                results[earlier],
                status="conflict",
                detail=f"another file also matches: {source}",
            )
            status, detail = (
                "conflict",
                f"another file also matches: {results[earlier].source}",
            )
        else:
            claimed[record.citation_key] = len(results)
            batch_hashes[digest] = source
        results.append(
            MatchResult(source, status, record, level, destination, digest, detail)
        )
    return results


def print_matches(root: Path, results: list[MatchResult], apply: bool) -> None:
    print(
        "MATCH APPLY — unique matches were copied into Inbox"
        if apply
        else "MATCH DRY RUN — no files changed"
    )
    for result in results:
        print()
        print(f"FILE   {result.source}")
        if result.record is not None:
            print(
                f"MATCH  {result.record.citation_key} "
                f"({MATCH_LEVELS.get(result.level, 'none')})"
            )
        if result.status == "matched" and result.destination is not None:
            print(f"    -> {result.destination.relative_to(root)}")
        else:
            print(f"{result.status.upper():<7}{result.detail}")
    matched = sum(result.status == "matched" for result in results)
    print()
    print(f"Result: {matched} of {len(results)} PDF(s) uniquely matched.")
    if matched and not apply:
        print("Re-run with --apply to copy them into Inbox; originals are preserved.")
    elif matched:
        print("Review each staged PDF, then attach it with a reviewed intake manifest.")


def run_match(root: Path, args: argparse.Namespace) -> int:
    if shutil.which("pdftotext") is None:
        raise FetchError("pdftotext is required to identify PDFs")
    sources = match_sources(args.match)
    with library_lock(root, args.lock_timeout):
        records = select_records(load_pending_records(root), args.keys)
        results = plan_matches(root, sources, records)
        if args.apply:
            copy_plans(
                root,
                [
                    StagePlan(result.source, result.destination, result.digest)
                    for result in results
                    if result.status == "matched"
                    and result.destination is not None
                    and result.digest is not None
                ],
            )
    print_matches(root, results, args.apply)
    return 0


def run(args: argparse.Namespace) -> int:
    validate_options(args)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise FetchError(f"library root does not exist: {root}")
    if args.match:
        return run_match(root, args)
    client = NetworkClient(args.timeout)
    email = os.environ.get(EMAIL_ENV, "").strip() or None
    if args.browser:
        # Validate browser settings before any network work or file writes.
        proxy_prefix()
        browser_command()

    discover = args.apply or not args.browser
    with library_lock(root, args.lock_timeout):
        records = select_records(load_pending_records(root), args.keys)
        results: list[FetchResult] = []
        for index, record in enumerate(records if discover else []):
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
    elif discover:
        print_results(root, results, args.apply)
        if not email:
            print(
                f"NOTICE Unpaywall was skipped; set {EMAIL_ENV} "
                "at runtime to enable it."
            )
    if args.browser:
        unresolved = (
            [result.record for result in results if result.destination is None]
            if args.apply
            else records
        )
        open_publisher_pages(root, unresolved, client, args.delay)
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except (FetchError, IntakeError, OSError, StageError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
