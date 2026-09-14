from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from paperlib.validation import validate_library


VALID_BIBLIOGRAPHY = """% Synthetic private bibliography.

% Topic: PeripheralEsoteric / DigitalBooks

@book{editor2024handbook,
  editor     = {Editor, Erin},
  title      = {Synthetic Handbook},
  date       = {2024},
  publisher  = {Example Press},
  keywords   = {PeripheralEsoteric, DigitalBooks},
  file       = {}
}
"""

VALID_CATALOG = """#let bibliography-file = "library.bib"

= Peripheral & Esoteric

== Digital Books

- #text("Synthetic Handbook") @editor2024handbook

#bibliography(
  bibliography-file,
  title: [References],
)
"""


class SemanticValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-validation-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "library.bib").write_text(VALID_BIBLIOGRAPHY, encoding="utf-8")
        (self.root / "main.typ").write_text(VALID_CATALOG, encoding="utf-8")

    def validate(self):
        return validate_library(self.root, compile_catalog=False)

    def test_accepts_semantically_consistent_editor_only_pending_record(self) -> None:
        result = self.validate()

        self.assertEqual(result.errors, ())
        self.assertEqual((result.entries, result.files, result.pending), (1, 0, 1))

    def test_at_sign_inside_title_is_not_mistaken_for_a_citation(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "Synthetic Handbook", "Synthetic Fe@C Handbook"
        )
        catalog = VALID_CATALOG.replace("Synthetic Handbook", "Synthetic Fe@C Handbook")
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertEqual(result.errors, ())

    def test_detects_duplicate_catalog_citations_without_deduplicating(self) -> None:
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        catalog = catalog.replace(
            "#bibliography(",
            '- #text("Synthetic Handbook") @editor2024handbook\n\n#bibliography(',
        )
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog contains citation key more than once: editor2024handbook",
            result.errors,
        )

    def test_detects_catalog_title_and_taxonomy_drift(self) -> None:
        catalog = VALID_CATALOG.replace(
            "Synthetic Handbook", "Different Display Title"
        ).replace("== Digital Books", "== Unrelated Books")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog and BibTeX titles differ for editor2024handbook", result.errors
        )
        self.assertIn(
            "catalog headings and BibTeX keywords differ for editor2024handbook",
            result.errors,
        )

    def test_revalidates_media_content_during_consistency_check(self) -> None:
        relative = "Library/PeripheralEsoteric/DigitalBooks/SyntheticHandbook.pdf"
        destination = self.root / relative
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"not really a PDF")
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "file       = {}", f"file       = {{{relative}}}"
        )
        catalog = VALID_CATALOG.replace(
            '- #text("Synthetic Handbook")',
            f'- #link("{relative}")[#text("Synthetic Handbook")]',
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertTrue(
            any(error.startswith("invalid library media") for error in result.errors),
            result.errors,
        )

    def test_rejects_impossible_canonical_date(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "date       = {2024}", "date       = {2024-13-40}"
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "entry editor2024handbook has a non-canonical date: 2024-13-40",
            result.errors,
        )


if __name__ == "__main__":
    unittest.main()
