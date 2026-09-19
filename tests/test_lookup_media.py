from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOOKUP_SCRIPTS = REPOSITORY_ROOT / "skills/music-film-intake/scripts"
INTAKE_ENGINE = (
    REPOSITORY_ROOT / "skills" / "paper-library-intake" / "scripts" / "intake_papers.py"
)
if str(LOOKUP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LOOKUP_SCRIPTS))

import lookup_media  # noqa: E402


ALBUM_ID = "00000000-0000-4000-8000-000000000001"
FILM_ID = "Q4115189"
ALBUM_QID = "Q13406268"


def item_value(qid: str) -> dict[str, object]:
    return {"entity-type": "item", "id": qid}


def statement(value: object, qualifiers: dict[str, object] | None = None):
    return {
        "mainsnak": {"datavalue": {"value": value}},
        "rank": "normal",
        "qualifiers": qualifiers or {},
    }


def duration(amount: str, unit: str) -> dict[str, object]:
    return {"amount": amount, "unit": f"http://www.wikidata.org/entity/{unit}"}


def release_time(value: str, precision: int) -> dict[str, object]:
    return {"time": value, "precision": precision}


RELEASE_GROUP = {
    "id": ALBUM_ID,
    "title": "Synthetic Sessions",
    "primary-type": "Album",
    "secondary-types": [],
    "first-release-date": "2026-01-15",
    "artist-credit": [
        {
            "name": "Example Ensemble",
            "joinphrase": " & ",
            "artist": {
                "name": "Example Ensemble",
                "sort-name": "Example Ensemble",
                "type": "Group",
            },
        },
        {
            "name": "Ada Example",
            "joinphrase": "",
            "artist": {
                "name": "Ada Example",
                "sort-name": "Example, Ada",
                "type": "Person",
            },
        },
    ],
    "relations": [
        {
            "type": "wikidata",
            "url": {"resource": f"https://www.wikidata.org/wiki/{ALBUM_QID}"},
        }
    ],
}
RELEASES = {
    "releases": [
        {
            "id": "00000000-0000-4000-8000-000000000011",
            "date": "2027-02-01",
            "country": "XW",
            "label-info": [{"label": {"name": "Reissue Records"}}],
            "relations": [
                {
                    "type": "streaming",
                    "url": {"resource": "https://music.apple.com/xx/album/1"},
                },
                {
                    "type": "streaming",
                    "url": {"resource": "https://open.spotify.com/album/synthetic"},
                },
            ],
        },
        {
            "id": "00000000-0000-4000-8000-000000000012",
            "date": "2026-01-15",
            "country": "XE",
            "label-info": [{"label": {"name": "Example Records"}}],
            "relations": [
                {
                    "type": "purchase for download",
                    "url": {"resource": "https://store.example.test/album"},
                }
            ],
        },
        {"id": "00000000-0000-4000-8000-000000000013", "date": ""},
    ]
}
MUSIC_SEARCH = {
    "release-groups": [
        {
            "id": ALBUM_ID,
            "title": "Synthetic Sessions",
            "primary-type": "Album",
            "secondary-types": ["Live"],
            "first-release-date": "2026-01-15",
            "artist-credit": RELEASE_GROUP["artist-credit"],
        },
        {
            "id": "00000000-0000-4000-8000-000000000002",
            "title": "Synthetic Sessions",
            "primary-type": "Album",
            "first-release-date": "2030",
            "artist-credit": [{"name": "Other Ensemble", "joinphrase": ""}],
        },
    ]
}
FILM = {
    "entities": {
        FILM_ID: {
            "labels": {
                "en": {"value": "Synthetic Horizon"},
                "ko": {"value": "합성 지평선"},
            },
            "descriptions": {"en": {"value": "2026 film directed by Dana Director"}},
            "claims": {
                "P31": [statement(item_value("Q11424"))],
                "P57": [statement(item_value("Q900001"))],
                "P272": [statement(item_value("Q900002"))],
                "P577": [
                    statement(release_time("+2027-01-10T00:00:00Z", 11)),
                    statement(release_time("+2026-00-00T00:00:00Z", 9)),
                    statement(release_time("+2026-03-01T00:00:00Z", 11)),
                ],
                "P345": [statement("tt0000000")],
                "P1476": [statement({"text": "Horizon synthétique", "language": "fr"})],
                "P2047": [statement(duration("+100", "Q7727"))],
                "P1651": [
                    statement(
                        "trailer0001",
                        {
                            "P2047": [
                                {"datavalue": {"value": duration("+120", "Q11574")}}
                            ]
                        },
                    ),
                    statement(
                        "fullfilm001",
                        {
                            "P2047": [
                                {"datavalue": {"value": duration("+5990", "Q11574")}}
                            ]
                        },
                    ),
                ],
            },
        }
    }
}
FILM_PEOPLE = {
    "entities": {
        "Q900001": {
            "labels": {"en": {"value": "Dana Director"}},
            "claims": {"P734": [statement(item_value("Q900003"))]},
        },
        "Q900002": {"labels": {"en": {"value": "Example Pictures"}}, "claims": {}},
    }
}
FAMILY_NAMES = {"entities": {"Q900003": {"labels": {"mul": {"value": "Director"}}}}}
FILM_SEARCH = {"query": {"search": [{"title": FILM_ID}, {"title": "Q900009"}]}}
OTHER_FILM = {
    "entities": {
        "Q900009": {
            "labels": {"en": {"value": "Synthetic Horizon"}},
            "descriptions": {"en": {"value": "2031 remake"}},
            "claims": {
                "P577": [statement(release_time("+2031-05-01T00:00:00Z", 11))],
                "P57": [statement(item_value("Q900010"))],
            },
        }
    }
}


class FakeResponse(io.BytesIO):
    def __init__(self, payload: object, url: str):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.url = url

    def geturl(self) -> str:
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_arguments):
        self.close()


class FakeOpener:
    """Serve synthetic JSON by URL fragment and record every request."""

    def __init__(self, routes: list[tuple[str, object]]):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        for fragment, payload in self.routes:
            if fragment in request.full_url:
                if isinstance(payload, Exception):
                    self.routes.remove((fragment, payload))
                    raise payload
                return FakeResponse(payload, request.full_url)
        raise AssertionError(f"unexpected request: {request.full_url}")


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


MUSIC_ROUTES = [
    (f"ws/2/release-group/{ALBUM_ID}?", RELEASE_GROUP),
    ("ws/2/release?", RELEASES),
    ("ws/2/release-group?", MUSIC_SEARCH),
]
FILM_ROUTES = [
    ("list=search", FILM_SEARCH),
    (
        f"ids={FILM_ID}%7CQ900009",
        {"entities": {**FILM["entities"], **OTHER_FILM["entities"]}},
    ),
    (f"ids={FILM_ID}&", FILM),
    ("ids=Q900001%7CQ900002", FILM_PEOPLE),
    ("ids=Q900001%7CQ900010", FILM_PEOPLE),
    ("ids=Q900003", FAMILY_NAMES),
]


class LookupMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-lookup-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.time = FakeTime()

    def client(self, routes: list[tuple[str, object]]):
        opener = FakeOpener(list(routes))
        client = lookup_media.NetworkClient(
            30.0, opener=opener, sleep=self.time.sleep, clock=self.time.clock
        )
        return client, opener

    def run_lookup(self, routes, *arguments: str):
        client, opener = self.client(routes)
        args = lookup_media.parse_args([*arguments, "--root", str(self.root)])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = lookup_media.run(args, client)
        self.assertEqual(status, 0)
        return output.getvalue(), opener

    def test_music_search_quotes_terms_and_filters_by_year(self) -> None:
        output, opener = self.run_lookup(
            MUSIC_ROUTES,
            "music",
            'Synthetic "Sessions"',
            "--artist",
            "Example Ensemble",
            "--year",
            "2026",
            "--json",
        )

        results = json.loads(output)
        self.assertEqual([result["id"] for result in results], [ALBUM_ID])
        self.assertEqual(results[0]["credit"], "Example Ensemble & Ada Example")
        self.assertEqual(results[0]["type"], "Album + Live")
        query = parse_qs(urlsplit(opener.requests[0].full_url).query)["query"][0]
        self.assertEqual(
            query,
            'releasegroup:"Synthetic \\"Sessions\\"" AND artist:"Example Ensemble"',
        )

    def test_music_draft_uses_release_group_label_and_streaming_link(self) -> None:
        output, _opener = self.run_lookup(
            MUSIC_ROUTES,
            "music",
            "--id",
            f"https://musicbrainz.org/release-group/{ALBUM_ID}",
            "--json",
        )

        draft = json.loads(output)
        item = draft["item"]
        self.assertEqual(item["entry_type"], "audio")
        self.assertTrue(item["pending"])
        self.assertEqual(item["citation_key"], "example2026syntheticsessions")
        self.assertEqual(
            item["fields"],
            {
                "author": "{Example Ensemble} and Example, Ada",
                "date": "2026-01-15",
                "publisher": "Example Records",
                "type": "Album",
                "musicbrainz": ALBUM_ID,
                "wikidata": ALBUM_QID,
                "url": "https://open.spotify.com/album/synthetic",
            },
        )
        self.assertEqual(
            item["metadata_sources"],
            [
                f"https://musicbrainz.org/release-group/{ALBUM_ID}",
                "https://musicbrainz.org/release/00000000-0000-4000-8000-000000000012",
            ],
        )
        self.assertEqual(
            [link["url"] for link in draft["links"]],
            [
                "https://open.spotify.com/album/synthetic",
                "https://music.apple.com/xx/album/1",
                f"https://musicbrainz.org/release-group/{ALBUM_ID}",
            ],
        )
        self.assertTrue(any("2 artists" in note for note in draft["notes"]))
        self.assertEqual(len(self.time.sleeps), 1)
        self.assertAlmostEqual(
            self.time.sleeps[0], lookup_media.MINIMUM_INTERVALS["musicbrainz.org"]
        )

    def test_reference_link_preference_skips_streaming_pages(self) -> None:
        output, _opener = self.run_lookup(
            MUSIC_ROUTES, "music", "--id", ALBUM_ID, "--link", "reference", "--json"
        )

        fields = json.loads(output)["item"]["fields"]
        self.assertEqual(
            fields["url"], f"https://musicbrainz.org/release-group/{ALBUM_ID}"
        )

    def test_film_draft_orders_director_names_and_ignores_trailers(self) -> None:
        output, _opener = self.run_lookup(
            FILM_ROUTES, "film", "--id", FILM_ID, "--json"
        )

        draft = json.loads(output)
        item = draft["item"]
        self.assertEqual(item["entry_type"], "movie")
        self.assertEqual(item["title"], "Synthetic Horizon")
        self.assertEqual(item["citation_key"], "director2026synthetichorizon")
        self.assertEqual(
            item["fields"],
            {
                "author": "Director, Dana",
                "date": "2026-03-01",
                "publisher": "Example Pictures",
                "type": "Film",
                "imdb": "tt0000000",
                "wikidata": FILM_ID,
                "url": "https://www.youtube.com/watch?v=fullfilm001",
            },
        )
        kinds = {link["url"]: link["kind"] for link in draft["links"]}
        self.assertEqual(kinds["https://www.youtube.com/watch?v=trailer0001"], "video")
        self.assertEqual(kinds["https://www.imdb.com/title/tt0000000/"], "reference")
        self.assertTrue(any("trailers" in note for note in draft["notes"]))
        self.assertTrue(any("Horizon synthétique" in note for note in draft["notes"]))

    def test_film_title_language_keeps_an_ascii_citation_key(self) -> None:
        output, _opener = self.run_lookup(
            FILM_ROUTES, "film", "--id", FILM_ID, "--language", "ko", "--json"
        )
        item = json.loads(output)["item"]
        self.assertEqual(item["title"], "합성 지평선")
        self.assertEqual(item["citation_key"], "director2026synthetichorizon")

        output, _opener = self.run_lookup(
            FILM_ROUTES, "film", "--id", FILM_ID, "--language", "original", "--json"
        )
        self.assertEqual(json.loads(output)["item"]["title"], "Horizon synthétique")

    def test_film_search_filters_by_year_and_director(self) -> None:
        output, _opener = self.run_lookup(
            FILM_ROUTES,
            "film",
            "Synthetic Horizon",
            "--year",
            "2026",
            "--director",
            "Dana",
            "--json",
        )

        results = json.loads(output)
        self.assertEqual([result["id"] for result in results], [FILM_ID])
        self.assertEqual(results[0]["imdb"], "tt0000000")
        self.assertEqual(results[0]["year"], "2026")

    def test_group_sort_name_supplies_the_citation_key_family(self) -> None:
        index = lookup_media.LibraryIndex(frozenset(), {}, {})
        arguments = ("{Person Example Group}", "2026-01-15", "To the Edge of Synthesis")

        self.assertEqual(
            lookup_media.suggest_key(*arguments, index, [], "Example"),
            "example2026edgesynthesis",
        )
        self.assertEqual(
            lookup_media.suggest_key(*arguments, index, []), "person2026edgesynthesis"
        )

    def test_person_names_keep_family_first_order_and_brace_unknowns(self) -> None:
        entity = {
            "labels": {"en": {"value": "Kim Example-ho"}},
            "claims": {"P734": [statement(item_value("Q1"))]},
        }
        self.assertEqual(
            lookup_media.person_name(entity, {"Q1": "Kim"}), "Kim, Example-ho"
        )
        self.assertEqual(
            lookup_media.person_name(entity, {"Q1": "Park"}), "{Kim Example-ho}"
        )

    def test_draft_notes_existing_identifiers_and_key_collisions(self) -> None:
        (self.root / "library.bib").write_text(
            """% Topic: Film / ScienceFiction

@movie{director2026synthetichorizon,
  author   = {Director, Dana},
  title    = {Synthetic Horizon},
  date     = {2026-03-01},
  wikidata = {https://www.wikidata.org/wiki/q4115189},
  keywords = {Film, ScienceFiction},
  file     = {}
}
""",
            encoding="utf-8",
        )

        output, _opener = self.run_lookup(
            FILM_ROUTES, "film", "--id", FILM_ID, "--json"
        )

        draft = json.loads(output)
        self.assertEqual(draft["item"]["citation_key"], "director2026synthetichorizona")
        notes = "\n".join(draft["notes"])
        self.assertIn(
            f"DUPLICATE: wikidata {FILM_ID} is already recorded as "
            "director2026synthetichorizon",
            notes,
        )
        self.assertIn("same title, release year, and first creator", notes)

    def test_retries_rate_limits_and_identifies_a_private_contact(self) -> None:
        rate_limited = HTTPError("https://musicbrainz.org/", 429, "busy", None, None)
        routes = [("ws/2/release-group?", rate_limited), *MUSIC_ROUTES]
        contact = "https://example.test/contact"
        with mock.patch.dict(os.environ, {lookup_media.CONTACT_ENV: contact}):
            output, opener = self.run_lookup(routes, "music", "Synthetic Sessions")

        self.assertIn("Synthetic Sessions", output)
        self.assertNotIn(contact, output)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn(contact, opener.requests[-1].get_header("User-agent"))
        self.assertIn(lookup_media.RETRY_PAUSES[0], self.time.sleeps)

    def test_rejects_an_unsafe_contact_and_invalid_arguments(self) -> None:
        with mock.patch.dict(os.environ, {lookup_media.CONTACT_ENV: "a (b)"}):
            with self.assertRaises(lookup_media.MediaLookupError):
                lookup_media.NetworkClient(30.0)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                lookup_media.parse_args(["music"])
            with self.assertRaises(SystemExit):
                lookup_media.parse_args(["film", "Title", "--id", FILM_ID])
            with self.assertRaises(SystemExit):
                lookup_media.parse_args(["film", "Title", "--year", "26"])

    def test_drafts_pass_the_offline_intake_dry_run(self) -> None:
        shutil.copy2(REPOSITORY_ROOT / "templates/main.typ", self.root / "main.typ")
        shutil.copy2(
            REPOSITORY_ROOT / "templates/library.bib", self.root / "library.bib"
        )
        film_output, _opener = self.run_lookup(
            FILM_ROUTES, "film", "--id", FILM_ID, "--json"
        )
        album_output, _opener = self.run_lookup(
            MUSIC_ROUTES, "music", "--id", ALBUM_ID, "--json"
        )
        manifests = [
            (
                "film.json",
                {
                    "topic": {
                        "path": "Film/ScienceFiction",
                        "headings": ["Film", "Science Fiction"],
                    },
                    "items": [json.loads(film_output)["item"]],
                },
            ),
            (
                "music.json",
                {
                    "topic": {"path": "Music/Jazz", "headings": ["Music", "Jazz"]},
                    "items": [json.loads(album_output)["item"]],
                },
            ),
        ]
        arguments = []
        for name, manifest in manifests:
            path = self.root / name
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            arguments.extend(["--manifest", str(path)])

        result = subprocess.run(
            [sys.executable, str(INTAKE_ENGINE), "--root", str(self.root), *arguments],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FILE  PENDING LOCAL PATH", result.stdout)
        self.assertIn(
            "LINK  [URL] https://open.spotify.com/album/synthetic", result.stdout
        )
        self.assertIn("ID    wikidata Q4115189", result.stdout)


if __name__ == "__main__":
    unittest.main()
