from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from paperlib.catalog import CatalogError, parse_catalog
from paperlib.validation import validate_library


FILM_URL = "https://watch.example.test/title/synthetic-horizon"
RECORDING_BIBLIOGRAPHY = f"""% Topic: Film / ScienceFiction

@movie{{director2026synthetichorizon,
  author   = {{Director, Dana}},
  title    = {{Synthetic Horizon}},
  date     = {{2026-03-01}},
  type     = {{Film}},
  imdb     = {{tt0000000}},
  wikidata = {{Q4115189}},
  url      = {{{FILM_URL}}},
  keywords = {{Film, ScienceFiction}},
  file     = {{}}
}}
"""
RECORDING_ITEM = (
    "- #reference-title(<director2026synthetichorizon>)"
    '[#text("Synthetic Horizon")] #h(0pt) '
    f'#link("{FILM_URL}")[#text(size: 8pt, weight: "bold")[\\[URL\\]]] '
    "@director2026synthetichorizon"
)

VALID_BIBLIOGRAPHY = """% Synthetic private bibliography.

% Topic: Literature / DigitalBooks

@book{editor2024handbook,
  editor     = {Editor, Erin},
  title      = {Synthetic Handbook},
  date       = {2024},
  publisher  = {Example Press},
  keywords   = {Literature, DigitalBooks},
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

= Literature

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

    def test_accepts_title_with_structured_subtitle(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  date       = {2024},",
            "  subtitle   = {A Structured Subtitle},\n  date       = {2024},",
        )
        catalog = VALID_CATALOG.replace(
            "Synthetic Handbook", "Synthetic Handbook: A Structured Subtitle"
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertEqual(result.errors, ())

    def test_rejects_catalog_title_that_omits_structured_subtitle(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  date       = {2024},",
            "  subtitle   = {A Structured Subtitle},\n  date       = {2024},",
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog and BibTeX titles differ for editor2024handbook", result.errors
        )

    def test_accepts_structured_numbered_series_title(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  date       = {2024},",
            "  series     = {Synthetic Cycle},\n"
            "  number     = {7},\n"
            "  date       = {2024},",
        )
        catalog = VALID_CATALOG.replace(
            "Synthetic Handbook", "Synthetic Cycle #7: Synthetic Handbook"
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertEqual(result.errors, ())

    def test_rejects_catalog_title_that_omits_numbered_series(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  date       = {2024},",
            "  series     = {Synthetic Cycle},\n"
            "  number     = {7},\n"
            "  date       = {2024},",
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "catalog and BibTeX titles differ for editor2024handbook", result.errors
        )

    def test_rejects_invalid_isbn(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  date       = {2024},",
            "  isbn       = {978-0-000-00000-3},\n  date       = {2024},",
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")

        result = self.validate()

        self.assertIn(
            "entry editor2024handbook has an invalid ISBN: 978-0-000-00000-3",
            result.errors,
        )

    def test_rejects_equivalent_isbn10_and_isbn13(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  date       = {2024},",
            "  isbn       = {0-000-00000-0},\n  date       = {2024},",
        )
        bibliography += """

@book{example2025secondhandbook,
  author     = {Example, Ada},
  title      = {A Second Synthetic Handbook},
  isbn       = {978-0-000-00000-2},
  date       = {2025},
  publisher  = {Example Press},
  keywords   = {Literature, DigitalBooks},
  file       = {}
}
"""
        catalog = VALID_CATALOG.replace(
            "#bibliography(",
            "- #reference-title(<example2025secondhandbook>)["
            '#text("A Second Synthetic Handbook")] #h(0pt) '
            "@example2025secondhandbook\n\n#bibliography(",
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        result = self.validate()

        self.assertIn("duplicate ISBN: 9780000000002", result.errors)

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
        relative = "Library/Literature/DigitalBooks/SyntheticHandbook.pdf"
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
        relative = "Library/Literature/DigitalBooks/SyntheticHandbook.pdf"
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

    def write_recording(self, bibliography: str, item: str) -> None:
        catalog = VALID_CATALOG.replace(
            "= Literature\n\n== Digital Books",
            "= Film\n\n== Science Fiction",
        ).replace(
            '- #reference-title(<editor2024handbook>)[#text("Synthetic Handbook")] '
            "#h(0pt) @editor2024handbook",
            item,
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

    def test_accepts_pending_recording_with_matching_url_link(self) -> None:
        self.write_recording(RECORDING_BIBLIOGRAPHY, RECORDING_ITEM)

        result = self.validate()

        self.assertEqual(result.errors, ())
        self.assertEqual((result.entries, result.files, result.pending), (1, 0, 1))

    def test_rejects_recording_url_link_drift(self) -> None:
        self.write_recording(
            RECORDING_BIBLIOGRAPHY,
            RECORDING_ITEM.replace(FILM_URL, "https://watch.example.test/other"),
        )
        self.assertIn(
            "catalog URL link and BibTeX url differ for director2026synthetichorizon",
            self.validate().errors,
        )

        self.write_recording(
            RECORDING_BIBLIOGRAPHY,
            "- #reference-title(<director2026synthetichorizon>)"
            '[#text("Synthetic Horizon")] #h(0pt) @director2026synthetichorizon',
        )
        self.assertIn(
            "audiovisual entry director2026synthetichorizon must show a [URL] link",
            self.validate().errors,
        )

        self.write_recording(
            RECORDING_BIBLIOGRAPHY.replace(f"  url      = {{{FILM_URL}}},\n", ""),
            RECORDING_ITEM,
        )
        self.assertIn(
            "audiovisual entry director2026synthetichorizon shows a [URL] link "
            "without a url",
            self.validate().errors,
        )

    def test_rejects_url_link_on_a_document(self) -> None:
        bibliography = VALID_BIBLIOGRAPHY.replace(
            "  file       = {}", f"  url        = {{{FILM_URL}}},\n  file       = {{}}"
        )
        catalog = VALID_CATALOG.replace(
            "#h(0pt) @editor2024handbook",
            f'#h(0pt) #link("{FILM_URL}")[#text(size: 8pt)[\\[URL\\]]] '
            "@editor2024handbook",
        )
        (self.root / "library.bib").write_text(bibliography, encoding="utf-8")
        (self.root / "main.typ").write_text(catalog, encoding="utf-8")

        self.assertIn(
            "only audio and video entries show a [URL] link: editor2024handbook",
            self.validate().errors,
        )

    def test_rejects_unsafe_noncanonical_and_duplicate_recording_fields(self) -> None:
        second = (
            RECORDING_BIBLIOGRAPHY.split("\n", 2)[2]
            .replace("director2026synthetichorizon", "remaker2031synthetichorizon")
            .replace("Director, Dana", "Remaker, Rae")
            .replace("2026-03-01", "2031-05-01")
            .replace("tt0000000", "https://www.imdb.com/title/tt0000001/")
            .replace(FILM_URL, "ftp://files.example.test/film")
        )
        second_item = (
            RECORDING_ITEM.replace(
                "director2026synthetichorizon", "remaker2031synthetichorizon"
            )
            .replace(FILM_URL, "ftp://files.example.test/film")
            .replace("[\\[URL\\]]", "[\\[MKV\\]]")
        )
        self.write_recording(
            f"{RECORDING_BIBLIOGRAPHY}\n{second}", f"{RECORDING_ITEM}\n\n{second_item}"
        )

        errors = self.validate().errors

        self.assertIn(
            "entry remaker2031synthetichorizon has a non-canonical imdb identifier: "
            "https://www.imdb.com/title/tt0000001/",
            errors,
        )
        self.assertIn("duplicate wikidata identifier: Q4115189", errors)
        self.assertIn(
            "entry remaker2031synthetichorizon has an unsafe or non-HTTP(S) url",
            errors,
        )

    def test_catalog_parser_separates_library_and_web_links(self) -> None:
        catalog = (
            "= Film\n\n"
            "- #reference-title(<director2026synthetichorizon>)"
            '[#text("Synthetic Horizon")] #h(0pt) '
            '#link("Library/Film/SyntheticHorizon.mkv")[#text[\\[MKV\\]]] '
            f'#link("{FILM_URL}")[#text(size: 8pt)[\\[URL\\]]] '
            "@director2026synthetichorizon\n\n"
            "#bibliography(bibliography-file) <references>\n"
        )

        item = parse_catalog(catalog)[0]

        self.assertEqual(item.path, "Library/Film/SyntheticHorizon.mkv")
        self.assertEqual(item.url, FILM_URL)
        self.assertTrue(item.url_label)
        with self.assertRaisesRegex(CatalogError, "at most one library-file link"):
            parse_catalog(
                catalog.replace(
                    "Library/Film/SyntheticHorizon.mkv", "https://watch.example.test/"
                )
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
