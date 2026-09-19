"""Small, strict BibLaTeX parser for the library's normalized records."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
import re
from typing import Iterable, Mapping
from urllib.parse import urlsplit


ENTRY_HEADER_RE = re.compile(r"@([A-Za-z]+)\s*\{")
FIELD_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
KEY_RE = re.compile(r"[^,\s{}]+")
TOPIC_MARKER_RE = re.compile(r"(?m)^% Topic:\s*(.+?)\s*$")
DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
ISBN_PREFIX_RE = re.compile(r"^ISBN(?:-1[03])?\s*:?\s*", re.IGNORECASE)
ISBN_SEPARATOR_RE = re.compile(r"[\s\-\u2010\u2011\u2012\u2013\u2014\u2212]")
NAME_SEPARATOR_RE = re.compile(r"\s+and\s+")
# Albums use @audio or @music; films use @movie or @video.
AUDIO_ENTRY_TYPES = frozenset({"audio", "music"})
VIDEO_ENTRY_TYPES = frozenset({"movie", "video"})
AUDIOVISUAL_ENTRY_TYPES = AUDIO_ENTRY_TYPES | VIDEO_ENTRY_TYPES
# BibLaTeX types for whole books, their parts, and edited or reference volumes.
BOOK_ENTRY_TYPES = frozenset(
    {
        "book",
        "bookinbook",
        "booklet",
        "collection",
        "inbook",
        "incollection",
        "inreference",
        "manual",
        "mvbook",
        "mvcollection",
        "mvproceedings",
        "mvreference",
        "proceedings",
        "reference",
        "suppbook",
        "suppcollection",
    }
)
# Kinds of record, from most to least common in a research library.
RECORD_KINDS = ("paper", "book", "music", "film")
IDENTIFIER_FIELDS = ("imdb", "musicbrainz", "wikidata")
# Citation keys of records verified as distinct works despite a shared identity.
DISTINCT_FROM_FIELD = "distinctfrom"
IDENTIFIER_PATTERNS = {
    "imdb": re.compile(r"^tt[0-9]{7,10}$"),
    "musicbrainz": re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
    "wikidata": re.compile(r"^Q[1-9][0-9]*$"),
}
IDENTIFIER_URL_PREFIXES = {
    "imdb": re.compile(r"^https?://(?:(?:www|m)\.)?imdb\.com/title/", re.IGNORECASE),
    "musicbrainz": re.compile(
        r"^https?://(?:beta\.)?musicbrainz\.org/(?:release-group|recording)/",
        re.IGNORECASE,
    ),
    "wikidata": re.compile(
        r"^https?://(?:(?:www|m)\.)?wikidata\.org/(?:wiki|entity)/", re.IGNORECASE
    ),
}


class BibtexError(RuntimeError):
    """A bibliography cannot be interpreted without ambiguity."""


@dataclass(frozen=True)
class BibField:
    name: str
    value: str
    value_start: int
    value_end: int


@dataclass(frozen=True)
class BibEntry:
    entry_type: str
    citation_key: str
    fields: dict[str, str]
    field_spans: dict[str, BibField]
    topic: tuple[str, ...] | None
    start: int
    end: int

    def field(self, name: str) -> BibField | None:
        return self.field_spans.get(name.casefold())


def skip_space_and_comments(text: str, index: int, limit: int | None = None) -> int:
    end = len(text) if limit is None else limit
    while index < end:
        if text[index].isspace():
            index += 1
            continue
        if text[index] == "%":
            newline = text.find("\n", index, end)
            if newline < 0:
                return end
            index = newline + 1
            continue
        return index
    return index


def find_closing_brace(
    text: str, opening_index: int, context: str, limit: int | None = None
) -> int:
    depth = 1
    escaped = False
    end = len(text) if limit is None else limit
    for index in range(opening_index + 1, end):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
    raise BibtexError(f"unclosed brace in {context}")


def _quoted_value_end(text: str, start: int, limit: int, context: str) -> int:
    escaped = False
    for index in range(start, limit):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return index
    raise BibtexError(f"unclosed quoted field {context}")


def _parse_fields(
    text: str, start: int, end: int, citation_key: str
) -> tuple[dict[str, str], dict[str, BibField]]:
    fields: dict[str, str] = {}
    spans: dict[str, BibField] = {}
    index = start
    while True:
        index = skip_space_and_comments(text, index, end)
        while index < end and text[index] == ",":
            index = skip_space_and_comments(text, index + 1, end)
        if index >= end:
            return fields, spans

        name_match = FIELD_NAME_RE.match(text, index, end)
        if not name_match:
            snippet = text[index : min(index + 24, end)]
            raise BibtexError(f"cannot parse field in {citation_key} near {snippet!r}")
        name = name_match.group(0).casefold()
        index = skip_space_and_comments(text, name_match.end(), end)
        if index >= end or text[index] != "=":
            raise BibtexError(f"field {name} in {citation_key} has no equals sign")
        index = skip_space_and_comments(text, index + 1, end)
        if index >= end:
            raise BibtexError(f"field {name} in {citation_key} has no value")

        if text[index] == "{":
            closing = find_closing_brace(
                text, index, f"field {name} in {citation_key}", end
            )
            value_start = index + 1
            value_end = closing
            index = closing + 1
        elif text[index] == '"':
            value_start = index + 1
            value_end = _quoted_value_end(
                text, value_start, end, f"{name} in {citation_key}"
            )
            index = value_end + 1
        else:
            value_start = index
            while index < end and text[index] != ",":
                index += 1
            value_end = index
            while value_start < value_end and text[value_start].isspace():
                value_start += 1
            while value_end > value_start and text[value_end - 1].isspace():
                value_end -= 1

        value = text[value_start:value_end].strip()
        if name in fields:
            raise BibtexError(f"duplicate field {name} in {citation_key}")
        fields[name] = value
        spans[name] = BibField(name, value, value_start, value_end)


def _topic_before(
    markers: list[tuple[int, tuple[str, ...]]], position: int
) -> tuple[str, ...] | None:
    topic: tuple[str, ...] | None = None
    for marker_position, marker_topic in markers:
        if marker_position > position:
            break
        topic = marker_topic
    return topic


def parse_bibliography(text: str, *, require_entries: bool = True) -> list[BibEntry]:
    """Parse normalized BibLaTeX, retaining exact field-value spans for updates."""

    markers: list[tuple[int, tuple[str, ...]]] = []
    for marker in TOPIC_MARKER_RE.finditer(text):
        topic = tuple(
            part.strip() for part in marker.group(1).split("/") if part.strip()
        )
        markers.append((marker.start(), topic))

    entries: list[BibEntry] = []
    citation_keys: set[str] = set()
    index = 0
    while True:
        index = skip_space_and_comments(text, index)
        if index >= len(text):
            break
        header = ENTRY_HEADER_RE.match(text, index)
        if not header:
            line = text.count("\n", 0, index) + 1
            raise BibtexError(f"unexpected bibliography content at line {line}")

        entry_type = header.group(1).casefold()
        if entry_type in {"comment", "preamble", "string"}:
            raise BibtexError(f"unsupported BibTeX directive: @{entry_type}")
        opening = header.end() - 1
        closing = find_closing_brace(text, opening, f"@{entry_type} entry")
        content_start = opening + 1
        comma = text.find(",", content_start, closing)
        if comma < 0:
            raise BibtexError(f"@{entry_type} entry has no citation-key separator")
        citation_key = text[content_start:comma].strip()
        if not KEY_RE.fullmatch(citation_key):
            raise BibtexError(f"invalid citation key: {citation_key!r}")
        if citation_key in citation_keys:
            raise BibtexError(f"duplicate citation key: {citation_key}")
        citation_keys.add(citation_key)

        fields, spans = _parse_fields(text, comma + 1, closing, citation_key)
        entries.append(
            BibEntry(
                entry_type=entry_type,
                citation_key=citation_key,
                fields=fields,
                field_spans=spans,
                topic=_topic_before(markers, index),
                start=index,
                end=closing + 1,
            )
        )
        index = closing + 1

    if require_entries and not entries:
        raise BibtexError("library.bib contains no bibliography entries")
    return entries


def replace_field_values(
    text: str, replacements: Iterable[tuple[BibField, str]]
) -> str:
    """Replace parsed field contents without reformatting unrelated records."""

    result = text
    ordered = sorted(replacements, key=lambda item: item[0].value_start, reverse=True)
    last_start = len(text) + 1
    for field, value in ordered:
        if field.value_end > last_start:
            raise BibtexError("overlapping bibliography replacements")
        result = result[: field.value_start] + value + result[field.value_end :]
        last_start = field.value_start
    return result


def normalize_doi(value: str) -> str:
    doi = value.strip()
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.rstrip(". ")


def is_canonical_doi(value: str) -> bool:
    return normalize_doi(value) == value and DOI_RE.fullmatch(value) is not None


def is_audiovisual(entry_type: str) -> bool:
    """Return whether an entry type records an album or a film."""

    return entry_type.casefold() in AUDIOVISUAL_ENTRY_TYPES


def record_kind(entry_type: str) -> str:
    """Return whether an entry type is a paper, book, music, or film record.

    Every document that is not book-like counts as a paper, including articles,
    conference papers, reports, theses, and online preprints.
    """

    folded = entry_type.casefold()
    if folded in AUDIO_ENTRY_TYPES:
        return "music"
    if folded in VIDEO_ENTRY_TYPES:
        return "film"
    if folded in BOOK_ENTRY_TYPES:
        return "book"
    return "paper"


def normalize_identifier(name: str, value: str) -> str:
    """Reduce an IMDb, MusicBrainz, or Wikidata value or page URL to its ID."""

    identifier = IDENTIFIER_URL_PREFIXES[name].sub("", value.strip())
    identifier = re.split(r"[/?#]", identifier, maxsplit=1)[0]
    return identifier.upper() if name == "wikidata" else identifier.casefold()


def is_canonical_identifier(name: str, value: str) -> bool:
    return IDENTIFIER_PATTERNS[name].fullmatch(value) is not None


def is_safe_web_url(value: str) -> bool:
    """Return whether *value* is an absolute, credential-free HTTP(S) URL."""

    if not value or not value.isprintable() or " " in value:
        return False
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        credentials = (parts.username, parts.password)
    except ValueError:
        return False
    return (
        parts.scheme.casefold() in {"http", "https"}
        and bool(hostname)
        and credentials == (None, None)
    )


def _compact_isbn(value: str) -> str:
    isbn = ISBN_PREFIX_RE.sub("", value.strip())
    return ISBN_SEPARATOR_RE.sub("", isbn).upper()


def is_valid_isbn(value: str) -> bool:
    """Return whether *value* has a valid ISBN-10 or ISBN-13 checksum."""

    isbn = _compact_isbn(value)
    if (
        len(isbn) == 10
        and isbn[:9].isdigit()
        and (isbn[-1].isdigit() or isbn[-1] == "X")
    ):
        digits = [int(character) for character in isbn[:9]]
        digits.append(10 if isbn[-1] == "X" else int(isbn[-1]))
        return (
            sum(weight * digit for weight, digit in zip(range(10, 0, -1), digits)) % 11
            == 0
        )
    if len(isbn) == 13 and isbn.isdigit():
        checksum = sum(
            int(character) * (1 if index % 2 == 0 else 3)
            for index, character in enumerate(isbn)
        )
        return checksum % 10 == 0
    return False


def normalize_isbn(value: str) -> str:
    """Normalize a valid ISBN to an unseparated ISBN-13 identity.

    Invalid input is compacted but otherwise returned unchanged so callers can
    report the original record as invalid before using the result as identity.
    """

    isbn = _compact_isbn(value)
    if not is_valid_isbn(isbn) or len(isbn) == 13:
        return isbn
    stem = f"978{isbn[:9]}"
    weighted_sum = sum(
        int(character) * (1 if index % 2 == 0 else 3)
        for index, character in enumerate(stem)
    )
    return f"{stem}{(-weighted_sum) % 10}"


def is_canonical_date(value: str, *, year_only: bool = False) -> bool:
    match = DATE_RE.fullmatch(value)
    if not match:
        return False
    year, month, day = match.groups()
    if not 1 <= int(year) <= 9999:
        return False
    if year_only:
        return month is None
    if month is None:
        return True
    month_number = int(month)
    if not 1 <= month_number <= 12:
        return False
    if day is None:
        return True
    day_number = int(day)
    if day_number < 1:
        return False
    return day_number <= calendar.monthrange(int(year), month_number)[1]


def plain_text(value: str, *, typography: bool = True) -> str:
    """Remove grouping braces and common BibTeX escapes for display comparison."""

    escaped_characters = {
        "#": "#",
        "$": "$",
        "%": "%",
        "&": "&",
        "_": "_",
        "{": "{",
        "}": "}",
        "~": "~",
        "\\": "\\",
    }
    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            replacement = escaped_characters.get(value[index + 1])
            if replacement is not None:
                result.append(replacement)
                index += 2
                continue
        if character not in "{}":
            result.append(" " if character == "~" and typography else character)
        index += 1
    normalized = " ".join("".join(result).split())
    if typography:
        normalized = normalized.replace("---", "—").replace("--", "–")
    return normalized


def title_identity(value: str) -> str:
    return "".join(
        character for character in plain_text(value).casefold() if character.isalnum()
    )


def split_names(value: str) -> list[str]:
    """Split a BibTeX name list on ``and`` separators outside braces."""

    pieces: list[str] = []
    start = 0
    depth = 0
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            conjunction = NAME_SEPARATOR_RE.match(value, index)
            if conjunction:
                pieces.append(value[start:index])
                index = conjunction.end()
                start = index
                continue
        index += 1
    pieces.append(value[start:])
    return pieces


def record_identity(entry_type: str, fields: Mapping[str, str]) -> str:
    """Return the normalized identity used to reject duplicate records.

    Albums and films often reuse the title of a book, an earlier release, or a
    remake, so an audiovisual identity also includes its medium, release year,
    and first credited creator.
    """

    identity = title_identity(catalog_title(fields))
    if not identity or not is_audiovisual(entry_type):
        return identity
    medium = "audio" if entry_type.casefold() in AUDIO_ENTRY_TYPES else "video"
    year = (fields.get("date") or fields.get("year") or "").strip()[:4]
    creator = split_names(fields.get("author") or fields.get("editor") or "")[0]
    return f"{identity}|{medium}|{year}|{title_identity(creator)}"


def key_list(value: str) -> list[str]:
    """Split a comma-separated citation-key field such as ``distinctfrom``."""

    return [key.strip() for key in value.split(",") if key.strip()]


def work_title(fields: Mapping[str, str]) -> str:
    """Return the plain-text ``title: subtitle`` of the work itself."""

    title = plain_text(fields.get("title", ""))
    subtitle = plain_text(fields.get("subtitle", ""))
    return f"{title}: {subtitle}" if subtitle else title


def catalog_title(fields: Mapping[str, str]) -> str:
    """Return the plain-text title shown in the catalog topic list."""

    title = work_title(fields)
    series = plain_text(fields.get("series", ""))
    number = plain_text(fields.get("number", ""))
    return f"{series} #{number}: {title}" if series and number else title
