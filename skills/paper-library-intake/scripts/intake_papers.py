#!/usr/bin/env python3
"""Safely apply a reviewed library-item manifest to this Typst catalog."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date
import fcntl
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from paperlib.bibtex import (  # noqa: E402
    DISTINCT_FROM_FIELD,
    IDENTIFIER_FIELDS,
    BibEntry,
    BibtexError,
    catalog_title,
    is_audiovisual,
    is_canonical_date,
    is_canonical_doi,
    is_canonical_identifier,
    is_safe_web_url,
    is_valid_isbn,
    normalize_doi,
    normalize_identifier,
    normalize_isbn,
    parse_bibliography,
    record_identity,
    replace_field_values,
    title_identity,
)
from paperlib.catalog import (  # noqa: E402
    CatalogError,
    CatalogItem,
    heading_component,
    parse_catalog,
)
from paperlib.media import (  # noqa: E402
    INBOX_DIRECTORY,
    LIBRARY_DIRECTORY,
    MediaError,
    media_files,
    sha256,
    validate_media,
)
from paperlib.validation import check_sources  # noqa: E402


KEY_RE = re.compile(r"^[a-z]+[0-9]{4}[a-z0-9]+$")
NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*\.(?:epub|mobi|pdf)$")
TOPIC_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
ENTRY_TYPE_RE = re.compile(r"^[A-Za-z]+$")
FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
HEADING_RE = re.compile(r"^(=+)\s+(.+?)\s*$")
SAFE_HEADING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &+()/.\-–]*$")
CATALOG_UPDATED_RE = re.compile(
    r'^#let catalog-updated = "(?:\\.|[^"\\])*"\s*$', re.MULTILINE
)
# Manifest vocabulary; tests compare these sets with the public JSON schema.
MANIFEST_PROPERTIES = frozenset({"$schema", "topic", "items"})
LEGACY_MANIFEST_PROPERTIES = frozenset({"papers"})
TOPIC_PROPERTIES = frozenset({"path", "headings"})
NEW_ITEM_PROPERTIES = frozenset(
    {
        "attach",
        "pending",
        "source_file",
        "canonical_filename",
        "citation_key",
        "entry_type",
        "title",
        "bib_title",
        "fields",
        "sidecars",
        "metadata_sources",
        "distinct_from",
    }
)
LEGACY_ITEM_PROPERTIES = frozenset({"source_pdf"})
ATTACHMENT_PROPERTIES = frozenset(
    {
        "attach",
        "citation_key",
        "source_file",
        "canonical_filename",
        "sidecars",
        "metadata_sources",
    }
)
RESERVED_FIELDS = frozenset({"title", "keywords", "file", DISTINCT_FROM_FIELD})
# Exit status for an apply stopped by Ctrl-C or a termination signal.
INTERRUPTED_EXIT_CODE = 130


class IntakeError(RuntimeError):
    """A preflight or transactional intake failure."""


class IntakeInterrupted(IntakeError):
    """An interrupt or termination signal stopped an apply before it finished."""

    def __init__(self, cause: str):
        super().__init__(f"intake interrupted by {cause}; changes were rolled back")


@contextmanager
def interrupt_on_termination():
    """Raise IntakeInterrupted on SIGTERM or SIGHUP so the rollback still runs."""

    def interrupt(signal_number: int, _frame: Any) -> None:
        raise IntakeInterrupted(signal.Signals(signal_number).name)

    previous = {
        number: signal.signal(number, interrupt)
        for number in (signal.SIGTERM, signal.SIGHUP)
    }
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def interrupts_ignored():
    """Keep a second Ctrl-C or signal from abandoning a rollback halfway."""

    previous = {
        number: signal.signal(number, signal.SIG_IGN)
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@dataclass(frozen=True)
class ItemPlan:
    source_file: Path | None
    target_file: Path | None
    citation_key: str
    entry_type: str
    display_title: str
    fields: dict[str, str]
    sidecars: tuple[Path, ...]
    metadata_sources: tuple[str, ...]
    digest: str | None
    existing_entry: BibEntry | None = None
    existing_catalog_item: CatalogItem | None = None

    @property
    def pending(self) -> bool:
        return self.source_file is None

    @property
    def attachment(self) -> bool:
        return self.existing_entry is not None


@dataclass(frozen=True)
class Snapshot:
    existed: bool
    data: bytes
    mode: int | None


@dataclass(frozen=True)
class TopicPlan:
    manifest_path: Path
    topic_path: str
    headings: tuple[str, ...]
    topic_directory: Path
    items: tuple[ItemPlan, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or transactionally apply a reviewed JSON intake manifest. "
            "Without --apply, no library files are changed."
        )
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--manifest",
        type=Path,
        action="append",
        help="reviewed JSON manifest; repeat for one transactional multi-topic batch",
    )
    source_group.add_argument(
        "--write-template", type=Path, metavar="PATH", help="write a starter manifest"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="library root")
    parser.add_argument("--apply", action="store_true", help="apply the reviewed plan")
    parser.add_argument(
        "--delete-sidecars",
        action="store_true",
        help="delete manifest-listed .bib/.bibtex sidecars after successful intake",
    )
    parser.add_argument(
        "--output",
        default="Catalog.pdf",
        help="root-level catalog PDF name (default: Catalog.pdf)",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="seconds to wait for the library lock (default: 5)",
    )
    report_group = parser.add_mutually_exclusive_group()
    report_group.add_argument(
        "--report-json",
        type=Path,
        metavar="PATH",
        help="write one private report to this exact JSON path",
    )
    report_group.add_argument(
        "--report-base",
        type=Path,
        metavar="PATH",
        help=(
            "write PATH.dry-run.json or PATH.applied.json according to this run's phase"
        ),
    )
    parser.add_argument(
        "--force-report",
        action="store_true",
        help="replace an existing report output",
    )
    return parser.parse_args()


def parse_status_args(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} status",
        description="Report records whose local document is still pending",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--pending",
        action="store_true",
        help="list pending-download records (currently the only status view)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    parser.add_argument("--lock-timeout", type=float, default=5.0, metavar="SECONDS")
    args = parser.parse_args(arguments)
    if not args.pending:
        parser.error("status currently requires --pending")
    return args


def parse_topics_args(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"{Path(sys.argv[0]).name} topics",
        description="List the current catalog taxonomy and per-topic record counts",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    parser.add_argument("--lock-timeout", type=float, default=5.0, metavar="SECONDS")
    return parser.parse_args(arguments)


@contextmanager
def library_lock(root: Path, timeout: float):
    if not math.isfinite(timeout) or timeout < 0:
        raise IntakeError("--lock-timeout must be a finite, non-negative number")
    lock_path = root / ".paper-library.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise IntakeError(
            f"cannot open advisory lock {lock_path.name}: {error}"
        ) from error
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise IntakeError(f"advisory lock is not a regular file: {lock_path.name}")
    os.fchmod(descriptor, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise IntakeError(
                        f"library is busy; could not acquire {lock_path.name} "
                        f"within {timeout:g} seconds"
                    ) from error
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def template_manifest() -> dict[str, Any]:
    return {
        "topic": {
            "path": "QuantumChemistry/ElectronicStructure/AnalyticalGradients",
            "headings": [
                "Quantum Chemistry",
                "Electronic Structure",
                "Analytical Gradients",
            ],
        },
        "items": [
            {
                "source_file": "Inbox/downloaded-item.pdf",
                "canonical_filename": "DistinctiveOfficialTitle.pdf",
                "citation_key": "author2026distinctivetitle",
                "entry_type": "article",
                "title": "The official display title",
                "bib_title": "The official display title with {Protected Acronyms}",
                "fields": {
                    "author": "Author, First and Researcher, Second",
                    "journaltitle": "Journal Name",
                    "date": "2026",
                    "volume": "12",
                    "number": "3",
                    "pages": "101--120",
                    "doi": "10.0000/example-doi",
                },
                "metadata_sources": [
                    "https://doi.org/10.0000/example-doi",
                    "https://api.crossref.org/works/10.0000%2Fexample-doi",
                ],
                "sidecars": ["Inbox/downloaded-citation.bib"],
            }
        ],
    }


def write_template(path: Path) -> None:
    destination = path.expanduser().resolve()
    if destination.exists():
        raise IntakeError(f"refusing to overwrite existing template: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(template_manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote manifest template: {destination}")


def require_text(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def first_symlink_component(path: Path) -> Path | None:
    if not path.is_absolute():
        raise ValueError("symlink-component checks require an absolute path")
    cursor = Path(path.anchor)
    for component in path.parts[1:]:
        cursor /= component
        if cursor.is_symlink():
            return cursor
    return None


def resolve_in_root(root: Path, value: str, context: str) -> Path:
    raw_path = Path(value).expanduser()
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    absolute = Path(os.path.abspath(candidate))
    if not absolute.is_relative_to(root):
        raise IntakeError(f"{context} leaves the library root: {value}")
    symlink = first_symlink_component(absolute)
    if symlink is not None:
        raise IntakeError(f"{context} uses a symlinked path component: {symlink}")
    return absolute.resolve()


def normalize_space(value: Any, context: str) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise IntakeError(f"{context} must be text or a number")
    normalized = " ".join(str(value).split())
    if not normalized:
        raise IntakeError(f"{context} cannot be empty")
    return normalized


def current_catalog_date(today: date | None = None) -> str:
    value = today or date.today()
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def update_catalog_date(main_text: str, value: str) -> str:
    matches = list(CATALOG_UPDATED_RE.finditer(main_text))
    if len(matches) != 1:
        raise IntakeError(
            "main.typ must define exactly one quoted #let catalog-updated value"
        )
    match = matches[0]
    replacement = f"#let catalog-updated = {json.dumps(value)}"
    return main_text[: match.start()] + replacement + main_text[match.end() :]


def braces_are_balanced(value: str) -> bool:
    """Return whether *value* can be written between braces and parsed back.

    A final unpaired backslash would escape the closing brace, so it counts as
    unbalanced.
    """

    depth = 0
    escaped = False
    for character in value:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not escaped


def library_file_candidates(root: Path) -> list[Path]:
    """Return canonical and staged media for duplicate-content checks."""

    candidates: list[Path] = []
    for directory in (LIBRARY_DIRECTORY, INBOX_DIRECTORY):
        try:
            found = media_files(root, directory)
        except MediaError as error:
            raise IntakeError(str(error)) from error
        for candidate in found:
            if candidate.is_symlink():
                raise IntakeError(
                    "library media must not be a symlink: "
                    f"{candidate.relative_to(root)}"
                )
            candidates.append(candidate)
    return candidates


@dataclass
class PlanState:
    root: Path
    topic_path: str
    topic_parts: tuple[str, ...]
    existing_entries: dict[str, BibEntry]
    existing_catalog: dict[str, list[CatalogItem]]
    existing_files: set[Path]
    existing_dois: set[str]
    existing_isbns: set[str]
    existing_identifiers: dict[str, set[str]]
    # Record identity -> citation keys that already share it.
    existing_titles: dict[str, list[str]]
    new_keys: set[str] = field(default_factory=set)
    touched_keys: set[str] = field(default_factory=set)
    new_dois: set[str] = field(default_factory=set)
    new_isbns: set[str] = field(default_factory=set)
    new_identifiers: dict[str, set[str]] = field(default_factory=dict)
    new_titles: dict[str, list[str]] = field(default_factory=dict)
    new_sources: set[Path] = field(default_factory=set)
    new_targets: set[Path] = field(default_factory=set)
    new_hashes: dict[str, Path] = field(default_factory=dict)


def parse_topic(manifest: dict[str, Any]) -> tuple[str, tuple[str, ...], list[str]]:
    unknown_root = set(manifest) - MANIFEST_PROPERTIES - LEGACY_MANIFEST_PROPERTIES
    if unknown_root:
        raise IntakeError(
            "manifest has unsupported top-level properties: "
            + ", ".join(sorted(unknown_root))
        )
    if "$schema" in manifest and not isinstance(manifest["$schema"], str):
        raise IntakeError("manifest.$schema must be a string")
    topic = manifest.get("topic")
    if not isinstance(topic, dict):
        raise IntakeError("manifest.topic must be an object")
    unknown_topic = set(topic) - TOPIC_PROPERTIES
    if unknown_topic:
        raise IntakeError(
            "manifest.topic has unsupported properties: "
            + ", ".join(sorted(unknown_topic))
        )
    topic_path = require_text(topic, "path", "topic")
    topic_parts = tuple(topic_path.split("/"))
    if not topic_parts or any(not TOPIC_RE.fullmatch(part) for part in topic_parts):
        raise IntakeError(
            "topic.path must contain only canonical PascalCase components"
        )

    headings_raw = topic.get("headings")
    if not isinstance(headings_raw, list) or len(headings_raw) != len(topic_parts):
        raise IntakeError(
            "topic.headings must contain one readable heading per path component"
        )
    headings: list[str] = []
    for index, heading in enumerate(headings_raw):
        if not isinstance(heading, str) or not SAFE_HEADING_RE.fullmatch(
            heading.strip()
        ):
            raise IntakeError(f"topic.headings[{index}] is not safe plain heading text")
        clean_heading = heading.strip()
        if heading_component(clean_heading).casefold() != topic_parts[index].casefold():
            raise IntakeError(
                f"topic.headings[{index}] must match topic.path component "
                f"{topic_parts[index]} when spacing, punctuation, and case are ignored"
            )
        headings.append(clean_heading)
    return topic_path, topic_parts, headings


def manifest_items(manifest: dict[str, Any]) -> tuple[str, list[Any]]:
    if "items" in manifest and "papers" in manifest:
        raise IntakeError("manifest must use items or legacy papers, not both")
    collection_key = "papers" if "papers" in manifest else "items"
    items = manifest.get(collection_key)
    if not isinstance(items, list) or not items:
        raise IntakeError(f"manifest.{collection_key} must be a non-empty array")
    return collection_key, items


def parse_sidecars(
    raw_item: dict[str, Any], context: str, root: Path
) -> tuple[Path, ...]:
    raw_sidecars = raw_item.get("sidecars", [])
    if not isinstance(raw_sidecars, list):
        raise IntakeError(f"{context}.sidecars must be an array")
    sidecars: list[Path] = []
    for index, value in enumerate(raw_sidecars):
        if not isinstance(value, str) or not value.strip():
            raise IntakeError(f"{context}.sidecars[{index}] must be a path string")
        sidecar = resolve_in_root(root, value.strip(), f"{context}.sidecars[{index}]")
        if not sidecar.is_file() or sidecar.is_symlink():
            raise IntakeError(f"sidecar is not a regular file: {value}")
        if sidecar.suffix.casefold() not in {".bib", ".bibtex"}:
            raise IntakeError(f"sidecar must end in .bib or .bibtex: {value}")
        if sidecar in {root / "library.bib", root / "examples/references.bib"}:
            raise IntakeError(
                f"refusing to treat a canonical database as a sidecar: {value}"
            )
        sidecars.append(sidecar)
    return tuple(sidecars)


def parse_metadata_sources(raw_item: dict[str, Any], context: str) -> tuple[str, ...]:
    raw_sources = raw_item.get("metadata_sources", [])
    if not isinstance(raw_sources, list):
        raise IntakeError(f"{context}.metadata_sources must be an array")
    sources: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_sources):
        source_context = f"{context}.metadata_sources[{index}]"
        if not isinstance(value, str) or not value.strip():
            raise IntakeError(f"{source_context} must be a non-empty URL")
        source = value.strip()
        if not is_safe_web_url(source):
            raise IntakeError(f"{source_context} must be an HTTP(S) URL")
        identity = source.casefold()
        if identity in seen:
            raise IntakeError(f"duplicate metadata source URL: {source}")
        seen.add(identity)
        sources.append(source)
    return tuple(sources)


def resolve_document(
    raw_item: dict[str, Any],
    context: str,
    state: PlanState,
    *,
    attachment: bool,
) -> tuple[Path, Path, str]:
    if "source_file" in raw_item and "source_pdf" in raw_item:
        raise IntakeError(
            f"{context} must use source_file or legacy source_pdf, not both"
        )
    if attachment and "source_pdf" in raw_item:
        raise IntakeError(f"{context} attachments must use source_file")
    source_key = (
        "source_file"
        if "source_file" in raw_item
        else "source_pdf"
        if "source_pdf" in raw_item
        else "source_file"
    )
    source_value = require_text(raw_item, source_key, context)
    source_file = resolve_in_root(state.root, source_value, f"{context}.{source_key}")
    if not source_file.is_file() or source_file.is_symlink():
        raise IntakeError(
            f"{context}.{source_key} is not a regular file: {source_value}"
        )
    if source_key == "source_pdf" and source_file.suffix.casefold() != ".pdf":
        raise IntakeError(
            f"{context}.source_pdf is legacy and accepts only PDF; use source_file"
        )
    try:
        validate_media(source_file)
    except MediaError as error:
        raise IntakeError(str(error)) from error
    if source_file in state.existing_files:
        raise IntakeError(f"item is already referenced by library.bib: {source_value}")
    if source_file in state.new_sources:
        raise IntakeError(f"source file appears more than once: {source_value}")
    state.new_sources.add(source_file)

    canonical_filename = require_text(raw_item, "canonical_filename", context)
    if not NAME_RE.fullmatch(canonical_filename):
        raise IntakeError(
            f"{context}.canonical_filename must be ASCII PascalCase ending in "
            f".pdf, .epub, or .mobi: {canonical_filename}"
        )
    target_file = resolve_in_root(
        state.root,
        f"{LIBRARY_DIRECTORY}/{state.topic_path}/{canonical_filename}",
        f"{context}.canonical_filename",
    )
    if target_file.suffix.casefold() != source_file.suffix.casefold():
        raise IntakeError(
            f"{context}.canonical_filename must keep the source format: "
            f"{source_file.suffix.casefold()}"
        )
    if target_file in state.existing_files or target_file in state.new_targets:
        raise IntakeError(
            f"multiple records target the same path: {target_file.relative_to(state.root)}"
        )
    if target_file.exists() and target_file != source_file:
        raise IntakeError(
            f"destination already exists: {target_file.relative_to(state.root)}"
        )
    state.new_targets.add(target_file)

    digest = sha256(source_file)
    duplicate_source = state.new_hashes.get(digest)
    if duplicate_source:
        raise IntakeError(
            f"duplicate file content in manifest: {source_value} and "
            f"{duplicate_source.relative_to(state.root)}"
        )
    state.new_hashes[digest] = source_file
    return source_file, target_file, digest


def parse_new_fields(
    raw_item: dict[str, Any],
    context: str,
    entry_type: str,
    topic_parts: tuple[str, ...],
    pending: bool,
    target_file: Path | None,
    root: Path,
) -> tuple[str, str, dict[str, str]]:
    display_title = normalize_space(raw_item.get("title"), f"{context}.title")
    bib_title = normalize_space(
        raw_item.get("bib_title", display_title), f"{context}.bib_title"
    )
    if not braces_are_balanced(bib_title):
        raise IntakeError(
            f"unbalanced braces or a trailing backslash in {context}.bib_title"
        )
    if title_identity(display_title) != title_identity(bib_title):
        raise IntakeError(
            f"{context}.bib_title must represent the same title as {context}.title"
        )

    raw_fields = raw_item.get("fields")
    if not isinstance(raw_fields, dict):
        raise IntakeError(f"{context}.fields must be an object")
    if any(str(name).casefold() in RESERVED_FIELDS for name in raw_fields):
        raise IntakeError(
            f"{context}.fields must not override title, keywords, file, or "
            f"{DISTINCT_FROM_FIELD}; use {context}.distinct_from for the latter"
        )

    fields: dict[str, str] = {}
    for field_name, field_value in raw_fields.items():
        if not isinstance(field_name, str) or not FIELD_NAME_RE.fullmatch(field_name):
            raise IntakeError(f"invalid BibTeX field name in {context}: {field_name!r}")
        normalized_name = field_name.casefold()
        if normalized_name in fields:
            raise IntakeError(
                f"duplicate BibTeX field name in {context}: {normalized_name}"
            )
        if normalized_name == "isbn" and not isinstance(field_value, str):
            raise IntakeError(f"{context}.fields.isbn must be a string")
        normalized_value = normalize_space(
            field_value, f"{context}.fields.{field_name}"
        )
        if not braces_are_balanced(normalized_value):
            raise IntakeError(
                "unbalanced braces or a trailing backslash in "
                f"{context}.fields.{field_name}"
            )
        fields[normalized_name] = normalized_value

    if not fields.get("author") and not fields.get("editor"):
        raise IntakeError(f"{context}.fields requires author or editor")
    date_value = fields.get("date", fields.get("year"))
    if date_value is None:
        raise IntakeError(f"{context}.fields requires date or year")
    for date_field in ("date", "year"):
        if date_field in fields and not is_canonical_date(
            fields[date_field], year_only=date_field == "year"
        ):
            raise IntakeError(
                f"{context}.fields.{date_field} must be YYYY, YYYY-MM, or YYYY-MM-DD"
            )
    if "date" in fields and "year" in fields:
        if fields["date"][:4] != fields["year"][:4]:
            raise IntakeError(f"{context}.fields.date and year disagree")

    fields["title"] = bib_title
    doi = fields.get("doi")
    if doi:
        doi = normalize_doi(doi)
        if not is_canonical_doi(doi):
            raise IntakeError(f"invalid DOI in {context}: {fields['doi']}")
        fields["doi"] = doi
        fields.setdefault("url", f"https://doi.org/{doi}")

    isbn = fields.get("isbn")
    if isbn:
        if not is_valid_isbn(isbn):
            raise IntakeError(f"invalid ISBN in {context}: {isbn}")
        fields["isbn"] = normalize_isbn(isbn)

    for name in IDENTIFIER_FIELDS:
        if name not in fields:
            continue
        identifier = normalize_identifier(name, fields[name])
        if not is_canonical_identifier(name, identifier):
            raise IntakeError(f"invalid {name} identifier in {context}: {fields[name]}")
        fields[name] = identifier

    url = fields.get("url")
    if url and is_audiovisual(entry_type) and not is_safe_web_url(url):
        raise IntakeError(
            f"{context}.fields.url must be an HTTP(S) URL without credentials; "
            "it becomes the catalog [URL] link"
        )

    fields["keywords"] = ", ".join(topic_parts)
    if pending:
        fields["file"] = ""
    else:
        assert target_file is not None
        fields["file"] = target_file.relative_to(root).as_posix()
    return display_title, bib_title, fields


def parse_distinct_from(
    raw_item: dict[str, Any], context: str, citation_key: str
) -> list[str]:
    """Return the reviewed keys of distinct works that share this identity."""

    if "distinct_from" not in raw_item:
        return []
    raw_keys = raw_item["distinct_from"]
    if not isinstance(raw_keys, list) or not raw_keys:
        raise IntakeError(
            f"{context}.distinct_from must be a non-empty array of citation keys"
        )
    keys: list[str] = []
    for index, value in enumerate(raw_keys):
        if not isinstance(value, str) or not KEY_RE.fullmatch(value.strip()):
            raise IntakeError(
                f"{context}.distinct_from[{index}] must be a citation key"
            )
        key = value.strip()
        if key == citation_key:
            raise IntakeError(f"{context}.distinct_from cannot list the record itself")
        if key in keys:
            raise IntakeError(f"duplicate {context}.distinct_from key: {key}")
        keys.append(key)
    return keys


def build_new_plan(
    raw_item: dict[str, Any], context: str, state: PlanState
) -> ItemPlan:
    unknown = set(raw_item) - NEW_ITEM_PROPERTIES - LEGACY_ITEM_PROPERTIES
    if unknown:
        raise IntakeError(
            f"{context} has unsupported properties: " + ", ".join(sorted(unknown))
        )
    pending = raw_item.get("pending", False)
    if not isinstance(pending, bool):
        raise IntakeError(f"{context}.pending must be true or false")
    source_file: Path | None = None
    target_file: Path | None = None
    digest: str | None = None
    if pending:
        forbidden = {
            name
            for name in ("source_file", "source_pdf", "canonical_filename")
            if name in raw_item
        }
        if forbidden:
            raise IntakeError(
                f"{context} is pending and must omit file properties: "
                + ", ".join(sorted(forbidden))
            )
    else:
        source_file, target_file, digest = resolve_document(
            raw_item, context, state, attachment=False
        )

    citation_key = require_text(raw_item, "citation_key", context)
    if not KEY_RE.fullmatch(citation_key):
        raise IntakeError(
            f"citation key must follow firstauthorYYYYshorttitle: {citation_key}"
        )
    if citation_key in state.existing_entries or citation_key in state.new_keys:
        raise IntakeError(f"duplicate citation key: {citation_key}")
    if citation_key in state.existing_catalog:
        raise IntakeError(f"citation key already appears in main.typ: {citation_key}")
    state.new_keys.add(citation_key)

    entry_type = raw_item.get("entry_type", "article")
    if not isinstance(entry_type, str) or not ENTRY_TYPE_RE.fullmatch(entry_type):
        raise IntakeError(f"{context}.entry_type must contain letters only")
    entry_type = entry_type.casefold()
    display_title, bib_title, fields = parse_new_fields(
        raw_item,
        context,
        entry_type,
        state.topic_parts,
        pending,
        target_file,
        state.root,
    )
    distinct_from = parse_distinct_from(raw_item, context, citation_key)
    identity = record_identity(entry_type, fields)
    sharing = [
        *state.existing_titles.get(identity, []),
        *state.new_titles.get(identity, []),
    ]
    unrelated = [key for key in distinct_from if key not in sharing]
    if unrelated:
        raise IntakeError(
            f"{context}.distinct_from names records that do not share this "
            f"record's identity: {', '.join(unrelated)}"
        )
    unconfirmed = [key for key in sharing if key not in distinct_from]
    if unconfirmed:
        conflict = (
            "duplicate recording (same title, release year, and first creator)"
            if is_audiovisual(entry_type)
            else "duplicate normalized title"
        )
        raise IntakeError(
            f"{conflict}: {display_title} (matches {', '.join(unconfirmed)}); "
            f"if it is a verified distinct work, list those keys in "
            f"{context}.distinct_from"
        )
    state.new_titles.setdefault(identity, []).append(citation_key)
    if distinct_from:
        fields[DISTINCT_FROM_FIELD] = ", ".join(distinct_from)

    doi = fields.get("doi")
    if doi:
        doi_identity = doi.casefold()
        if doi_identity in state.existing_dois or doi_identity in state.new_dois:
            raise IntakeError(f"duplicate DOI: {doi}")
        state.new_dois.add(doi_identity)
    isbn = fields.get("isbn")
    if isbn:
        if isbn in state.existing_isbns or isbn in state.new_isbns:
            raise IntakeError(f"duplicate ISBN: {isbn}")
        state.new_isbns.add(isbn)
    for name in IDENTIFIER_FIELDS:
        identifier = fields.get(name)
        if not identifier:
            continue
        new_identifiers = state.new_identifiers.setdefault(name, set())
        if (
            identifier in state.existing_identifiers.get(name, set())
            or identifier in new_identifiers
        ):
            raise IntakeError(f"duplicate {name} identifier: {identifier}")
        new_identifiers.add(identifier)
    if target_file is not None:
        relative_target = target_file.relative_to(state.root).as_posix()
        if any(
            item.path == relative_target
            for items in state.existing_catalog.values()
            for item in items
        ):
            raise IntakeError(
                f"library file path already appears in main.typ: {relative_target}"
            )

    return ItemPlan(
        source_file=source_file,
        target_file=target_file,
        citation_key=citation_key,
        entry_type=entry_type,
        display_title=catalog_title(fields),
        fields=fields,
        sidecars=parse_sidecars(raw_item, context, state.root),
        metadata_sources=parse_metadata_sources(raw_item, context),
        digest=digest,
    )


def build_attachment_plan(
    raw_item: dict[str, Any], context: str, state: PlanState
) -> ItemPlan:
    unknown = set(raw_item) - ATTACHMENT_PROPERTIES
    if unknown:
        raise IntakeError(
            f"{context} has unsupported attachment properties: "
            + ", ".join(sorted(unknown))
        )
    forbidden = {
        name
        for name in ("pending", "entry_type", "title", "bib_title", "fields")
        if name in raw_item
    }
    if forbidden:
        raise IntakeError(
            f"{context} is an attachment and must omit metadata properties: "
            + ", ".join(sorted(forbidden))
        )
    citation_key = require_text(raw_item, "citation_key", context)
    if not KEY_RE.fullmatch(citation_key):
        raise IntakeError(
            f"citation key must follow firstauthorYYYYshorttitle: {citation_key}"
        )
    if citation_key in state.touched_keys:
        raise IntakeError(f"record is attached more than once: {citation_key}")
    state.touched_keys.add(citation_key)
    entry = state.existing_entries.get(citation_key)
    if entry is None:
        raise IntakeError(f"attachment citation key does not exist: {citation_key}")
    file_field = entry.field("file")
    if file_field is None:
        raise IntakeError(f"attachment target {citation_key} has no file field")
    if file_field.value.strip():
        raise IntakeError(f"attachment target is not pending: {citation_key}")
    if entry.topic != state.topic_parts:
        raise IntakeError(
            f"attachment topic does not match existing record {citation_key}"
        )
    catalog_items = state.existing_catalog.get(citation_key, [])
    if len(catalog_items) != 1:
        raise IntakeError(
            f"attachment target must appear once in main.typ: {citation_key}"
        )
    catalog_item = catalog_items[0]
    if catalog_item.path is not None:
        raise IntakeError(
            f"attachment target already has a catalog link: {citation_key}"
        )

    source_file, target_file, digest = resolve_document(
        raw_item, context, state, attachment=True
    )
    fields = dict(entry.fields)
    fields["file"] = target_file.relative_to(state.root).as_posix()
    return ItemPlan(
        source_file=source_file,
        target_file=target_file,
        citation_key=citation_key,
        entry_type=entry.entry_type,
        display_title=catalog_title(fields),
        fields=fields,
        sidecars=parse_sidecars(raw_item, context, state.root),
        metadata_sources=parse_metadata_sources(raw_item, context),
        digest=digest,
        existing_entry=entry,
        existing_catalog_item=catalog_item,
    )


def parse_manifest(
    root: Path,
    manifest: dict[str, Any],
    bib_text: str,
    main_text: str,
) -> tuple[str, list[str], list[ItemPlan]]:
    topic_path, topic_parts, headings = parse_topic(manifest)
    collection_key, raw_items = manifest_items(manifest)
    try:
        entries = parse_bibliography(bib_text, require_entries=False)
        catalog_items = parse_catalog(main_text)
    except (BibtexError, CatalogError) as error:
        raise IntakeError(str(error)) from error

    existing_catalog: dict[str, list[CatalogItem]] = {}
    for item in catalog_items:
        existing_catalog.setdefault(item.citation_key, []).append(item)
    existing_files = {
        resolve_in_root(root, entry.fields["file"], "existing BibTeX file field")
        for entry in entries
        if entry.fields.get("file", "").strip()
    }
    existing_titles: dict[str, list[str]] = {}
    for entry in entries:
        if entry.fields.get("title", "").strip():
            identity = record_identity(entry.entry_type, entry.fields)
            existing_titles.setdefault(identity, []).append(entry.citation_key)
    state = PlanState(
        root=root,
        topic_path=topic_path,
        topic_parts=topic_parts,
        existing_entries={entry.citation_key: entry for entry in entries},
        existing_catalog=existing_catalog,
        existing_files=existing_files,
        existing_dois={
            normalize_doi(entry.fields["doi"]).casefold()
            for entry in entries
            if entry.fields.get("doi", "").strip()
        },
        existing_isbns={
            normalize_isbn(entry.fields["isbn"])
            for entry in entries
            if entry.fields.get("isbn", "").strip()
            and is_valid_isbn(entry.fields["isbn"])
        },
        existing_identifiers={
            name: {
                normalize_identifier(name, entry.fields[name])
                for entry in entries
                if entry.fields.get(name, "").strip()
            }
            for name in IDENTIFIER_FIELDS
        },
        existing_titles=existing_titles,
    )

    plans: list[ItemPlan] = []
    for index, raw_item in enumerate(raw_items):
        context = f"{collection_key}[{index}]"
        if not isinstance(raw_item, dict):
            raise IntakeError(f"{context} must be an object")
        attach = raw_item.get("attach", False)
        if not isinstance(attach, bool):
            raise IntakeError(f"{context}.attach must be true or false")
        if attach:
            plans.append(build_attachment_plan(raw_item, context, state))
        else:
            plans.append(build_new_plan(raw_item, context, state))

    if all(plan.digest is None for plan in plans):
        return topic_path, headings, plans
    manifest_sources = {
        plan.source_file for plan in plans if plan.source_file is not None
    }
    existing_hashes: dict[str, Path] = {}
    for candidate in library_file_candidates(root):
        if candidate in manifest_sources:
            continue
        existing_hashes.setdefault(sha256(candidate), candidate)
    for plan in plans:
        if plan.digest is None:
            continue
        duplicate = existing_hashes.get(plan.digest)
        if duplicate:
            assert plan.source_file is not None
            raise IntakeError(
                f"file duplicates existing content: "
                f"{plan.source_file.relative_to(root)} and "
                f"{duplicate.relative_to(root)}"
            )
    return topic_path, headings, plans


def render_bibtex(plan: ItemPlan) -> str:
    preferred_order = [
        "author",
        "editor",
        "title",
        "subtitle",
        "series",
        "journaltitle",
        "booktitle",
        "date",
        "year",
        "volume",
        "number",
        "pages",
        "publisher",
        "location",
        "edition",
        "issn",
        "isbn",
        "doi",
        "url",
    ]
    ordered_names = [name for name in preferred_order if name in plan.fields]
    ordered_names.extend(
        sorted(
            name
            for name in plan.fields
            if name not in preferred_order and name not in {"keywords", "file"}
        )
    )
    ordered_names.extend(name for name in ("keywords", "file") if name in plan.fields)
    width = max(len(name) for name in ordered_names)

    lines = [f"@{plan.entry_type}{{{plan.citation_key},"]
    for index, field_name in enumerate(ordered_names):
        comma = "," if index < len(ordered_names) - 1 else ""
        lines.append(
            f"  {field_name.ljust(width)} = {{{plan.fields[field_name]}}}{comma}"
        )
    lines.append("}")
    return "\n".join(lines)


def insert_bibtex(bib_text: str, topic_path: str, plans: list[ItemPlan]) -> str:
    plans = [plan for plan in plans if not plan.attachment]
    if not plans:
        return bib_text
    topic_label = topic_path.replace("/", " / ")
    marker = f"% Topic: {topic_label}"
    entries = "\n\n".join(render_bibtex(plan) for plan in plans)
    marker_match = re.search(rf"(?m)^{re.escape(marker)}[ \t]*$", bib_text)

    if not marker_match:
        return f"{bib_text.rstrip()}\n\n{marker}\n\n{entries}\n"

    section_start = marker_match.end()
    next_marker = re.search(r"(?m)^% Topic: ", bib_text[section_start:])
    insert_at = section_start + next_marker.start() if next_marker else len(bib_text)
    before = bib_text[:insert_at].rstrip()
    after = bib_text[insert_at:].lstrip("\n")
    result = f"{before}\n\n{entries}\n"
    if after:
        result += f"\n{after}"
    return result


def update_bibtex(bib_text: str, topic_path: str, plans: list[ItemPlan]) -> str:
    replacements = []
    for plan in plans:
        if not plan.attachment:
            continue
        assert plan.existing_entry is not None
        file_field = plan.existing_entry.field("file")
        assert file_field is not None
        replacements.append((file_field, plan.fields["file"]))
    updated = replace_field_values(bib_text, replacements)
    return insert_bibtex(updated, topic_path, plans)


def find_section_end(lines: list[str], start: int, level: int, limit: int) -> int:
    for index in range(start, limit):
        match = HEADING_RE.fullmatch(lines[index].strip())
        if match and len(match.group(1)) <= level:
            return index
    return limit


def catalog_url(plan: ItemPlan) -> str | None:
    """Return the web page an album or film links to until it has local media."""

    if not is_audiovisual(plan.entry_type):
        return None
    return plan.fields.get("url") or None


def catalog_item(plan: ItemPlan, root: Path) -> list[str]:
    title_literal = json.dumps(plan.display_title, ensure_ascii=False)
    links: list[tuple[str, str]] = []
    if not plan.pending:
        assert plan.target_file is not None
        links.append(
            (
                plan.target_file.relative_to(root).as_posix(),
                plan.target_file.suffix.removeprefix(".").upper(),
            )
        )
    url = catalog_url(plan)
    if url:
        links.append((url, "URL"))

    lines = [
        f"- #reference-title(<{plan.citation_key}>)[",
        f"    #text({title_literal})",
    ]
    prefix = "  ] #h(0pt) "
    for target, label in links:
        target_literal = json.dumps(target, ensure_ascii=False)
        lines.append(f"{prefix}#link({target_literal})[")
        lines.append(f'    #text(size: 8pt, weight: "bold")[\\[{label}\\]]')
        prefix = "  ] "
    lines.append(f"{prefix}@{plan.citation_key}")
    return lines


def insert_catalog_items(
    main_text: str, headings: list[str], plans: list[ItemPlan], root: Path
) -> str:
    plans = [plan for plan in plans if not plan.attachment]
    if not plans:
        return main_text
    lines = main_text.splitlines()
    bibliography_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("#bibliography(")
        ),
        None,
    )
    if bibliography_index is None:
        raise IntakeError("main.typ has no #bibliography block")

    search_start = 0
    search_end = bibliography_index
    missing_level: int | None = None

    for level, heading in enumerate(headings, start=1):
        expected_component = heading_component(heading).casefold()
        match_index = next(
            (
                index
                for index in range(search_start, search_end)
                if (
                    (match := HEADING_RE.fullmatch(lines[index].strip())) is not None
                    and len(match.group(1)) == level
                    and heading_component(match.group(2)).casefold()
                    == expected_component
                )
            ),
            None,
        )
        if match_index is None:
            missing_level = level
            insertion_index = search_end
            break
        section_end = find_section_end(lines, match_index + 1, level, search_end)
        search_start = match_index + 1
        search_end = section_end
    else:
        # Items placed after a subtopic heading would belong to that subtopic,
        # so direct items go before the topic's first deeper heading.
        insertion_index = next(
            (
                index
                for index in range(search_start, search_end)
                if HEADING_RE.fullmatch(lines[index].strip())
            ),
            search_end,
        )

    payload: list[str] = []
    if insertion_index > 0 and lines[insertion_index - 1].strip():
        payload.append("")

    if missing_level is not None:
        for level in range(missing_level, len(headings) + 1):
            payload.append(f"{'=' * level} {headings[level - 1]}")
            payload.append("")

    for plan_index, plan in enumerate(plans):
        if plan_index:
            payload.append("")
        payload.extend(catalog_item(plan, root))

    if insertion_index < len(lines) and lines[insertion_index].strip():
        payload.append("")

    lines[insertion_index:insertion_index] = payload
    return "\n".join(lines).rstrip() + "\n"


def update_catalog(
    main_text: str, headings: list[str], plans: list[ItemPlan], root: Path
) -> str:
    replacements: list[tuple[int, int, str]] = []
    for plan in plans:
        if not plan.attachment:
            continue
        assert plan.existing_catalog_item is not None
        item = plan.existing_catalog_item
        replacement = "\n".join(catalog_item(plan, root)).rstrip() + "\n\n"
        replacements.append((item.start, item.end, replacement))
    updated = main_text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:].lstrip("\n")
    return insert_catalog_items(updated, headings, plans, root)


def snapshot(path: Path) -> Snapshot:
    if not path.exists():
        return Snapshot(False, b"", None)
    return Snapshot(True, path.read_bytes(), stat.S_IMODE(path.stat().st_mode))


def atomic_write(path: Path, data: bytes, mode: int = 0o664) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def restore(path: Path, saved: Snapshot) -> None:
    if saved.existed:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, saved.data, saved.mode or 0o664)
    else:
        path.unlink(missing_ok=True)


def ensure_directory(path: Path, root: Path) -> list[Path]:
    missing: list[Path] = []
    cursor = path
    while cursor != root and not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    path.mkdir(parents=True, exist_ok=True)
    return missing


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def batch_items(topic_plans: list[TopicPlan]) -> list[ItemPlan]:
    return [item for topic in topic_plans for item in topic.items]


def preflight_batch_files(root: Path, topic_plans: list[TopicPlan]) -> None:
    sources: dict[Path, Path] = {}
    targets: dict[Path, Path] = {}
    hashes: dict[str, Path] = {}
    for plan in batch_items(topic_plans):
        if plan.source_file is None or plan.target_file is None or plan.digest is None:
            continue
        prior_source = sources.get(plan.source_file)
        if prior_source is not None:
            raise IntakeError(
                "source file appears in more than one manifest: "
                f"{plan.source_file.relative_to(root)}"
            )
        prior_target = targets.get(plan.target_file)
        if prior_target is not None:
            raise IntakeError(
                "multiple manifests target the same path: "
                f"{plan.target_file.relative_to(root)}"
            )
        prior_hash = hashes.get(plan.digest)
        if prior_hash is not None:
            raise IntakeError(
                "duplicate file content across manifests: "
                f"{prior_hash.relative_to(root)} and "
                f"{plan.source_file.relative_to(root)}"
            )
        sources[plan.source_file] = plan.source_file
        targets[plan.target_file] = plan.source_file
        hashes[plan.digest] = plan.source_file


def phase_report_path(base: Path, *, applied: bool) -> Path:
    """Return the non-colliding report path for a dry run or apply."""

    name = base.name
    if name.casefold().endswith(".json"):
        name = name[:-5]
    if not name:
        raise IntakeError("--report-base must include a filename stem")
    phase = "applied" if applied else "dry-run"
    return base.with_name(f"{name}.{phase}.json")


def resolve_report_path(
    requested: Path | None,
    *,
    root: Path,
    force: bool,
    protected_paths: set[Path],
) -> Path | None:
    if requested is None:
        if force:
            raise IntakeError("--force-report requires --report-json or --report-base")
        return None
    raw_path = requested.expanduser()
    candidate = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
    absolute = Path(os.path.abspath(candidate))
    symlink = first_symlink_component(absolute)
    if symlink is not None:
        raise IntakeError(
            f"report output must not use a symlinked path component: {symlink}"
        )
    report_path = absolute.resolve()
    if report_path.suffix.casefold() != ".json":
        raise IntakeError("report output must end in .json")
    if report_path in protected_paths:
        raise IntakeError(f"report output conflicts with an intake path: {report_path}")
    if report_path.exists():
        if not report_path.is_file():
            raise IntakeError(f"report output is not a regular file: {report_path}")
        if not force:
            raise IntakeError(
                f"refusing to overwrite existing report without --force-report: "
                f"{report_path}"
            )
    try:
        relative = report_path.relative_to(root)
    except ValueError:
        if not report_path.parent.is_dir():
            raise IntakeError(
                "an external report output requires an existing parent directory: "
                f"{report_path.parent}"
            )
    else:
        if not relative.parts or (
            relative.parts[0] != "reports"
            and not report_path.name.endswith(".intake-report.json")
        ):
            raise IntakeError(
                "a report inside the repository must be beneath reports/ or end in "
                ".intake-report.json so Git ignore rules protect it"
            )
    return report_path


def intake_report(
    root: Path,
    topic_plans: list[TopicPlan],
    *,
    status: str,
    delete_sidecars: bool,
    output_name: str,
    catalog_updated: str,
) -> dict[str, Any]:
    topics = []
    for topic in topic_plans:
        items = []
        for plan in topic.items:
            source_file = (
                display_path(plan.source_file, root)
                if plan.source_file is not None
                else None
            )
            target_file = (
                display_path(plan.target_file, root)
                if plan.target_file is not None
                else None
            )
            items.append(
                {
                    "action": "attach" if plan.attachment else "add",
                    "citation_key": plan.citation_key,
                    "entry_type": plan.entry_type,
                    "title": plan.display_title,
                    "pending": plan.pending,
                    "source_file": source_file,
                    "destination_file": target_file,
                    "format": (
                        plan.source_file.suffix.removeprefix(".").upper()
                        if plan.source_file is not None
                        else None
                    ),
                    "sha256": plan.digest,
                    "fields": dict(plan.fields),
                    "metadata_sources": list(plan.metadata_sources),
                    "sidecars": [
                        {
                            "path": display_path(sidecar, root),
                            "disposition": (
                                "delete-after-success" if delete_sidecars else "retain"
                            ),
                        }
                        for sidecar in plan.sidecars
                    ],
                }
            )
        topics.append(
            {
                "manifest": display_path(topic.manifest_path, root),
                "topic": {
                    "path": topic.topic_path,
                    "headings": list(topic.headings),
                },
                "destination_directory": display_path(topic.topic_directory, root),
                "items": items,
            }
        )

    items = batch_items(topic_plans)
    applied = status == "applied"
    return {
        "report_version": 1,
        "contains_private_library_metadata": True,
        "status": status,
        "topics": topics,
        "summary": {
            "manifests": len(topic_plans),
            "topics": len({topic.topic_path for topic in topic_plans}),
            "items": len(items),
            "new_records": sum(not item.attachment for item in items),
            "attachments": sum(item.attachment for item in items),
            "pending_records": sum(item.pending for item in items),
            "local_documents": sum(not item.pending for item in items),
        },
        "sidecar_policy": "delete-after-success" if delete_sidecars else "retain",
        "validation": "passed" if applied else "not-run",
        "catalog_build": "passed" if applied else "not-run",
        "catalog_output": output_name,
        "catalog_updated": catalog_updated,
    }


def report_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_report(root: Path, path: Path, payload: dict[str, Any]) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, report_bytes(payload), 0o600)


def print_plan(
    root: Path,
    topic_plans: list[TopicPlan],
    delete: bool,
    output_name: str,
    apply: bool,
    report_path: Path | None,
    catalog_updated: str,
) -> None:
    if apply:
        print("APPLY PLAN — changes begin after this summary")
    elif report_path is None:
        print("DRY RUN — no files changed")
    else:
        print("DRY RUN — library state unchanged; report will be written")
    if len(topic_plans) > 1:
        print(f"BATCH {len(topic_plans)} manifest(s)")
    for topic_index, topic in enumerate(topic_plans):
        if topic_index or len(topic_plans) > 1:
            print()
        print(f"Manifest: {display_path(topic.manifest_path, root)}")
        print(f"Topic: {topic.topic_path}")
        print(f"Headings: {' > '.join(topic.headings)}")
        print(f"DIR   {topic.topic_directory.relative_to(root)} (create if missing)")
        for plan in topic.items:
            print()
            if plan.pending and is_audiovisual(plan.entry_type):
                print("FILE  PENDING LOCAL PATH (empty BibTeX file field)")
            elif plan.pending:
                print("FILE  PENDING DOWNLOAD (empty BibTeX file field)")
            else:
                assert plan.source_file is not None
                assert plan.target_file is not None
                action = "ATTACH" if plan.attachment else "MOVE  "
                print(f"{action} {plan.source_file.relative_to(root)}")
                print(f"   -> {plan.target_file.relative_to(root)}")
            print(f"KEY   {plan.citation_key}")
            if plan.source_file is not None:
                print(f"FORMAT {plan.source_file.suffix.removeprefix('.').upper()}")
            print(f"TITLE {plan.display_title}")
            if "doi" in plan.fields:
                print(f"DOI   {plan.fields['doi']}")
            if "isbn" in plan.fields:
                print(f"ISBN  {plan.fields['isbn']}")
            for name in IDENTIFIER_FIELDS:
                if name in plan.fields:
                    print(f"ID    {name} {plan.fields[name]}")
            url = catalog_url(plan)
            if url:
                print(f"LINK  [URL] {url}")
            if DISTINCT_FROM_FIELD in plan.fields:
                print(f"DISTINCT FROM {plan.fields[DISTINCT_FROM_FIELD]}")
            for metadata_source in plan.metadata_sources:
                print(f"META  {metadata_source}")
            for sidecar in plan.sidecars:
                action = "DELETE AFTER SUCCESS" if delete else "KEEP"
                print(f"{action} {sidecar.relative_to(root)}")
    print()
    items = batch_items(topic_plans)
    new_count = sum(not plan.attachment for plan in items)
    attachment_count = sum(plan.attachment for plan in items)
    if new_count:
        print(f"ADD {new_count} record(s) to library.bib and main.typ")
    if attachment_count:
        print(f"UPDATE {attachment_count} pending record(s) and catalog link(s)")
    print("RUN scripts/validate-library.sh")
    print(f"BUILD {output_name}")
    print(f"DATE  Last updated: {catalog_updated}")
    if report_path is not None:
        print(f"REPORT {display_path(report_path, root)}")


def apply_plan(
    root: Path,
    topic_plans: list[TopicPlan],
    new_bib: str,
    new_main: str,
    output_path: Path,
    delete_sidecars: bool,
    report_path: Path | None,
    report_data: bytes | None,
) -> None:
    bib_path = root / "library.bib"
    main_path = root / "main.typ"
    validator = root / "scripts/validate-library.sh"
    if not validator.is_file():
        raise IntakeError(f"missing validator: {validator.relative_to(root)}")
    typst = shutil.which("typst")
    if not typst:
        raise IntakeError("typst is required for transactional validation and build")

    plans = batch_items(topic_plans)
    unique_sidecars = sorted(
        {sidecar for plan in plans for sidecar in plan.sidecars},
        key=lambda path: str(path),
    )
    protected_paths = {bib_path, main_path, output_path}
    for sidecar in unique_sidecars:
        if sidecar in protected_paths or sidecar in {
            plan.source_file for plan in plans if plan.source_file is not None
        }:
            raise IntakeError(
                f"refusing unsafe sidecar deletion target: {sidecar.relative_to(root)}"
            )

    saved = {
        bib_path: snapshot(bib_path),
        main_path: snapshot(main_path),
        output_path: snapshot(output_path),
    }
    if report_path is not None:
        saved[report_path] = snapshot(report_path)
    if delete_sidecars:
        saved.update({sidecar: snapshot(sidecar) for sidecar in unique_sidecars})

    moved: list[tuple[Path, Path]] = []
    created_directories: set[Path] = set()
    temporary_output = root / f".{output_path.stem}.intake-{os.getpid()}.pdf"
    temporary_output.unlink(missing_ok=True)

    try:
        with interrupt_on_termination():
            for topic in topic_plans:
                created_directories.update(
                    ensure_directory(topic.topic_directory, root)
                )
            for plan in plans:
                if plan.pending:
                    continue
                assert plan.source_file is not None
                assert plan.target_file is not None
                if plan.source_file == plan.target_file:
                    continue
                created_directories.update(
                    ensure_directory(plan.target_file.parent, root)
                )
                # Record the move first; rollback skips one that never happened.
                moved.append((plan.source_file, plan.target_file))
                shutil.move(str(plan.source_file), str(plan.target_file))

            atomic_write(
                bib_path, new_bib.encode("utf-8"), saved[bib_path].mode or 0o664
            )
            atomic_write(
                main_path, new_main.encode("utf-8"), saved[main_path].mode or 0o664
            )

            validator_command = (
                [str(validator)]
                if os.access(validator, os.X_OK)
                else ["bash", str(validator)]
            )
            # The build below is the compile check, so validation skips its own.
            validation = subprocess.run(
                [*validator_command, "--no-compile"], cwd=root, check=False
            )
            if validation.returncode != 0:
                raise IntakeError(
                    "library validation failed; changes will be rolled back"
                )

            compilation = subprocess.run(
                [typst, "compile", "main.typ", temporary_output.name],
                cwd=root,
                check=False,
            )
            if compilation.returncode != 0:
                raise IntakeError("catalog build failed; changes will be rolled back")
            os.replace(temporary_output, output_path)

            if delete_sidecars:
                for sidecar in unique_sidecars:
                    sidecar.unlink()

            if report_path is not None:
                assert report_data is not None
                try:
                    report_path.relative_to(root)
                except ValueError:
                    pass
                else:
                    created_directories.update(
                        ensure_directory(report_path.parent, root)
                    )
                atomic_write(report_path, report_data, 0o600)

    # BaseException also covers Ctrl-C, which must not leave a half-applied intake.
    except BaseException as error:
        with interrupts_ignored():
            roll_back(saved, moved, created_directories, temporary_output)
        if isinstance(error, IntakeError):
            raise
        if isinstance(error, KeyboardInterrupt):
            raise IntakeInterrupted("Ctrl-C (SIGINT)") from error
        if isinstance(error, Exception):
            raise IntakeError(
                f"intake failed and rollback was attempted: {error}"
            ) from error
        raise
    finally:
        temporary_output.unlink(missing_ok=True)


def roll_back(
    saved: dict[Path, Snapshot],
    moved: list[tuple[Path, Path]],
    created_directories: set[Path],
    temporary_output: Path,
) -> None:
    """Restore snapshots, move library files back, and remove new directories."""

    for path, saved_path in saved.items():
        try:
            restore(path, saved_path)
        except OSError as restore_error:
            print(f"ROLLBACK ERROR restoring {path}: {restore_error}", file=sys.stderr)
    for source, target in reversed(moved):
        try:
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        except OSError as restore_error:
            print(
                f"ROLLBACK ERROR restoring {source}: {restore_error}",
                file=sys.stderr,
            )
    for directory in sorted(
        created_directories, key=lambda path: len(path.parts), reverse=True
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    temporary_output.unlink(missing_ok=True)


def pending_status(root: Path, *, as_json: bool) -> int:
    bib_path = root / "library.bib"
    if not bib_path.is_file():
        raise IntakeError("the library root must contain library.bib")
    try:
        entries = parse_bibliography(
            bib_path.read_text(encoding="utf-8"), require_entries=False
        )
    except (OSError, UnicodeError, BibtexError) as error:
        raise IntakeError(f"cannot parse library.bib: {error}") from error

    records = []
    for entry in entries:
        if entry.fields.get("file", "").strip():
            continue
        topic = list(entry.topic or ())
        records.append(
            {
                "citation_key": entry.citation_key,
                "entry_type": entry.entry_type,
                "title": catalog_title(entry.fields),
                "doi": entry.fields.get("doi") or None,
                "url": entry.fields.get("url") or None,
                "topic": topic,
                "expected_directory": str(Path(LIBRARY_DIRECTORY, *topic)),
            }
        )
    records.sort(key=lambda record: str(record["citation_key"]))
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        print(f"Pending downloads: {len(records)}")
        for record in records:
            print(
                f"- {record['citation_key']}: {record['title']} "
                f"[{record['expected_directory']}]"
            )
    return 0


def topic_status(root: Path, *, as_json: bool) -> int:
    bib_path = root / "library.bib"
    main_path = root / "main.typ"
    if not bib_path.is_file() or not main_path.is_file():
        raise IntakeError("the library root must contain library.bib and main.typ")
    try:
        entries = parse_bibliography(
            bib_path.read_text(encoding="utf-8"), require_entries=False
        )
        catalog_items = parse_catalog(main_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, BibtexError, CatalogError) as error:
        raise IntakeError(f"cannot read the catalog taxonomy: {error}") from error

    catalog_by_key: dict[str, list[CatalogItem]] = {}
    for item in catalog_items:
        catalog_by_key.setdefault(item.citation_key, []).append(item)

    topics: dict[tuple[str, ...], dict[str, Any]] = {}
    for entry in entries:
        if not entry.topic:
            continue
        topic = entry.topic
        matching_items = catalog_by_key.get(entry.citation_key, [])
        headings = (
            matching_items[0].headings
            if len(matching_items) == 1
            and len(matching_items[0].headings) == len(topic)
            else topic
        )
        record = topics.setdefault(
            topic,
            {
                "path": "/".join(topic),
                "headings": list(headings),
                "records": 0,
                "local_files": 0,
                "pending": 0,
                "directory": str(Path(LIBRARY_DIRECTORY, *topic)),
            },
        )
        record["records"] += 1
        if entry.fields.get("file", "").strip():
            record["local_files"] += 1
        else:
            record["pending"] += 1

    records = sorted(topics.values(), key=lambda record: str(record["path"]).casefold())
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        print(f"Topics: {len(records)}")
        for record in records:
            readable = " / ".join(record["headings"])
            print(
                f"- {readable} [{record['path']}]: {record['records']} record(s), "
                f"{record['local_files']} local, {record['pending']} pending"
            )
    return 0


def run_status(arguments: list[str]) -> int:
    args = parse_status_args(arguments)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise IntakeError(f"library root does not exist: {root}")
    with library_lock(root, args.lock_timeout):
        return pending_status(root, as_json=args.json)


def run_topics(arguments: list[str]) -> int:
    args = parse_topics_args(arguments)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise IntakeError(f"library root does not exist: {root}")
    with library_lock(root, args.lock_timeout):
        return topic_status(root, as_json=args.json)


def run_manifest(args: argparse.Namespace) -> int:
    if args.write_template is not None:
        if (
            args.apply
            or args.delete_sidecars
            or args.report_json
            or args.report_base
            or args.force_report
        ):
            raise IntakeError(
                "--write-template cannot be combined with apply, sidecar, or report options"
            )
        write_template(args.write_template)
        return 0

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise IntakeError(f"library root does not exist: {root}")
    if Path(args.output).name != args.output or not args.output.endswith(".pdf"):
        raise IntakeError("--output must be a root-level filename ending in .pdf")
    output_path = root / args.output

    with library_lock(root, args.lock_timeout):
        bib_path = root / "library.bib"
        main_path = root / "main.typ"
        if not bib_path.is_file() or not main_path.is_file():
            raise IntakeError("the library root must contain library.bib and main.typ")

        bib_text = bib_path.read_text(encoding="utf-8")
        main_text = main_path.read_text(encoding="utf-8")
        manifest_paths = [path.expanduser().resolve() for path in args.manifest]
        if len(set(manifest_paths)) != len(manifest_paths):
            raise IntakeError("the same manifest was supplied more than once")

        topic_plans: list[TopicPlan] = []
        new_bib = bib_text
        new_main = main_text
        for manifest_path in manifest_paths:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise IntakeError(
                    f"cannot read manifest {manifest_path}: {error}"
                ) from error
            if not isinstance(manifest, dict):
                raise IntakeError(
                    f"manifest root must be a JSON object: {manifest_path}"
                )

            try:
                topic_path, headings, plans = parse_manifest(
                    root, manifest, new_bib, new_main
                )
            except IntakeError as error:
                raise IntakeError(
                    f"{display_path(manifest_path, root)}: {error}"
                ) from error
            topic_directory = resolve_in_root(
                root,
                f"{LIBRARY_DIRECTORY}/{topic_path}",
                "topic.path",
            )
            topic_plans.append(
                TopicPlan(
                    manifest_path=manifest_path,
                    topic_path=topic_path,
                    headings=tuple(headings),
                    topic_directory=topic_directory,
                    items=tuple(plans),
                )
            )
            new_bib = update_bibtex(new_bib, topic_path, plans)
            new_main = update_catalog(new_main, headings, plans, root)

        catalog_updated = current_catalog_date()
        new_main = update_catalog_date(new_main, catalog_updated)
        preflight_batch_files(root, topic_plans)
        # Apply the validator's text rules now, so the dry run fails wherever
        # the post-apply validation would.
        planned = check_sources(new_bib, new_main)
        if planned.errors:
            raise IntakeError(
                "the planned library state would fail validation:\n"
                + "\n".join(f"  - {error}" for error in planned.errors)
            )
        plans = batch_items(topic_plans)
        protected_paths = {
            bib_path,
            main_path,
            output_path,
            *manifest_paths,
            *(plan.source_file for plan in plans if plan.source_file is not None),
            *(plan.target_file for plan in plans if plan.target_file is not None),
            *(sidecar for plan in plans for sidecar in plan.sidecars),
        }
        report_request = args.report_json
        if args.report_base is not None:
            report_request = phase_report_path(args.report_base, applied=args.apply)
        report_path = resolve_report_path(
            report_request,
            root=root,
            force=args.force_report,
            protected_paths=protected_paths,
        )

        print_plan(
            root,
            topic_plans,
            args.delete_sidecars,
            args.output,
            args.apply,
            report_path,
            catalog_updated,
        )
        if not args.apply:
            if report_path is not None:
                write_report(
                    root,
                    report_path,
                    intake_report(
                        root,
                        topic_plans,
                        status="dry-run",
                        delete_sidecars=args.delete_sidecars,
                        output_name=args.output,
                        catalog_updated=catalog_updated,
                    ),
                )
            print("Dry run complete. Re-run with --apply after reviewing this plan.")
            return 0

        applied_report = (
            report_bytes(
                intake_report(
                    root,
                    topic_plans,
                    status="applied",
                    delete_sidecars=args.delete_sidecars,
                    output_name=args.output,
                    catalog_updated=catalog_updated,
                )
            )
            if report_path is not None
            else None
        )
        apply_plan(
            root,
            topic_plans,
            new_bib,
            new_main,
            output_path,
            args.delete_sidecars,
            report_path,
            applied_report,
        )
        print()
        print(
            f"Applied {len(plans)} item(s) across "
            f"{len({topic.topic_path for topic in topic_plans})} topic(s) successfully."
        )
        print(f"Updated: {bib_path.relative_to(root)}, {main_path.relative_to(root)}")
        print(f"Built: {output_path.relative_to(root)}")
        if report_path is not None:
            print(f"Report: {display_path(report_path, root)}")
        return 0


def main() -> int:
    try:
        arguments = sys.argv[1:]
        if arguments[:1] == ["status"]:
            return run_status(arguments[1:])
        if arguments[:1] == ["topics"]:
            return run_topics(arguments[1:])
        return run_manifest(parse_args())
    except IntakeInterrupted as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return INTERRUPTED_EXIT_CODE
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return INTERRUPTED_EXIT_CODE
    except (BibtexError, CatalogError, IntakeError, MediaError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
