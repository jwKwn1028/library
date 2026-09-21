from __future__ import annotations

import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SEARCH_SCRIPT = REPOSITORY_ROOT / "scripts/search-bibliography"
SYNTHETIC_BIBLIOGRAPHY = """% Synthetic search fixtures.

@book{editor2023handbook,
  editor = {{Example Research and Teaching Group}},
  title = {Synthetic Handbook},
  subtitle = {Reconstruction},
  series = {Synthetic Manuals},
  number = {2},
  year = {2023},
  keywords = {Literature, DigitalBooks},
  file = {}
}

% Topic: QuantumChemistry / ElectronicStructure / EmbeddingTheory

@article{example2024dft,
  author = {Exämple, Zoë and Researcher, Ben},
  title = {A Synthetic {DFT} Study},
  subtitle = {Testing the {API}},
  date = {2024-03-04},
  doi = {10.0000/synthetic-dft},
  keywords = {QuantumChemistry, ElectronicStructure, EmbeddingTheory},
  file = {Library/QuantumChemistry/SyntheticStudy.pdf}
}

% Topic: Film / Crime

@movie{director2025synthetic,
  author = {Director, Dana},
  title = {A Synthetic Mystery},
  date = {2025},
  keywords = {Film, Crime},
  file = {}
}
"""


class BibliographySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="paper-library-search-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bibliography = self.root / "library.bib"
        self.bibliography.write_text(SYNTHETIC_BIBLIOGRAPHY, encoding="utf-8")

    def search(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SEARCH_SCRIPT), "--root", str(self.root), *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

    def keys(self, *arguments: str) -> list[str]:
        result = self.search(*arguments, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return [record["citation_key"] for record in json.loads(result.stdout)]

    def test_matches_each_requested_field_and_normalizes_display_text(self) -> None:
        for query in (
            "dft",
            "EXAMPLE2024DFT",
            "Zoë",
            "Zoe\u0308",
            "zoe",
            "example",
            "electronic structure",
            "EmbeddingTheory",
            "QuantumChemistry/ElectronicStructure",
            "10.0000/SYNTHETIC-DFT",
            "testing API",
        ):
            with self.subTest(query=query):
                keys = self.keys(query)
                self.assertIn("example2024dft", keys)
                self.assertNotIn("director2025synthetic", keys)

    def test_every_term_must_match_but_can_match_different_fields(self) -> None:
        self.assertEqual(self.keys("dft", "zoe", "embedding"), ["example2024dft"])
        self.assertEqual(self.keys("dft zoe embedding"), ["example2024dft"])
        self.assertEqual(self.keys("dft", "crime"), [])

    def test_editor_only_books_series_subtitles_and_keyword_fallback(self) -> None:
        self.assertEqual(
            self.keys("Teaching", "Manuals", "Reconstruction", "DigitalBooks"),
            ["editor2023handbook"],
        )
        result = self.search("handbook", "--json")
        record = json.loads(result.stdout)[0]
        self.assertEqual(
            record["title"], "Synthetic Manuals #2: Synthetic Handbook: Reconstruction"
        )
        self.assertEqual(record["author"], "")
        self.assertEqual(record["editor"], "Example Research and Teaching Group")
        self.assertEqual(record["date"], "2023")
        self.assertEqual(record["topic"], ["Literature", "DigitalBooks"])

    def test_results_are_sorted_and_status_filters_cover_all_media(self) -> None:
        self.assertEqual(
            self.keys("synthetic"),
            ["director2025synthetic", "editor2023handbook", "example2024dft"],
        )
        self.assertEqual(
            self.keys("synthetic", "--pending"),
            ["director2025synthetic", "editor2023handbook"],
        )
        self.assertEqual(self.keys("synthetic", "--local"), ["example2024dft"])

    def test_text_output_identifies_results_and_attachment(self) -> None:
        result = self.search("dft")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Matches: 1", result.stdout)
        self.assertIn("example2024dft [local] (2024-03-04)", result.stdout)
        self.assertIn("A Synthetic DFT Study: Testing the API", result.stdout)
        self.assertIn("Author: Exämple, Zoë and Researcher, Ben", result.stdout)
        self.assertIn(
            "Topic: QuantumChemistry/ElectronicStructure/EmbeddingTheory", result.stdout
        )
        self.assertIn("DOI: 10.0000/synthetic-dft", result.stdout)
        self.assertIn(
            "File: Library/QuantumChemistry/SyntheticStudy.pdf", result.stdout
        )
        pending = self.search("handbook")
        self.assertIn("editor2023handbook [pending]", pending.stdout)
        self.assertIn("Editor: Example Research and Teaching Group", pending.stdout)
        self.assertNotIn("File:", pending.stdout)

    def test_no_matches_and_empty_bibliography_are_successful(self) -> None:
        result = self.search("nonexistent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Matches: 0\n")
        self.assertEqual(self.keys("nonexistent"), [])
        self.bibliography.write_text("% Empty library.\n", encoding="utf-8")
        self.assertEqual(self.keys("synthetic"), [])

    def test_requires_nonempty_query_and_valid_options(self) -> None:
        for arguments in (
            (),
            ("   ",),
            ("\u0308",),
            ("synthetic", "--pending", "--local"),
            ("synthetic", "--lock-timeout", "nan"),
            ("synthetic", "--lock-timeout", "-1"),
        ):
            with self.subTest(arguments=arguments):
                result = self.search(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)

    def test_missing_and_malformed_bibliography_fail_without_partial_results(
        self,
    ) -> None:
        for content in (None, "@article{broken, title = {Unclosed}", "invalid"):
            with self.subTest(content=content):
                if content is None:
                    self.bibliography.unlink()
                else:
                    self.bibliography.write_text(content, encoding="utf-8")
                result = self.search("synthetic", "--json")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("ERROR:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_search_preserves_library_state(self) -> None:
        for name, content in (
            ("main.typ", b"// unchanged"),
            ("Catalog.pdf", b"unchanged"),
        ):
            (self.root / name).write_bytes(content)
        before = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.iterdir()
        }
        result = self.search("synthetic", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, original in before.items():
            path = self.root / name
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            set(before) | {".paper-library.lock"},
        )

    def test_search_respects_shared_library_lock(self) -> None:
        with (self.root / ".paper-library.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.search("synthetic", "--lock-timeout", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("library is busy", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
