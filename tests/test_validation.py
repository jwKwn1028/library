from __future__ import annotations

from pathlib import Path
import shutil
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
#let title-link-style = "styles/title-link.csl"
#let reference-title(key, body) = cite(
  key,
  supplement: body,
  style: title-link-style,
)

= Peripheral & Esoteric

== Digital Books

- #reference-title(<editor2024handbook>)[#text("Synthetic Handbook")] #h(0pt) @editor2024handbook

#bibliography(
  bibliography-file,
  title: [References],
) <references>
"""


class SemanticValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-validation-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "styles").mkdir()
        shutil.copy2(
            Path(__file__).resolve().parents[1] / "styles/title-link.csl",
            self.root / "styles/title-link.csl",
        )
        (self.root / "library.bib").write_text(VALID_BIBLIOGRAPHY, encoding="utf-8")
        (self.root / "main.typ").write_text(VALID_CATALOG, encoding="utf-8")

    def validate(self):
        return validate_library(self.root, compile_catalog=False)

    def test_accepts_semantically_consistent_editor_only_pending_record(self) -> None:
        result = self.validate()

        self.assertEqual(result.errors, ())
        self.assertEqual((result.entries, result.files, result.pending), (1, 0, 1))

    def test_rejects_pending_title_without_reference_link(self) -> None:
        catalog = VALID_CATALOG.replace(
            '#reference-title(<editor2024handbook>)[#text("Synthetic Handbook")]',
            '#text("Synthetic Handbook")',
        )
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog entry editor2024handbook must link its title to its bibliography entry",
            result.errors,
        )

    def test_rejects_title_link_to_another_bibliography_entry(self) -> None:
        catalog = VALID_CATALOG.replace("<editor2024handbook>", "<other2024record>", 1)
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog entry editor2024handbook links its title to bibliography entry "
            "other2024record",
            result.errors,
        )

    def test_rejects_missing_bibliography_reference_target(self) -> None:
        catalog = VALID_CATALOG.replace(") <references>", ")")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "main.typ must label its bibliography <references> exactly once",
            result.errors,
        )

    def test_rejects_a_noncanonical_reference_title_helper(self) -> None:
        catalog = VALID_CATALOG.replace(
            "style: title-link-style,", "style: citation-style,"
        )
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "main.typ must define the canonical reference-title helper", result.errors
        )

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
            "- #reference-title(<editor2024handbook>)["
            '#text("Synthetic Handbook")] #h(0pt) '
            "@editor2024handbook\n\n#bibliography(",
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
            '- #reference-title(<editor2024handbook>)[#text("Synthetic Handbook")]',
            f"- #reference-title(<editor2024handbook>)["
            f'#text("Synthetic Handbook")] #h(0pt) '
            f'#link("{relative}")['
            '#text(size: 8pt, weight: "bold")[\\[PDF\\]]]',
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertTrue(
            any(error.startswith("invalid library media") for error in result.errors),
            result.errors,
        )
        self.assertNotIn(
            "catalog entry editor2024handbook must link its title to its bibliography entry",
            result.errors,
        )
        self.assertNotIn(
            "local entry editor2024handbook must show a [PDF] attachment link",
            result.errors,
        )

    def test_rejects_local_item_without_bibliography_entry_title_link(self) -> None:
        relative = "Library/PeripheralEsoteric/DigitalBooks/SyntheticHandbook.pdf"
        destination = self.root / relative
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"not really a PDF")
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "file       = {}", f"file       = {{{relative}}}"
        )
        catalog = VALID_CATALOG.replace(
            '- #reference-title(<editor2024handbook>)[#text("Synthetic Handbook")]',
            f'- #link("{relative}")[#text("Synthetic Handbook")] "[PDF]"',
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog entry editor2024handbook must link its title to its bibliography entry",
            result.errors,
        )
        self.assertIn(
            "local entry editor2024handbook must show a [PDF] attachment link",
            result.errors,
        )

    def test_private_inbox_media_is_not_treated_as_canonical_library_state(
        self,
    ) -> None:
        inbox_file = self.root / "Inbox/unrelated.pdf"
        inbox_file.parent.mkdir()
        inbox_file.write_bytes(b"not a cataloged PDF")

        result = self.validate()

        self.assertEqual(result.errors, ())

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
