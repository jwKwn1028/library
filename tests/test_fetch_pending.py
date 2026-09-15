from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPOSITORY_ROOT / "skills/paper-library-intake/scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

import fetch_pending  # noqa: E402
import stage_papers  # noqa: E402


PENDING_BIBLIOGRAPHY = """% Synthetic private bibliography.

% Topic: QuantumChemistry / ElectronicStructure / ExampleTheory

@article{example2026pending,
  author       = {Example, Ada},
  title        = {A Synthetic Pending Study},
  journaltitle = {Journal of Synthetic Examples},
  date         = {2026},
  doi          = {10.0000/synthetic-pending},
  url          = {https://doi.org/10.0000/synthetic-pending},
  keywords     = {QuantumChemistry, ElectronicStructure, ExampleTheory},
  file         = {}
}

@article{example2025available,
  author       = {Example, Ada},
  title        = {An Available Synthetic Study},
  journaltitle = {Journal of Synthetic Examples},
  date         = {2025},
  doi          = {10.0000/synthetic-available},
  keywords     = {QuantumChemistry, ElectronicStructure, ExampleTheory},
  file         = {Library/QuantumChemistry/ElectronicStructure/ExampleTheory/Available.pdf}
}
"""


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str = "https://example.test/paper.pdf"):
        super().__init__(data)
        self.url = url

    def geturl(self) -> str:
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_arguments):
        self.close()


SECOND_PENDING_ENTRY = """
@article{example2026companion,
  author       = {Sample, Grace},
  title        = {Companion Measurements for Synthetic Pending Work},
  journaltitle = {Journal of Synthetic Examples},
  date         = {2026},
  doi          = {10.0000/synthetic-companion},
  keywords     = {QuantumChemistry, ElectronicStructure, ExampleTheory},
  file         = {}
}
"""


class FakeDiscoveryClient:
    def json(self, url: str, source: str):
        if source == "Semantic Scholar":
            return {
                "paperId": "0" * 40,
                "externalIds": {
                    "DOI": "10.0000/SYNTHETIC-PENDING",
                    "ArXiv": "2601.00001",
                },
                "openAccessPdf": {
                    "url": "https://repository.test/green.pdf",
                    "status": "GREEN",
                },
            }
        if source == "Unpaywall":
            return {
                "best_oa_location": {
                    "url_for_pdf": "https://repository.test/open.pdf?token=private",
                    "version": "acceptedVersion",
                },
                "oa_locations": [],
            }
        if source == "OpenAlex":
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.0000/SYNTHETIC-PENDING",
                        "best_oa_location": {
                            "is_oa": True,
                            "pdf_url": "https://archive.test/manuscript.pdf",
                            "version": "acceptedVersion",
                            "source": {"display_name": "Synthetic Archive"},
                        },
                        "locations": [],
                    }
                ]
            }
        return {
            "message": {
                "link": [
                    {
                        "URL": "https://publisher.test/article.pdf",
                        "content-type": "application/pdf",
                        "content-version": "vor",
                    },
                    {
                        "URL": "https://publisher.test/article.xml",
                        "content-type": "application/xml",
                    },
                ]
            }
        }


class FakeDownloadClient:
    def __init__(self, data: bytes):
        self.data = data

    def open(self, _url: str, _accept: str):
        return FakeResponse(self.data)


class FakeRoutingClient:
    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.requested: list[str] = []

    def open(self, url: str, _accept: str):
        self.requested.append(url)
        if url not in self.pages:
            raise fetch_pending.FetchError("HTTP 404")
        return FakeResponse(self.pages[url], url)


class FakeHandleClient:
    def json(self, _url: str, source: str):
        if source != "DOI handle":
            raise fetch_pending.FetchError("unexpected source")
        return {
            "values": [
                {
                    "type": "URL",
                    "data": {"value": "https://publisher.test/article/pending"},
                }
            ]
        }


class FetchPendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-fetch-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "library.bib").write_text(PENDING_BIBLIOGRAPHY, encoding="utf-8")
        self.record = fetch_pending.load_pending_records(self.root)[0]

    def test_loads_only_doi_backed_pending_records(self) -> None:
        records = fetch_pending.load_pending_records(self.root)

        self.assertEqual(
            [record.citation_key for record in records], ["example2026pending"]
        )
        self.assertEqual(
            records[0].topic,
            ("QuantumChemistry", "ElectronicStructure", "ExampleTheory"),
        )

    def test_rejects_a_nonpending_requested_key(self) -> None:
        with self.assertRaisesRegex(
            fetch_pending.FetchError, "not a DOI-backed pending record"
        ):
            fetch_pending.select_records(
                fetch_pending.load_pending_records(self.root),
                ["example2025available"],
            )

    def test_discovers_oa_and_crossref_pdf_candidates(self) -> None:
        candidates, errors = fetch_pending.discover_candidates(
            self.record, FakeDiscoveryClient(), "reader" + "@" + "example.test"
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            [candidate.source for candidate in candidates],
            [
                "Unpaywall (acceptedVersion)",
                "OpenAlex OA (acceptedVersion; Synthetic Archive)",
                "Semantic Scholar OA (green)",
                "Crossref full text (vor)",
                "arXiv (2601.00001)",
                "DOI resolver",
            ],
        )
        self.assertEqual(
            fetch_pending.display_url(candidates[0].url),
            "https://repository.test/open.pdf",
        )
        self.assertEqual(candidates[4].url, "https://arxiv.org/pdf/2601.00001")

    def test_semantic_scholar_rejects_a_different_work(self) -> None:
        client = mock.Mock()
        client.json.return_value = {"externalIds": {"DOI": "10.0000/other"}}

        with self.assertRaisesRegex(fetch_pending.FetchError, "different DOI"):
            fetch_pending.semantic_scholar_candidates(self.record, client)

    def test_follows_a_landing_page_citation_pdf_url_once(self) -> None:
        landing = (
            b'<html><head><meta name="citation_pdf_url" '
            b'content="/files/paper.pdf"></head></html>'
        )
        client = FakeRoutingClient(
            {
                "https://repository.test/record": landing,
                "https://repository.test/files/paper.pdf": b"%PDF-synthetic",
            }
        )
        candidate = fetch_pending.Candidate(
            "synthetic", "https://repository.test/record", "https://repository.test"
        )
        with (
            mock.patch.object(fetch_pending, "validate_media"),
            mock.patch.object(fetch_pending, "verify_pdf_identity"),
        ):
            destination, _digest, selected, failures, status = (
                fetch_pending.download_record(
                    self.root, self.record, [candidate], client, 1024
                )
            )

        self.assertEqual(status, "downloaded")
        self.assertEqual(selected.source, "synthetic landing-page PDF")
        self.assertEqual(selected.url, "https://repository.test/files/paper.pdf")
        self.assertFalse(selected.follow_landing)
        self.assertEqual(len(failures), 1)
        self.assertEqual(destination.read_bytes(), b"%PDF-synthetic")

    def test_identity_score_ranks_doi_title_and_approximate_matches(self) -> None:
        self.assertEqual(
            fetch_pending.identity_score("doi: 10.0000/synthetic-pending", self.record),
            (3, 1.0),
        )
        self.assertEqual(
            fetch_pending.identity_score("A Synthetic Pending Study", self.record)[0],
            2,
        )
        self.assertEqual(
            fetch_pending.identity_score(
                "doi: 10.0000/synthetic-pending7 unrelated", self.record
            )[0],
            0,
        )

    def test_match_copies_only_unique_matches_into_inbox(self) -> None:
        (self.root / "library.bib").write_text(
            PENDING_BIBLIOGRAPHY + SECOND_PENDING_ENTRY, encoding="utf-8"
        )
        records = fetch_pending.load_pending_records(self.root)
        downloads = self.root / "downloads"
        downloads.mkdir()
        texts = {
            "first.pdf": "A Synthetic Pending Study\nAda Example",
            "both.pdf": (
                "A Synthetic Pending Study and "
                "Companion Measurements for Synthetic Pending Work"
            ),
            "scan.pdf": "",
        }
        for name in texts:
            (downloads / name).write_bytes(b"%PDF-" + name.encode())
        (downloads / "notes.txt").write_text("ignored", encoding="utf-8")

        with (
            mock.patch.object(fetch_pending, "validate_media"),
            mock.patch.object(stage_papers, "validate_media"),
            mock.patch.object(
                fetch_pending, "pdf_text", side_effect=lambda path: texts[path.name]
            ),
        ):
            results = fetch_pending.plan_matches(
                self.root, fetch_pending.match_sources([downloads]), records
            )
            by_name = {result.source.name: result for result in results}
            self.assertEqual(by_name["first.pdf"].status, "matched")
            self.assertEqual(
                by_name["first.pdf"].record.citation_key, "example2026pending"
            )
            self.assertEqual(by_name["both.pdf"].status, "ambiguous")
            self.assertEqual(by_name["scan.pdf"].status, "unmatched")

            fetch_pending.copy_plans(
                self.root,
                [
                    fetch_pending.StagePlan(
                        result.source, result.destination, result.digest
                    )
                    for result in results
                    if result.status == "matched"
                ],
            )

        self.assertEqual(
            sorted(path.name for path in (self.root / "Inbox").iterdir()),
            ["example2026pending.pdf"],
        )
        self.assertTrue((downloads / "first.pdf").exists())

    def test_browser_handoff_uses_proxy_prefix_and_landing_page(self) -> None:
        with (
            mock.patch.dict(
                fetch_pending.os.environ,
                {
                    fetch_pending.PROXY_ENV: "https://proxy.example.test/login?url=",
                    fetch_pending.BROWSER_ENV: "synthetic-browser --new-tab",
                },
            ),
            mock.patch.object(
                fetch_pending.shutil, "which", return_value="/usr/bin/synthetic"
            ),
            mock.patch.object(fetch_pending.subprocess, "Popen") as popen,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            fetch_pending.open_publisher_pages(
                self.root, [self.record], FakeHandleClient(), 0
            )

        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0],
            [
                "synthetic-browser",
                "--new-tab",
                "https://proxy.example.test/login?url="
                "https://publisher.test/article/pending",
            ],
        )

    def test_rejects_an_unsafe_proxy_prefix(self) -> None:
        for value in (
            "ftp://proxy.example.test/",
            "https://reader" + "@" + "proxy.example.test/",
        ):
            with (
                self.subTest(value=value),
                mock.patch.dict(
                    fetch_pending.os.environ, {fetch_pending.PROXY_ENV: value}
                ),
                self.assertRaisesRegex(fetch_pending.FetchError, "without credentials"),
            ):
                fetch_pending.proxy_prefix()

    def test_downloads_only_after_pdf_and_identity_validation(self) -> None:
        candidate = fetch_pending.Candidate(
            "synthetic", "https://example.test/paper.pdf", "https://example.test"
        )
        with (
            mock.patch.object(fetch_pending, "validate_media"),
            mock.patch.object(fetch_pending, "verify_pdf_identity"),
        ):
            destination, digest, selected, failures, status = (
                fetch_pending.download_record(
                    self.root,
                    self.record,
                    [candidate],
                    FakeDownloadClient(b"%PDF-synthetic"),
                    1024,
                )
            )

        self.assertEqual(status, "downloaded")
        self.assertEqual(selected, candidate)
        self.assertEqual(failures, [])
        self.assertIsNotNone(digest)
        self.assertEqual(destination, self.root / "Inbox/example2026pending.pdf")
        self.assertEqual(destination.read_bytes(), b"%PDF-synthetic")

    def test_rejects_an_html_response_without_leaving_a_file(self) -> None:
        candidate = fetch_pending.Candidate(
            "synthetic", "https://example.test/login", "https://example.test"
        )
        destination, digest, selected, failures, status = fetch_pending.download_record(
            self.root,
            self.record,
            [candidate],
            FakeDownloadClient(b"<html>login required</html>"),
            1024,
        )

        self.assertEqual(status, "unavailable")
        self.assertIsNone(destination)
        self.assertIsNone(digest)
        self.assertIsNone(selected)
        self.assertTrue(any("not a PDF" in failure for failure in failures))
        self.assertEqual(list((self.root / "Inbox").iterdir()), [])

    def test_enforces_the_download_size_limit(self) -> None:
        destination = self.root / "limited.pdf"
        with self.assertRaisesRegex(fetch_pending.FetchError, "exceeded 5 bytes"):
            fetch_pending.stream_pdf(
                FakeResponse(b"%PDF-too-large"), destination, 5, "synthetic"
            )


if __name__ == "__main__":
    unittest.main()
