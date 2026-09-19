#!/usr/bin/env python3
"""Look up album or film metadata and draft a pending intake manifest item.

This helper reads public MusicBrainz and Wikidata records and, when present,
the private library.bib for duplicate hints. It never writes files or changes
canonical library state; every draft still needs review and the offline
transactional intake engine.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from string import ascii_lowercase
import sys
import time
import unicodedata
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from paperlib.bibtex import (  # noqa: E402
    IDENTIFIER_FIELDS,
    BibtexError,
    is_canonical_date,
    is_canonical_identifier,
    is_safe_web_url,
    normalize_identifier,
    parse_bibliography,
    record_identity,
    split_names,
)


MUSICBRAINZ_API = "https://musicbrainz.org/ws/2/"
MUSICBRAINZ_PAGE = "https://musicbrainz.org/"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_PAGE = "https://www.wikidata.org/wiki/"
IMDB_PAGE = "https://www.imdb.com/title/"
USER_AGENT = "paper-library-lookup/1.0"
CONTACT_ENV = "PAPER_LIBRARY_LOOKUP_CONTACT"
JSON_MAX_BYTES = 8 * 1024 * 1024
# MusicBrainz allows one request per second; Wikidata asks for serial requests.
MINIMUM_INTERVALS = {"musicbrainz.org": 1.1}
RETRY_PAUSES = (2.0, 5.0)
WIKIDATA_BATCH = 10
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
FILM_CLASSES = (
    "Q11424",  # film
    "Q24869",  # feature film
    "Q202866",  # animated film
    "Q93204",  # documentary film
    "Q24862",  # short film
    "Q506240",  # television film
    "Q29168811",  # animated feature film
)
MUSICBRAINZ_STREAMING_RELATIONS = {"free streaming", "streaming"}
# Preferred album link hosts; subdomains such as artist.bandcamp.com also match.
STREAMING_HOSTS = (
    "open.spotify.com",
    "music.apple.com",
    "music.youtube.com",
    "youtube.com",
    "bandcamp.com",
    "tidal.com",
    "deezer.com",
    "qobuz.com",
)
# Wikidata identifiers that name a public place to watch a film. YouTube IDs are
# often trailers, so they count only when their duration covers the film.
YOUTUBE_PROPERTY = "P1651"
FILM_STREAMING_PROPERTIES = (
    (YOUTUBE_PROPERTY, "https://www.youtube.com/watch?v={}"),
    ("P724", "https://archive.org/details/{}"),
    ("P1874", "https://www.netflix.com/title/{}"),
)
DURATION_UNITS = {"Q7727": 1.0, "Q11574": 1 / 60, "Q25235": 60.0}
FULL_LENGTH_FRACTION = 0.9
FULL_LENGTH_MINUTES = 40.0
KEY_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
QID_RE = re.compile(r"^Q[1-9][0-9]*$")
WIKIDATA_TIME_RE = re.compile(r"^\+?(\d{4})-(\d{2})-(\d{2})T")
EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class MediaLookupError(RuntimeError):
    """A metadata request failed or returned data that cannot be drafted."""


@dataclass(frozen=True)
class Link:
    kind: str
    url: str


@dataclass(frozen=True)
class Draft:
    item: dict[str, Any]
    links: tuple[Link, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class LibraryIndex:
    keys: frozenset[str]
    identifiers: dict[tuple[str, str], str]
    records: dict[str, str]


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("query", nargs="?", help="title to search for")
    common.add_argument(
        "--id", dest="identifier", help="draft one record by identifier or page URL"
    )
    common.add_argument("--year", help="keep candidates released in this year")
    common.add_argument("--limit", type=int, default=5, help="search results")
    common.add_argument(
        "--link",
        choices=("streaming", "reference"),
        default="streaming",
        help="catalog url to prefer in a draft (default: streaming when found)",
    )
    common.add_argument("--json", action="store_true", help="emit JSON")
    common.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS")
    common.add_argument("--root", type=Path, default=Path.cwd(), help="library root")

    parser = argparse.ArgumentParser(
        description=(
            "Search MusicBrainz albums or Wikidata films, or draft one pending "
            "intake manifest item for review. Nothing is written."
        )
    )
    subparsers = parser.add_subparsers(dest="kind", required=True)
    music = subparsers.add_parser(
        "music",
        parents=[common],
        help="albums from MusicBrainz release groups",
        description="Search or draft an album from a MusicBrainz release group.",
    )
    music.add_argument("--artist", help="restrict the search to this artist credit")
    film = subparsers.add_parser(
        "film",
        parents=[common],
        help="films from Wikidata",
        description="Search or draft a film from its Wikidata item.",
    )
    film.add_argument("--director", help="keep candidates with this director")
    film.add_argument(
        "--language",
        default="en",
        help="title language code, or 'original' for the original title (default: en)",
    )
    args = parser.parse_args(arguments)
    if (args.query is None) == (args.identifier is None):
        parser.error("give either a search QUERY or --id, not both")
    if args.year is not None and not re.fullmatch(r"\d{4}", args.year):
        parser.error("--year must have four digits")
    if not 1 <= args.limit <= 25:
        parser.error("--limit must be between 1 and 25")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite, positive number")
    if args.kind == "film" and not re.fullmatch(
        r"original|[a-z]{2,3}(?:-[a-z0-9]+)*", args.language
    ):
        parser.error("--language must be a Wikidata language code or 'original'")
    return args


class NetworkClient:
    def __init__(
        self,
        timeout: float,
        *,
        opener: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout = timeout
        self.opener = opener
        self.sleep = sleep
        self.clock = clock
        self.last_request: dict[str, float] = {}
        # Both services ask clients to identify a contact; it is never printed.
        contact = os.environ.get(CONTACT_ENV, "").strip()
        if contact and (not contact.isprintable() or any(c in contact for c in "()")):
            raise MediaLookupError(f"{CONTACT_ENV} must be one printable line")
        self.user_agent = f"{USER_AGENT} ( {contact} )" if contact else USER_AGENT

    def pace(self, host: str) -> None:
        previous = self.last_request.get(host)
        if previous is not None:
            remaining = previous + MINIMUM_INTERVALS.get(host, 0.0) - self.clock()
            if remaining > 0:
                self.sleep(remaining)
        self.last_request[host] = self.clock()

    def json(self, url: str, source: str) -> dict[str, Any]:
        host = urlsplit(url).hostname or ""
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        for pause in (*RETRY_PAUSES, None):
            self.pace(host)
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    if not is_safe_web_url(response.geturl()):
                        raise MediaLookupError(f"{source} redirected to an unsafe URL")
                    data = response.read(JSON_MAX_BYTES + 1)
            except HTTPError as error:
                if error.code in {429, 503} and pause is not None:
                    self.sleep(pause)
                    continue
                raise MediaLookupError(
                    f"{source} returned HTTP {error.code}"
                ) from error
            except (TimeoutError, URLError) as error:
                reason = getattr(error, "reason", error)
                raise MediaLookupError(f"{source} request failed: {reason}") from error
            if len(data) > JSON_MAX_BYTES:
                raise MediaLookupError(f"{source} exceeded {JSON_MAX_BYTES} bytes")
            try:
                parsed = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise MediaLookupError(f"{source} returned invalid JSON") from error
            if not isinstance(parsed, dict):
                raise MediaLookupError(f"{source} returned a non-object response")
            if isinstance(parsed.get("error"), dict):
                code = parsed["error"].get("code", "unknown")
                raise MediaLookupError(f"{source} returned error {code}")
            return parsed
        raise MediaLookupError(f"{source} kept rate limiting requests")


def load_library_index(root: Path) -> LibraryIndex:
    bibliography = root / "library.bib"
    if not bibliography.is_file():
        return LibraryIndex(frozenset(), {}, {})
    try:
        entries = parse_bibliography(
            bibliography.read_text(encoding="utf-8"), require_entries=False
        )
    except (OSError, UnicodeError, BibtexError) as error:
        raise MediaLookupError(f"cannot parse library.bib: {error}") from error
    identifiers: dict[tuple[str, str], str] = {}
    records: dict[str, str] = {}
    for entry in entries:
        for name in IDENTIFIER_FIELDS:
            value = entry.fields.get(name, "").strip()
            if value:
                identifier = normalize_identifier(name, value)
                identifiers[(name, identifier)] = entry.citation_key
        records[record_identity(entry.entry_type, entry.fields)] = entry.citation_key
    return LibraryIndex(
        frozenset(entry.citation_key for entry in entries), identifiers, records
    )


def label_languages(language: str) -> str:
    codes = ["en", "ko", "mul"]
    if language != "original" and language not in codes:
        codes.append(language)
    return "|".join(codes)


def ascii_words(value: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return [word for word in re.split(r"[^a-z0-9]+", folded.casefold()) if word]


def family_prefix(name: str) -> str:
    """Return a letters-only family name for a citation key."""

    stripped = name.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        words = [
            word for word in ascii_words(stripped[1:-1]) if word not in KEY_STOPWORDS
        ]
    elif "," in stripped:
        words = ascii_words(stripped.split(",", 1)[0])
    else:
        words = ascii_words(stripped)[-1:]
    return re.sub(r"[^a-z]", "", "".join(words[:1]))


def suggest_key(
    author: str,
    date: str,
    title: str,
    index: LibraryIndex,
    notes: list[str],
    key_family: str = "",
) -> str:
    # A sort name such as "Metheny, Pat, Group" names a group's family better
    # than the group's first word does.
    family = re.sub(r"[^a-z]", "", "".join(ascii_words(key_family)[:1]))
    if not family and author:
        family = family_prefix(split_names(author)[0])
    if not family:
        family = "creator"
        notes.append("choose an ASCII family-name prefix for citation_key")
    year = date[:4] if re.fullmatch(r"\d{4}", date[:4]) else "0000"
    words = [word for word in ascii_words(title) if word not in KEY_STOPWORDS]
    short = "".join(words[:2]) or "".join(ascii_words(title)[:2])
    if not short:
        short = "title"
        notes.append("choose an ASCII short title for citation_key")
    base = f"{family}{year}{short}"
    if base not in index.keys:
        return base
    for suffix in ascii_lowercase:
        if f"{base}{suffix}" not in index.keys:
            notes.append(f"citation key {base} is taken; suggested {base}{suffix}")
            return f"{base}{suffix}"
    raise MediaLookupError(f"no free citation key remains for {base}")


def duplicate_notes(
    entry_type: str, title: str, fields: dict[str, str], index: LibraryIndex
) -> list[str]:
    notes = []
    for name in IDENTIFIER_FIELDS:
        value = fields.get(name)
        existing = index.identifiers.get((name, value)) if value else None
        if existing:
            notes.append(f"DUPLICATE: {name} {value} is already recorded as {existing}")
    existing = index.records.get(
        record_identity(entry_type, {**fields, "title": title})
    )
    if existing:
        notes.append(
            "DUPLICATE: the same title, release year, and first creator are "
            f"already recorded as {existing}"
        )
    return notes


def host_rank(url: str) -> int:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    for rank, preferred in enumerate(STREAMING_HOSTS):
        if host == preferred or host.endswith(f".{preferred}"):
            return rank
    return len(STREAMING_HOSTS)


def build_draft(
    *,
    entry_type: str,
    title: str,
    fields: dict[str, str],
    links: list[Link],
    link_preference: str,
    sources: list[str],
    notes: list[str],
    index: LibraryIndex,
    key_title: str = "",
    key_family: str = "",
) -> Draft:
    streaming = [link for link in links if link.kind == "streaming"]
    reference = [link for link in links if link.kind == "reference"]
    chosen = (streaming if link_preference == "streaming" else []) + reference
    if chosen:
        fields["url"] = chosen[0].url
    fields = {name: value for name, value in fields.items() if value}
    notes = [*duplicate_notes(entry_type, title, fields, index), *notes]
    if "author" not in fields:
        notes.append("no creator was found; add author before intake")
    if "date" not in fields:
        notes.append("no release date was found; add date before intake")
    elif len(fields["date"]) == 4:
        notes.append(
            "release date is year-only; add month and day when a reliable "
            "source has them"
        )
    item = {
        "pending": True,
        "citation_key": suggest_key(
            fields.get("author", ""),
            fields.get("date", ""),
            title if ascii_words(title) else key_title or title,
            index,
            notes,
            key_family,
        ),
        "entry_type": entry_type,
        "title": title,
        "metadata_sources": sources,
        "fields": fields,
    }
    return Draft(item, tuple(links), tuple(notes))


def musicbrainz_url(path: str, **parameters: str | int) -> str:
    return f"{MUSICBRAINZ_API}{path}?{urlencode({**parameters, 'fmt': 'json'})}"


def lucene_phrase(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def credit_text(credits: Any) -> str:
    if not isinstance(credits, list):
        return ""
    return "".join(
        f"{credit.get('name', '')}{credit.get('joinphrase', '')}"
        for credit in credits
        if isinstance(credit, dict)
    ).strip()


def music_authors(credits: Any, notes: list[str]) -> str:
    names: list[str] = []
    for credit in credits if isinstance(credits, list) else []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") if isinstance(credit.get("artist"), dict) else {}
        name = str(credit.get("name") or artist.get("name") or "").strip()
        sort_name = str(artist.get("sort-name") or "").strip()
        if artist.get("id") == VARIOUS_ARTISTS:
            names.append("{Various Artists}")
            notes.append("compilation credited to Various Artists")
        elif artist.get("type") == "Person" and "," in sort_name:
            names.append(sort_name)
        elif name:
            # Braces keep a group or single-word name from being split as a person.
            names.append(f"{{{name}}}")
    if len(names) > 1:
        notes.append(f"{len(names)} artists are credited; confirm their order")
    return " and ".join(names)


def search_music(
    client: NetworkClient,
    query: str,
    artist: str | None,
    year: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    terms = [f"releasegroup:{lucene_phrase(query)}"]
    if artist:
        terms.append(f"artist:{lucene_phrase(artist)}")
    data = client.json(
        musicbrainz_url(
            "release-group", query=" AND ".join(terms), limit=25 if year else limit
        ),
        "MusicBrainz search",
    )
    results = []
    for group in data.get("release-groups", []):
        if not isinstance(group, dict) or not group.get("id"):
            continue
        date = str(group.get("first-release-date") or "")
        if year and not date.startswith(year):
            continue
        types = [group.get("primary-type"), *(group.get("secondary-types") or [])]
        results.append(
            {
                "id": str(group["id"]),
                "title": str(group.get("title", "")),
                "credit": credit_text(group.get("artist-credit")),
                "date": date,
                "type": " + ".join(str(value) for value in types if value),
                "url": f"{MUSICBRAINZ_PAGE}release-group/{group['id']}",
            }
        )
    return results[:limit]


def draft_music(
    client: NetworkClient, identifier: str, link_preference: str, index: LibraryIndex
) -> Draft:
    mbid = normalize_identifier("musicbrainz", identifier)
    if not is_canonical_identifier("musicbrainz", mbid):
        raise MediaLookupError("--id must be a MusicBrainz release-group ID or URL")
    group = client.json(
        musicbrainz_url(f"release-group/{mbid}", inc="artists+url-rels"),
        "MusicBrainz release group",
    )
    releases = client.json(
        musicbrainz_url(
            "release",
            **{
                "release-group": mbid,
                "inc": "labels+url-rels",
                "status": "official",
                "limit": 100,
            },
        ),
        "MusicBrainz releases",
    )
    title = str(group.get("title") or "").strip()
    if not title:
        raise MediaLookupError("the MusicBrainz release group has no title")

    notes: list[str] = []
    credits = group.get("artist-credit") or []
    author = music_authors(credits, notes)
    first_artist = (
        credits[0].get("artist")
        if credits
        and isinstance(credits[0], dict)
        and isinstance(credits[0].get("artist"), dict)
        else {}
    )
    sort_family = str(first_artist.get("sort-name") or "").split(",", 1)[0]
    dated = sorted(
        (
            release
            for release in releases.get("releases", [])
            if isinstance(release, dict)
            and is_canonical_date(str(release.get("date") or ""))
        ),
        key=lambda release: str(release["date"]),
    )
    date = str(group.get("first-release-date") or "")
    if not is_canonical_date(date):
        date = str(dated[0]["date"]) if dated else ""

    sources = [f"{MUSICBRAINZ_PAGE}release-group/{mbid}"]
    label = ""
    for release in dated:
        names = [
            str(info["label"].get("name", "")).strip()
            for info in release.get("label-info") or []
            if isinstance(info, dict) and isinstance(info.get("label"), dict)
        ]
        names = [name for name in names if name and name != "[no label]"]
        if names:
            label = names[0]
            if is_canonical_identifier("musicbrainz", str(release.get("id", ""))):
                sources.append(f"{MUSICBRAINZ_PAGE}release/{release['id']}")
            notes.append(
                f"publisher is the label of the earliest dated official release "
                f"({release.get('date')}, {release.get('country') or 'no country'})"
            )
            break
    if not label:
        notes.append("no label was found on an official release; add publisher")

    wikidata = ""
    for relation in group.get("relations") or []:
        target = str((relation.get("url") or {}).get("resource") or "")
        if relation.get("type") == "wikidata":
            candidate = normalize_identifier("wikidata", target)
            if is_canonical_identifier("wikidata", candidate):
                wikidata = candidate

    streaming: dict[str, Link] = {}
    for release in releases.get("releases", []):
        if not isinstance(release, dict):
            continue
        for relation in release.get("relations") or []:
            target = str((relation.get("url") or {}).get("resource") or "")
            if relation.get(
                "type"
            ) in MUSICBRAINZ_STREAMING_RELATIONS and is_safe_web_url(target):
                streaming.setdefault(target, Link("streaming", target))
    links = sorted(streaming.values(), key=lambda link: host_rank(link.url))
    links.append(Link("reference", sources[0]))

    fields = {
        "author": author,
        "date": date,
        "publisher": label,
        "type": str(group.get("primary-type") or "Album"),
        "musicbrainz": mbid,
        "wikidata": wikidata,
    }
    return build_draft(
        entry_type="audio",
        title=title,
        fields=fields,
        links=links,
        link_preference=link_preference,
        sources=sources,
        notes=notes,
        index=index,
        key_family=sort_family,
    )


def wikidata_url(**parameters: str | int) -> str:
    return f"{WIKIDATA_API}?{urlencode({**parameters, 'format': 'json'})}"


def wikidata_entities(
    client: NetworkClient, ids: list[str], props: str, languages: str
) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), WIKIDATA_BATCH):
        data = client.json(
            wikidata_url(
                action="wbgetentities",
                ids="|".join(ids[start : start + WIKIDATA_BATCH]),
                props=props,
                languages=languages,
            ),
            "Wikidata",
        )
        for qid, entity in (data.get("entities") or {}).items():
            if isinstance(entity, dict) and "missing" not in entity:
                entities[qid] = entity
    return entities


def claim_statements(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    return [
        statement
        for statement in (entity.get("claims") or {}).get(prop, [])
        if isinstance(statement, dict) and statement.get("rank") != "deprecated"
    ]


def snak_value(snak: Any) -> Any:
    return ((snak.get("datavalue") or {}) if isinstance(snak, dict) else {}).get(
        "value"
    )


def claim_values(entity: dict[str, Any], prop: str) -> list[Any]:
    values = []
    for statement in claim_statements(entity, prop):
        value = snak_value(statement.get("mainsnak"))
        if value is not None:
            values.append(value)
    return values


def minutes(quantity: Any) -> float | None:
    if not isinstance(quantity, dict):
        return None
    factor = DURATION_UNITS.get(str(quantity.get("unit", "")).rsplit("/", 1)[-1])
    try:
        amount = float(quantity.get("amount", ""))
    except ValueError:
        return None
    return amount * factor if factor and math.isfinite(amount) else None


def claim_ids(entity: dict[str, Any], prop: str) -> list[str]:
    return [
        str(value["id"])
        for value in claim_values(entity, prop)
        if isinstance(value, dict) and QID_RE.fullmatch(str(value.get("id", "")))
    ]


def entity_label(entity: dict[str, Any], languages: tuple[str, ...] = ()) -> str:
    labels = entity.get("labels") or {}
    for language in (*languages, "en", "mul"):
        value = (labels.get(language) or {}).get("value")
        if value:
            return str(value)
    return ""


def release_years(entity: dict[str, Any]) -> list[str]:
    years = set()
    for value in claim_values(entity, "P577"):
        if not isinstance(value, dict):
            continue
        match = WIKIDATA_TIME_RE.match(str(value.get("time", "")))
        if match:
            years.add(match.group(1))
    return sorted(years)


def release_date(entity: dict[str, Any]) -> str:
    """Return the earliest release, at the best precision known for that year."""

    candidates: list[tuple[str, int, str]] = []
    for value in claim_values(entity, "P577"):
        if not isinstance(value, dict):
            continue
        match = WIKIDATA_TIME_RE.match(str(value.get("time", "")))
        precision = value.get("precision")
        if not match or precision not in (9, 10, 11):
            continue
        year, month, day = match.groups()
        text = {9: year, 10: f"{year}-{month}", 11: f"{year}-{month}-{day}"}[precision]
        if is_canonical_date(text):
            candidates.append((year, -precision, text))
    if not candidates:
        return ""
    earliest = min(candidate[0] for candidate in candidates)
    same_year = [candidate for candidate in candidates if candidate[0] == earliest]
    best = min(candidate[1] for candidate in same_year)
    return min(candidate[2] for candidate in same_year if candidate[1] == best)


def imdb_id(entity: dict[str, Any]) -> str:
    for value in claim_values(entity, "P345"):
        if isinstance(value, str) and is_canonical_identifier("imdb", value):
            return value
    return ""


def film_watch_links(film: dict[str, Any]) -> list[Link]:
    """Return watch pages, demoting YouTube videos too short to be the film."""

    runtimes = [value for value in map(minutes, claim_values(film, "P2047")) if value]
    threshold = (
        max(runtimes) * FULL_LENGTH_FRACTION if runtimes else FULL_LENGTH_MINUTES
    )
    links = []
    for prop, template in FILM_STREAMING_PROPERTIES:
        for statement in claim_statements(film, prop):
            value = snak_value(statement.get("mainsnak"))
            if not isinstance(value, str) or not EXTERNAL_ID_RE.fullmatch(value):
                continue
            kind = "streaming"
            if prop == YOUTUBE_PROPERTY:
                durations = [
                    minutes(snak_value(snak))
                    for snak in (statement.get("qualifiers") or {}).get("P2047", [])
                ]
                length = max(
                    (duration for duration in durations if duration), default=0
                )
                kind = "streaming" if length >= threshold else "video"
            links.append(Link(kind, template.format(value)))
    return links


def person_name(entity: dict[str, Any], family_labels: dict[str, str]) -> str:
    """Return "Family, Given" when Wikidata's family name occurs in the label."""

    full = entity_label(entity)
    for family_id in claim_ids(entity, "P734"):
        family = family_labels.get(family_id, "")
        pattern = rf"(?<![^\W_]){re.escape(family)}(?![^\W_])"
        if family and re.search(pattern, full):
            given = " ".join(re.sub(pattern, " ", full, count=1).split())
            return f"{family}, {given}" if given else family
    return f"{{{full}}}" if full else ""


def film_title(entity: dict[str, Any], language: str, notes: list[str]) -> str:
    originals = [
        value
        for value in claim_values(entity, "P1476")
        if isinstance(value, dict) and value.get("text")
    ]
    original = next(
        (value for value in originals if "-" not in str(value.get("language", ""))),
        originals[0] if originals else None,
    )
    labels = {
        code: (entity.get("labels") or {}).get(code, {}).get("value")
        for code in ("en", "ko")
    }
    variants = [f"{code} {value!r}" for code, value in labels.items() if value]
    if original:
        variants.append(f"original ({original.get('language')}) {original['text']!r}")
    if variants:
        notes.append("available titles: " + "; ".join(variants))
    if language == "original" and original:
        return str(original["text"])
    title = entity_label(entity, () if language == "original" else (language,))
    return title or (str(original["text"]) if original else "")


def search_films(
    client: NetworkClient,
    query: str,
    year: str | None,
    director: str | None,
    limit: int,
    language: str,
) -> list[dict[str, Any]]:
    classes = "|".join(f"P31={qid}" for qid in FILM_CLASSES)
    data = client.json(
        wikidata_url(
            action="query",
            list="search",
            srsearch=f"{query} haswbstatement:{classes}",
            srlimit=20 if year or director else limit,
        ),
        "Wikidata search",
    )
    ids = [
        str(hit.get("title"))
        for hit in (data.get("query") or {}).get("search", [])
        if isinstance(hit, dict) and QID_RE.fullmatch(str(hit.get("title", "")))
    ]
    entities = wikidata_entities(
        client, ids, "labels|descriptions|claims", label_languages(language)
    )
    director_labels: dict[str, str] = {}
    if director:
        director_ids = sorted(
            {qid for entity in entities.values() for qid in claim_ids(entity, "P57")}
        )
        director_labels = {
            qid: entity_label(entity)
            for qid, entity in wikidata_entities(
                client, director_ids, "labels", "en|mul"
            ).items()
        }

    results = []
    for qid in ids:
        entity = entities.get(qid)
        if entity is None:
            continue
        years = release_years(entity)
        directors = [
            director_labels.get(value, "") for value in claim_ids(entity, "P57")
        ]
        if year and year not in years:
            continue
        if director and not any(
            director.casefold() in name.casefold() for name in directors
        ):
            continue
        description = ((entity.get("descriptions") or {}).get("en") or {}).get(
            "value", ""
        )
        results.append(
            {
                "id": qid,
                "title": entity_label(
                    entity, () if language == "original" else (language,)
                ),
                "description": description,
                "year": years[0] if years else "",
                "imdb": imdb_id(entity) or None,
                "url": f"{WIKIDATA_PAGE}{qid}",
            }
        )
    return results[:limit]


def draft_film(
    client: NetworkClient,
    identifier: str,
    language: str,
    link_preference: str,
    index: LibraryIndex,
) -> Draft:
    qid = normalize_identifier("wikidata", identifier)
    if not is_canonical_identifier("wikidata", qid):
        raise MediaLookupError("--id must be a Wikidata item ID or URL")
    entities = wikidata_entities(
        client, [qid], "labels|descriptions|claims", label_languages(language)
    )
    if qid not in entities:
        raise MediaLookupError(f"Wikidata has no item {qid}")
    film = entities[qid]
    notes: list[str] = []
    if not set(claim_ids(film, "P31")) & set(FILM_CLASSES):
        notes.append(f"{qid} is not recorded as an instance of a film class")
    title = film_title(film, language, notes)
    if not title:
        raise MediaLookupError(f"Wikidata item {qid} has no usable title")

    director_ids = claim_ids(film, "P57")
    company_ids = claim_ids(film, "P272")
    related = wikidata_entities(
        client,
        list(dict.fromkeys(director_ids + company_ids)),
        "labels|claims",
        "en|mul",
    )
    family_ids = sorted(
        {
            family
            for qid_value in director_ids
            if qid_value in related
            for family in claim_ids(related[qid_value], "P734")
        }
    )
    family_labels = {
        family: entity_label(value)
        for family, value in wikidata_entities(
            client, family_ids, "labels", "en|mul"
        ).items()
    }
    directors = [
        person_name(related[value], family_labels)
        for value in director_ids
        if value in related
    ]
    if any(name.startswith("{") for name in directors):
        notes.append("a director name is braced because its family name is unknown")
    companies = [
        entity_label(related[value]) for value in company_ids if value in related
    ]
    companies = [company for company in companies if company]
    if len(companies) > 2:
        notes.append(f"{len(companies)} production companies listed; trim if needed")

    imdb = imdb_id(film)
    links = film_watch_links(film)
    if any(link.kind == "video" for link in links):
        notes.append("video links shorter than the film (often trailers) are not used")
    if imdb:
        links.append(Link("reference", f"{IMDB_PAGE}{imdb}/"))
    links.append(Link("reference", f"{WIKIDATA_PAGE}{qid}"))

    fields = {
        "author": " and ".join(name for name in directors if name),
        "date": release_date(film),
        "publisher": " and ".join(companies),
        "type": "Film",
        "imdb": imdb,
        "wikidata": qid,
    }
    return build_draft(
        entry_type="movie",
        title=title,
        fields=fields,
        links=links,
        link_preference=link_preference,
        sources=[f"{WIKIDATA_PAGE}{qid}"],
        notes=notes,
        index=index,
        key_title=entity_label(film, ("en",)),
    )


def print_candidates(kind: str, results: list[dict[str, Any]]) -> None:
    if not results:
        print("No candidates found. Refine the title, artist/director, or year.")
        return
    for number, result in enumerate(results, start=1):
        if kind == "music":
            credit = f" — {result['credit']}" if result["credit"] else ""
            kinds = f" [{result['type']}]" if result["type"] else ""
            print(
                f"{number}. {result['title']}{credit} ({result['date'] or '?'}){kinds}"
            )
            print(f"   musicbrainz {result['id']}")
        else:
            print(f"{number}. {result['title']} ({result['year'] or '?'})")
            if result["description"]:
                print(f"   {result['description']}")
            imdb = f"  imdb {result['imdb']}" if result["imdb"] else ""
            print(f"   wikidata {result['id']}{imdb}")
        print(f"   {result['url']}")
    print("\nDraft one with --id <identifier>.")


def print_draft(draft: Draft) -> None:
    print("DRAFT pending manifest item — review before use; nothing was written")
    print(json.dumps(draft.item, ensure_ascii=False, indent=2))
    if draft.links:
        print("\nLINKS (fields.url becomes the catalog [URL] link)")
        for link in draft.links:
            print(f"  {link.kind:<9} {link.url}")
    if draft.notes:
        print("\nNOTES")
        for note in draft.notes:
            print(f"  - {note}")


def run(args: argparse.Namespace, client: NetworkClient) -> int:
    root = args.root.expanduser().resolve()
    if args.identifier is None:
        if args.kind == "music":
            results = search_music(
                client, args.query, args.artist, args.year, args.limit
            )
        else:
            results = search_films(
                client, args.query, args.year, args.director, args.limit, args.language
            )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_candidates(args.kind, results)
        return 0

    index = load_library_index(root)
    if args.kind == "music":
        draft = draft_music(client, args.identifier, args.link, index)
    else:
        draft = draft_film(client, args.identifier, args.language, args.link, index)
    if args.json:
        payload = {
            "item": draft.item,
            "links": [{"kind": link.kind, "url": link.url} for link in draft.links],
            "notes": list(draft.notes),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_draft(draft)
    return 0


def main() -> int:
    args = parse_args()
    try:
        return run(args, NetworkClient(args.timeout))
    except (MediaLookupError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
