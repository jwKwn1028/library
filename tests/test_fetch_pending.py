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


class FakeDiscoveryClient:
    def json(self, url: str, source: str):
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
                "Crossref full text (vor)",
                "DOI resolver",
            ],
        )
        self.assertEqual(
            fetch_pending.display_url(candidates[0].url),
            "https://repository.test/open.pdf",
        )

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
