"""Parse the constrained Typst catalog structure used by this repository."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re


HEADING_RE = re.compile(r"^(=+)\s+(.+?)\s*$")
CITATION_RE = re.compile(r"(?<![A-Za-z0-9_-])@([A-Za-z0-9_-]+)")
TRAILING_CITATION_RE = re.compile(r"@([A-Za-z0-9_-]+)\s*$")
LINK_RE = re.compile(r'#link\s*\(\s*("(?:\\.|[^"\\])*")', re.DOTALL)
TEXT_RE = re.compile(r'#text\s*\(\s*("(?:\\.|[^"\\])*")\s*\)', re.DOTALL)


class CatalogError(RuntimeError):
    """The catalog cannot be interpreted without ambiguity."""


@dataclass(frozen=True)
class CatalogItem:
    citation_key: str
    title: str
    path: str | None
    headings: tuple[str, ...]
    start: int
    end: int


def heading_component(heading: str) -> str:
    return "".join(character for character in heading if character.isalnum())


def _decode_string(literal: str, context: str) -> str:
    try:
        value = json.loads(literal)
    except json.JSONDecodeError as error:
        raise CatalogError(f"invalid Typst string in {context}: {error}") from error
    if not isinstance(value, str):
        raise CatalogError(f"non-text Typst string in {context}")
    return value


def _raw_link_title(block: str, citation_key: str) -> str | None:
    body = re.search(
        rf"\)\s*\[(.*?)\]\s*@{re.escape(citation_key)}(?:\s|$)",
        block,
        flags=re.DOTALL,
    )
    if not body:
        return None
    value = " ".join(line.strip() for line in body.group(1).splitlines()).strip()
    return value or None


def _plain_title(block: str, citation_key: str) -> str:
    prefix = block[: block.rfind(f"@{citation_key}")]
    prefix = re.sub(r"^-\s*", "", prefix.strip())
    return " ".join(prefix.split())


def parse_catalog(text: str) -> list[CatalogItem]:
    bibliography = re.search(r"(?m)^#bibliography\s*\(", text)
    if not bibliography:
        raise CatalogError("main.typ has no #bibliography block")
    source = text[: bibliography.start()]
    lines = source.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)

    headings: list[str] = []
    items: list[CatalogItem] = []
    line_index = 0
    while line_index < len(lines):
        stripped = lines[line_index].strip()
        heading = HEADING_RE.fullmatch(stripped)
        if heading:
            level = len(heading.group(1))
            headings[level - 1 :] = [heading.group(2)]
            line_index += 1
            continue
        if not lines[line_index].startswith("- "):
            line_index += 1
            continue

        start_line = line_index
        line_index += 1
        while line_index < len(lines):
            candidate = lines[line_index]
            if candidate.startswith("- ") or HEADING_RE.fullmatch(candidate.strip()):
                break
            line_index += 1
        start = offsets[start_line]
        end = offsets[line_index] if line_index < len(lines) else len(source)
        block = source[start:end].rstrip()
        citations = TRAILING_CITATION_RE.findall(block)
        if len(citations) != 1:
            raise CatalogError(
                f"catalog item near line {start_line + 1} must contain exactly one citation"
            )
        citation_key = citations[0]

        link = LINK_RE.search(block)
        path = _decode_string(link.group(1), citation_key) if link else None
        title_match = TEXT_RE.search(block)
        if title_match:
            title = _decode_string(title_match.group(1), citation_key)
        elif link:
            title = _raw_link_title(block, citation_key) or ""
        else:
            title = _plain_title(block, citation_key)
        if not title:
            raise CatalogError(f"catalog item {citation_key} has no readable title")
        items.append(
            CatalogItem(
                citation_key=citation_key,
                title=title,
                path=path,
                headings=tuple(headings),
                start=start,
                end=end,
            )
        )
    return items
