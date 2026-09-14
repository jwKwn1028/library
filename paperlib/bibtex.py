"""Small, strict BibLaTeX parser for the library's normalized records."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
import re
from typing import Iterable


ENTRY_HEADER_RE = re.compile(r"@([A-Za-z]+)\s*\{")
FIELD_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
KEY_RE = re.compile(r"[^,\s{}]+")
TOPIC_MARKER_RE = re.compile(r"(?m)^% Topic:\s*(.+?)\s*$")
DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


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
