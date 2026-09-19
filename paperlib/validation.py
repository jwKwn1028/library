"""Semantic consistency checks for a private paper-library instance."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from paperlib.bibtex import (
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
    key_list,
    normalize_doi,
    normalize_identifier,
    normalize_isbn,
    parse_bibliography,
    record_identity,
    title_identity,
)
from paperlib.catalog import (
    CITATION_RE,
    CatalogError,
    catalog_source,
    heading_component,
    parse_catalog,
)
from paperlib.media import (
    LIBRARY_DIRECTORY,
    MediaError,
    media_files,
    sha256,
    validate_media,
)


KEY_RE = re.compile(r"^[a-z]+[0-9]{4}[a-z0-9]+$")
TOPIC_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*\.(?:epub|mobi|pdf)$")


@dataclass(frozen=True)
class ValidationResult:
    entries: int
    files: int
    pending: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class SourceCheck:
    """The text-only result for one library.bib and main.typ pair."""

    entries: tuple[BibEntry, ...]
    local_paths: tuple[str, ...]
    pending: int
    errors: tuple[str, ...]
    complete: bool


def _duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if value and count > 1)


def _safe_local_path(root: Path, value: str) -> tuple[Path | None, str | None]:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None, f"library file path leaves the root: {value}"
    candidate = root / relative
    try:
        resolved = candidate.resolve()
    except OSError as error:
        return None, f"cannot resolve library file path {value}: {error}"
    if not resolved.is_relative_to(root):
        return None, f"library file path leaves the root through a symlink: {value}"
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            return None, f"library file path uses a symlink: {value}"
    return candidate, None


def _disk_media(root: Path) -> tuple[list[str], list[str]]:
    """Return canonical media under Library/; other directories are not scanned."""

    try:
        candidates = media_files(root, LIBRARY_DIRECTORY)
    except MediaError as error:
        return [], [str(error)]
    paths: list[str] = []
    errors: list[str] = []
    for candidate in candidates:
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            errors.append(f"library media path is a symlink: {relative}")
        paths.append(relative)
    return paths, errors


def check_sources(bib_text: str, main_text: str) -> SourceCheck:
    """Check bibliography and catalog semantics without reading the disk.

    The intake engine runs these same checks on its planned text during a dry
    run, so a dry run and an apply agree on every text-level rule.
    """

    try:
        entries = parse_bibliography(bib_text)
    except BibtexError as error:
        return SourceCheck((), (), 0, (f"cannot parse library.bib: {error}",), False)
    errors: list[str] = []
    if "download pending" in main_text.casefold():
        errors.append("catalog contains deprecated visible download-pending labels")
    try:
        catalog_items = parse_catalog(main_text)
    except CatalogError as error:
        errors.append(f"cannot parse main.typ: {error}")
        return SourceCheck(tuple(entries), (), 0, tuple(errors), False)
    bibliography_bindings = re.findall(
        r'(?m)^#let\s+bibliography-file\s*=\s*"library\.bib"\s*$', main_text
    )
    if len(bibliography_bindings) != 1:
        errors.append("main.typ must select library.bib exactly once")
    bibliography_targets = re.findall(
        r"(?ms)^#bibliography\s*\(.*?^\)\s*<references>\s*$", main_text
    )
    if len(bibliography_targets) != 1:
        errors.append("main.typ must label its bibliography <references> exactly once")
    title_link_style_bindings = re.findall(
        r'(?m)^#let\s+title-link-style\s*=\s*"styles/title-link\.csl"\s*$',
        main_text,
    )
    if len(title_link_style_bindings) != 1:
        errors.append("main.typ must select styles/title-link.csl exactly once")
    reference_title_helpers = re.findall(
        r"(?ms)^#let\s+reference-title\s*\(\s*key\s*,\s*body\s*\)\s*=\s*"
        r"cite\s*\(\s*key\s*,\s*supplement:\s*body\s*,\s*"
        r"style:\s*title-link-style\s*,?\s*\)\s*$",
        main_text,
    )
    if len(reference_title_helpers) != 1:
        errors.append("main.typ must define the canonical reference-title helper")

    keys = [entry.citation_key for entry in entries]
    for key in keys:
        if not KEY_RE.fullmatch(key):
            errors.append(
                f"citation key does not follow firstauthorYYYYshorttitle: {key}"
            )

    dois: list[str] = []
    isbns: list[str] = []
    identifiers: dict[str, list[str]] = {name: [] for name in IDENTIFIER_FIELDS}
    identity_keys: dict[str, list[str]] = defaultdict(list)
    distinct_from: dict[str, set[str]] = {}
    local_paths: list[str] = []
    entry_by_key = {entry.citation_key: entry for entry in entries}
    pending = 0

    for entry in entries:
        key = entry.citation_key
        fields = entry.fields
        title = fields.get("title", "").strip()
        if not title:
            errors.append(f"entry {key} has no title")
        else:
            identity = record_identity(entry.entry_type, fields)
            if not identity:
                errors.append(f"entry {key} has an empty normalized title")
            identity_keys[identity].append(key)
        if (
            not fields.get("author", "").strip()
            and not fields.get("editor", "").strip()
        ):
            errors.append(f"entry {key} requires author or editor")
        date = fields.get("date", "").strip()
        year = fields.get("year", "").strip()
        if not date and not year:
            errors.append(f"entry {key} requires date or year")
        if date and not is_canonical_date(date):
            errors.append(f"entry {key} has a non-canonical date: {date}")
        if year and not is_canonical_date(year, year_only=True):
            errors.append(f"entry {key} has a non-canonical year: {year}")
        if date and year and date[:4] != year:
            errors.append(f"entry {key} has conflicting date and year fields")

        doi = fields.get("doi", "").strip()
        if doi:
            normalized = normalize_doi(doi)
            if not is_canonical_doi(doi):
                errors.append(f"entry {key} has a non-canonical DOI: {doi}")
            dois.append(normalized.casefold())

        isbn = fields.get("isbn", "").strip()
        if isbn:
            if not is_valid_isbn(isbn):
                errors.append(f"entry {key} has an invalid ISBN: {isbn}")
            else:
                isbns.append(normalize_isbn(isbn))

        for name in IDENTIFIER_FIELDS:
            identifier = fields.get(name, "").strip()
            if not identifier:
                continue
            if not is_canonical_identifier(name, identifier):
                errors.append(
                    f"entry {key} has a non-canonical {name} identifier: {identifier}"
                )
            identifiers[name].append(normalize_identifier(name, identifier))

        url = fields.get("url", "").strip()
        if is_audiovisual(entry.entry_type) and url and not is_safe_web_url(url):
            errors.append(f"entry {key} has an unsafe or non-HTTP(S) url")

        distinct_value = fields.get(DISTINCT_FROM_FIELD)
        if distinct_value is not None:
            listed = key_list(distinct_value)
            if not listed:
                errors.append(f"entry {key} has an empty {DISTINCT_FROM_FIELD} field")
            if len(set(listed)) != len(listed):
                errors.append(f"entry {key} repeats a {DISTINCT_FROM_FIELD} key")
            for other in listed:
                if other == key:
                    errors.append(f"entry {key} lists itself in {DISTINCT_FROM_FIELD}")
                elif other not in entry_by_key:
                    errors.append(
                        f"entry {key} lists an unknown {DISTINCT_FROM_FIELD} key: "
                        f"{other}"
                    )
            distinct_from[key] = set(listed)

        topic = entry.topic
        if not topic:
            errors.append(f"entry {key} has no % Topic marker")
            topic = ()
        elif any(not TOPIC_RE.fullmatch(component) for component in topic):
            errors.append(f"entry {key} has a non-canonical % Topic marker")

        keywords_value = fields.get("keywords")
        if keywords_value is None:
            errors.append(f"entry {key} has no keywords field")
            keywords: tuple[str, ...] = ()
        else:
            keywords = tuple(
                component.strip()
                for component in keywords_value.split(",")
                if component.strip()
            )
            if not keywords or any(not TOPIC_RE.fullmatch(part) for part in keywords):
                errors.append(f"entry {key} has non-canonical topic keywords")
            if "Library" in keywords:
                errors.append(f"entry {key} includes physical Library in its keywords")
        if topic and keywords != topic:
            errors.append(f"entry {key} topic marker and keywords differ")

        file_value = fields.get("file")
        if file_value is None:
            errors.append(f"entry {key} has no file field")
            continue
        file_value = file_value.strip()
        if not file_value:
            pending += 1
            continue
        local_paths.append(file_value)
        path_parts = Path(file_value).parts
        if not file_value.startswith(f"{LIBRARY_DIRECTORY}/"):
            errors.append(f"library file path must be under Library/: {file_value}")
        if any(ord(character) > 127 for character in file_value):
            errors.append(f"library file path is not ASCII: {file_value}")
        if not path_parts or not NAME_RE.fullmatch(path_parts[-1]):
            errors.append(f"library filename is not canonical PascalCase: {file_value}")
        path_topic = (
            tuple(path_parts[1:-1]) if path_parts[:1] == (LIBRARY_DIRECTORY,) else ()
        )
        if any(not TOPIC_RE.fullmatch(part) for part in path_topic):
            errors.append(f"library path contains a non-canonical topic: {file_value}")
        if keywords and path_topic != keywords:
            errors.append(f"entry {key} file path and keywords differ")

    for duplicate in _duplicates(dois):
        errors.append(f"duplicate DOI: {duplicate}")
    for duplicate in _duplicates(isbns):
        errors.append(f"duplicate ISBN: {duplicate}")
    for name, values in identifiers.items():
        for duplicate in _duplicates(values):
            errors.append(f"duplicate {name} identifier: {duplicate}")
    # A shared identity is allowed only when every pair is asserted distinct.
    for identity, group in sorted(identity_keys.items()):
        if not identity or len(group) < 2:
            continue
        if any(
            second not in distinct_from.get(first, set())
            and first not in distinct_from.get(second, set())
            for first, second in combinations(group, 2)
        ):
            errors.append(
                f"duplicate normalized title: {identity} ({', '.join(group)})"
            )
    for duplicate in _duplicates(local_paths):
        errors.append(f"multiple entries reference the same library file: {duplicate}")

    catalog_keys = [item.citation_key for item in catalog_items]
    catalog_paths = [item.path for item in catalog_items if item.path is not None]
    for duplicate in _duplicates(catalog_keys):
        errors.append(f"catalog contains citation key more than once: {duplicate}")
    for duplicate in _duplicates(catalog_paths):
        errors.append(
            f"catalog links the same library file more than once: {duplicate}"
        )

    outside_items = list(catalog_source(main_text))
    for item in catalog_items:
        outside_items[item.start : item.end] = " " * (item.end - item.start)
    if CITATION_RE.search("".join(outside_items)):
        errors.append("catalog has citations outside parseable catalog items")
    if Counter(keys) != Counter(catalog_keys):
        errors.append("BibTeX entries and catalog citation keys differ")
        missing_keys = Counter(keys) - Counter(catalog_keys)
        extra_keys = Counter(catalog_keys) - Counter(keys)
        for key in sorted(missing_keys.elements()):
            errors.append(f"BibTeX key is missing from catalog: {key}")
        for key in sorted(extra_keys.elements()):
            errors.append(f"catalog cites an unknown BibTeX key: {key}")

    items_by_key: dict[str, list] = defaultdict(list)
    for item in catalog_items:
        items_by_key[item.citation_key].append(item)
    for key, entry in entry_by_key.items():
        matching = items_by_key.get(key, [])
        if len(matching) != 1:
            continue
        item = matching[0]
        if title_identity(item.title) != title_identity(catalog_title(entry.fields)):
            errors.append(f"catalog and BibTeX titles differ for {key}")
        keywords = tuple(
            part.strip()
            for part in entry.fields.get("keywords", "").split(",")
            if part.strip()
        )
        heading_path = tuple(
            heading_component(heading).casefold() for heading in item.headings
        )
        if heading_path != tuple(keyword.casefold() for keyword in keywords):
            errors.append(f"catalog headings and BibTeX keywords differ for {key}")
        file_value = entry.fields.get("file", "").strip()
        if item.reference_title_key is None:
            errors.append(
                f"catalog entry {key} must link its title to its bibliography entry"
            )
        elif item.reference_title_key != key:
            errors.append(
                f"catalog entry {key} links its title to bibliography entry "
                f"{item.reference_title_key}"
            )
        if file_value and item.path != file_value:
            errors.append(f"catalog link and BibTeX file differ for {key}")
        if file_value:
            expected_format = Path(file_value).suffix.removeprefix(".").upper()
            if item.attachment_format != expected_format:
                errors.append(
                    f"local entry {key} must show a [{expected_format}] attachment link"
                )
        if not file_value and item.path is not None:
            errors.append(f"pending entry {key} must not link to a local file")
        if not file_value and item.attachment_format is not None:
            errors.append(f"pending entry {key} must not show a local attachment link")
        url_value = entry.fields.get("url", "").strip()
        if not is_audiovisual(entry.entry_type):
            if item.url is not None or item.url_label:
                errors.append(f"only audio and video entries show a [URL] link: {key}")
        elif url_value:
            if item.url != url_value:
                errors.append(f"catalog URL link and BibTeX url differ for {key}")
            if not item.url_label:
                errors.append(f"audiovisual entry {key} must show a [URL] link")
        elif item.url is not None or item.url_label:
            errors.append(f"audiovisual entry {key} shows a [URL] link without a url")

    return SourceCheck(tuple(entries), tuple(local_paths), pending, tuple(errors), True)


def validate_library(root: Path, *, compile_catalog: bool = True) -> ValidationResult:
    root = root.expanduser().resolve()
    errors: list[str] = []
    bib_path = root / "library.bib"
    main_path = root / "main.typ"
    title_link_style_path = root / "styles/title-link.csl"
    if not bib_path.is_file():
        errors.append("missing bibliography: library.bib")
    if not main_path.is_file():
        errors.append("missing catalog source: main.typ")
    if not title_link_style_path.is_file():
        errors.append("missing catalog title-link style: styles/title-link.csl")
    if errors:
        return ValidationResult(0, 0, 0, tuple(errors))

    try:
        bib_text = bib_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return ValidationResult(0, 0, 0, (f"cannot parse library.bib: {error}",))
    try:
        main_text = main_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return ValidationResult(0, 0, 0, (f"cannot read main.typ: {error}",))

    sources = check_sources(bib_text, main_text)
    errors.extend(sources.errors)
    if not sources.complete:
        return ValidationResult(len(sources.entries), 0, 0, tuple(errors))

    for file_value in sources.local_paths:
        candidate, path_error = _safe_local_path(root, file_value)
        if path_error:
            errors.append(path_error)
            continue
        assert candidate is not None
        if not candidate.is_file():
            errors.append(
                f"BibTeX file field points to a missing library file: {file_value}"
            )
            continue
        try:
            validate_media(candidate)
        except MediaError as error:
            errors.append(f"invalid library media {file_value}: {error}")

    disk_paths, disk_errors = _disk_media(root)
    errors.extend(disk_errors)
    # Paths outside Library/ are already reported by the text checks.
    bib_paths = [
        value
        for value in sources.local_paths
        if value.startswith(f"{LIBRARY_DIRECTORY}/")
    ]
    if Counter(disk_paths) != Counter(bib_paths):
        errors.append("library files on disk and BibTeX file fields differ")
        missing_paths = Counter(bib_paths) - Counter(disk_paths)
        orphan_paths = Counter(disk_paths) - Counter(bib_paths)
        for value in sorted(missing_paths.elements()):
            errors.append(f"BibTeX library file is absent from disk: {value}")
        for value in sorted(orphan_paths.elements()):
            errors.append(f"uncataloged library file on disk: {value}")
    hashes: dict[str, list[str]] = defaultdict(list)
    for value in disk_paths:
        candidate, path_error = _safe_local_path(root, value)
        if path_error or candidate is None:
            continue
        try:
            hashes[sha256(candidate)].append(value)
        except OSError as error:
            errors.append(f"cannot hash library file {value}: {error}")
    for paths in hashes.values():
        if len(paths) > 1:
            errors.append(
                "duplicate library-file content detected: " + ", ".join(paths)
            )

    if compile_catalog:
        typst = shutil.which("typst")
        if not typst:
            errors.append("required command not found: typst")
        else:
            with tempfile.TemporaryDirectory(
                prefix="paper-library-validation-"
            ) as temporary_directory:
                output = Path(temporary_directory) / "Catalog.pdf"
                compilation = subprocess.run(
                    [typst, "compile", str(main_path), str(output)],
                    cwd=root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if compilation.returncode != 0:
                    detail = compilation.stderr.strip().splitlines()
                    suffix = f": {detail[-1]}" if detail else ""
                    errors.append(f"Typst compilation failed{suffix}")

    return ValidationResult(
        len(sources.entries), len(sources.local_paths), sources.pending, tuple(errors)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a private paper library")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--no-compile", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_library(args.root, compile_catalog=not args.no_compile)
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if result.errors:
        print(f"Validation failed with {len(result.errors)} error(s).", file=sys.stderr)
        return 1
    checks = (
        "catalog semantics, canonical names, unique keys/DOIs/ISBNs/identifiers/"
        "content, media formats"
    )
    if not args.no_compile:
        checks += ", and Typst compilation"
    print(
        "OK: validated "
        f"{result.entries} bibliography entries, {result.files} library files, "
        f"{result.pending} pending downloads, {checks}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
