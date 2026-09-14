from __future__ import annotations

import json
import fcntl
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTAKE_ENGINE = (
    REPOSITORY_ROOT / "skills" / "paper-library-intake" / "scripts" / "intake_papers.py"
)


class IntakeFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-formats-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "library"
        self.inbox = self.root / "Inbox"
        scripts = self.root / "scripts"
        self.inbox.mkdir(parents=True)
        scripts.mkdir()

        shutil.copy2(REPOSITORY_ROOT / "templates/main.typ", self.root / "main.typ")
        shutil.copy2(
            REPOSITORY_ROOT / "templates/library.bib", self.root / "library.bib"
        )
        validator = scripts / "validate-library.sh"
        shutil.copy2(REPOSITORY_ROOT / "scripts/validate-library.sh", validator)
        validator.chmod(0o755)
        shutil.copytree(REPOSITORY_ROOT / "paperlib", self.root / "paperlib")

    def run_manifest(
        self, manifest: dict[str, object], *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        manifest_path = self.root / "intake.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return subprocess.run(
            [
                sys.executable,
                str(INTAKE_ENGINE),
                "--root",
                str(self.root),
                "--manifest",
                str(manifest_path),
                *arguments,
            ],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_status(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(INTAKE_ENGINE),
                "status",
                "--root",
                str(self.root),
                "--pending",
                *arguments,
            ],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    @staticmethod
    def manifest(items: list[dict[str, object]]) -> dict[str, object]:
        return {
            "topic": {
                "path": "PeripheralEsoteric/DigitalBooks",
                "headings": ["Peripheral & Esoteric", "Digital Books"],
            },
            "items": items,
        }

    @staticmethod
    def item(
        source_file: str,
        canonical_filename: str,
        citation_key: str,
        title: str,
        entry_type: str = "book",
    ) -> dict[str, object]:
        fields = {
            "author": "Example, Ada",
            "date": "2026",
        }
        if entry_type == "book":
            fields["publisher"] = "Example Press"
        else:
            fields["journaltitle"] = "Journal of Synthetic Examples"
        return {
            "source_file": source_file,
            "canonical_filename": canonical_filename,
            "citation_key": citation_key,
            "entry_type": entry_type,
            "title": title,
            "fields": fields,
        }

    def write_pdf(self, destination: Path) -> None:
        typst = shutil.which("typst")
        if not typst:
            self.skipTest("typst is required to generate the PDF fixture")
        source = self.root / "fixture.typ"
        source.write_text("= Synthetic PDF fixture\n", encoding="utf-8")
        result = subprocess.run(
            [typst, "compile", str(source), str(destination)],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @staticmethod
    def write_epub(destination: Path) -> None:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(mimetype, b"application/epub+zip")
            archive.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
            )
            archive.writestr(
                "OEBPS/content.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="id"
  xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:synthetic-epub</dc:identifier>
    <dc:title>Synthetic EPUB fixture</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest/>
  <spine/>
</package>
""",
            )

    @staticmethod
    def write_mobi(destination: Path) -> None:
        data = bytearray(128)
        data[:14] = b"Synthetic MOBI"
        data[60:68] = b"BOOKMOBI"
        data[76:78] = (1).to_bytes(2, byteorder="big")
        data[78:82] = (88).to_bytes(4, byteorder="big")
        data[88:104] = b"Synthetic record"
        destination.write_bytes(data)

    def test_transactional_apply_supports_pdf_epub_and_mobi(self) -> None:
        pdf = self.inbox / "incoming.pdf"
        epub = self.inbox / "incoming.epub"
        mobi = self.inbox / "incoming.mobi"
        self.write_pdf(pdf)
        self.write_epub(epub)
        self.write_mobi(mobi)

        items = [
            self.item(
                "Inbox/incoming.pdf",
                "SyntheticPdfGuide.pdf",
                "example2026pdfguide",
                "Synthetic PDF guide",
                entry_type="article",
            ),
            self.item(
                "Inbox/incoming.epub",
                "SyntheticEpubGuide.epub",
                "example2026epubguide",
                "Synthetic EPUB guide",
            ),
            self.item(
                "Inbox/incoming.mobi",
                "SyntheticMobiGuide.mobi",
                "example2026mobiguide",
                "Synthetic MOBI guide",
            ),
        ]
        manifest = self.manifest(items)
        original_bib = (self.root / "library.bib").read_bytes()
        original_main = (self.root / "main.typ").read_bytes()

        dry_run = self.run_manifest(manifest)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("DRY RUN — no files changed", dry_run.stdout)
        self.assertIn("FORMAT PDF", dry_run.stdout)
        self.assertIn("FORMAT EPUB", dry_run.stdout)
        self.assertIn("FORMAT MOBI", dry_run.stdout)
        self.assertEqual((self.root / "library.bib").read_bytes(), original_bib)
        self.assertEqual((self.root / "main.typ").read_bytes(), original_main)
        self.assertTrue(pdf.exists())
        self.assertTrue(epub.exists())
        self.assertTrue(mobi.exists())

        applied = self.run_manifest(manifest, "--apply")
        self.assertEqual(
            applied.returncode,
            0,
            f"stdout:\n{applied.stdout}\nstderr:\n{applied.stderr}",
        )
        self.assertIn("APPLY PLAN — changes begin after this summary", applied.stdout)
        self.assertNotIn("DRY RUN — no files changed", applied.stdout)

        destinations = [
            "Library/PeripheralEsoteric/DigitalBooks/SyntheticPdfGuide.pdf",
            "Library/PeripheralEsoteric/DigitalBooks/SyntheticEpubGuide.epub",
            "Library/PeripheralEsoteric/DigitalBooks/SyntheticMobiGuide.mobi",
        ]
        for source in (pdf, epub, mobi):
            self.assertFalse(source.exists())
        for relative in destinations:
            self.assertTrue((self.root / relative).is_file())

        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        for relative in destinations:
            self.assertIn(f"= {{{relative}}}", bibliography)
            self.assertIn(f'#link("{relative}")', catalog)
        self.assertIn("@article{example2026pdfguide,", bibliography)
        self.assertIn("@book{example2026epubguide,", bibliography)
        self.assertIn("@book{example2026mobiguide,", bibliography)
        self.assertGreater((self.root / "PaperLibrary.pdf").stat().st_size, 0)

        multiline_catalog = catalog
        for relative in destinations:
            multiline_catalog = multiline_catalog.replace(
                f'#link("{relative}")',
                f'#link(\n    "{relative}",\n  )',
            )
        (self.root / "main.typ").write_text(multiline_catalog, encoding="utf-8")
        validation = subprocess.run(
            [str(self.root / "scripts/validate-library.sh")],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_pending_item_requires_no_local_document(self) -> None:
        item = {
            "pending": True,
            "citation_key": "example2026pendingpaper",
            "entry_type": "article",
            "title": "Synthetic pending paper",
            "fields": {
                "author": "Example, Ada and Researcher, Ben",
                "journaltitle": "Journal of Synthetic Examples",
                "date": "2026",
                "doi": "10.0000/pending-example",
            },
        }
        second_item = {
            "pending": True,
            "citation_key": "researcher2025pendingstudy",
            "entry_type": "article",
            "title": "Another synthetic pending study",
            "fields": {
                "author": "Researcher, Ben",
                "journaltitle": "Journal of Synthetic Examples",
                "date": "2025",
                "doi": "10.0000/another-pending-example",
            },
        }
        manifest = self.manifest([item, second_item])

        dry_run = self.run_manifest(manifest)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("FILE  PENDING DOWNLOAD", dry_run.stdout)
        self.assertIn(
            "DIR   Library/PeripheralEsoteric/DigitalBooks (create if missing)",
            dry_run.stdout,
        )
        self.assertNotIn("MOVE  ", dry_run.stdout)
        self.assertFalse((self.root / "Library").exists())

        applied = self.run_manifest(manifest, "--apply")
        self.assertEqual(
            applied.returncode,
            0,
            f"stdout:\n{applied.stdout}\nstderr:\n{applied.stderr}",
        )

        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        self.assertIn("@article{example2026pendingpaper,", bibliography)
        self.assertIn("@article{researcher2025pendingstudy,", bibliography)
        self.assertIn("file         = {}", bibliography)
        self.assertIn("Synthetic pending paper", catalog)
        self.assertIn("@example2026pendingpaper", catalog)
        self.assertNotIn("download pending", catalog.casefold())
        self.assertNotIn("#link(", catalog)
        self.assertTrue(
            (self.root / "Library/PeripheralEsoteric/DigitalBooks").is_dir()
        )
        self.assertIn("0 library files, 2 pending downloads", applied.stdout)
        self.assertGreater((self.root / "PaperLibrary.pdf").stat().st_size, 0)

        (self.root / "main.typ").write_text(
            catalog.replace(
                "@example2026pendingpaper",
                "@example2026pendingpaper #text[(download pending)]",
                1,
            ),
            encoding="utf-8",
        )
        validation = subprocess.run(
            [str(self.root / "scripts/validate-library.sh")],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(validation.returncode, 1)
        self.assertIn(
            "catalog contains deprecated visible download-pending labels",
            validation.stderr,
        )

    def test_attaches_download_to_existing_pending_record(self) -> None:
        pending_item = {
            "pending": True,
            "citation_key": "editor2026pendingbook",
            "entry_type": "book",
            "title": "Synthetic edited pending book",
            "fields": {
                "editor": "Editor, Erin",
                "publisher": "Example Press",
                "date": "2026",
                "isbn": "978-0-00-000000-1",
            },
        }
        pending_result = self.run_manifest(self.manifest([pending_item]), "--apply")
        self.assertEqual(pending_result.returncode, 0, pending_result.stderr)

        status = self.run_status("--json")
        self.assertEqual(status.returncode, 0, status.stderr)
        status_records = json.loads(status.stdout)
        self.assertEqual(len(status_records), 1)
        self.assertEqual(status_records[0]["citation_key"], "editor2026pendingbook")
        self.assertEqual(
            status_records[0]["expected_directory"],
            "Library/PeripheralEsoteric/DigitalBooks",
        )

        epub = self.inbox / "edited-book.epub"
        self.write_epub(epub)
        attachment = {
            "attach": True,
            "citation_key": "editor2026pendingbook",
            "source_file": "Inbox/edited-book.epub",
            "canonical_filename": "SyntheticEditedPendingBook.epub",
        }
        manifest = self.manifest([attachment])
        dry_run = self.run_manifest(manifest)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("ATTACH Inbox/edited-book.epub", dry_run.stdout)
        self.assertIn("UPDATE 1 pending record", dry_run.stdout)

        applied = self.run_manifest(manifest, "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        destination = (
            self.root / "Library/PeripheralEsoteric/DigitalBooks/"
            "SyntheticEditedPendingBook.epub"
        )
        self.assertTrue(destination.is_file())
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        relative = destination.relative_to(self.root).as_posix()
        self.assertIn(f"file      = {{{relative}}}", bibliography)
        self.assertIn(f'#link("{relative}")', catalog)
        self.assertIn("editor    = {Editor, Erin}", bibliography)
        self.assertEqual(json.loads(self.run_status("--json").stdout), [])

    def test_pending_status_accepts_an_initialized_empty_library(self) -> None:
        result = self.run_status("--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_editor_only_book_is_valid_metadata(self) -> None:
        item = {
            "pending": True,
            "citation_key": "editor2024handbook",
            "entry_type": "book",
            "title": "Synthetic editor-only handbook",
            "fields": {
                "editor": "Editor, Erin and Curator, Casey",
                "publisher": "Example Press",
                "date": "2024",
            },
        }
        result = self.run_manifest(self.manifest([item]), "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        self.assertIn("editor    = {Editor, Erin and Curator, Casey}", bibliography)

    def test_bib_title_must_describe_the_display_title(self) -> None:
        item = {
            "pending": True,
            "citation_key": "example2026titlemismatch",
            "entry_type": "article",
            "title": "Synthetic Display Title",
            "bib_title": "A Different Work",
            "fields": {"author": "Example, Ada", "date": "2026"},
        }

        result = self.run_manifest(self.manifest([item]))

        self.assertEqual(result.returncode, 2)
        self.assertIn("bib_title must represent the same title", result.stderr)

    def test_intake_refuses_to_run_while_library_lock_is_held(self) -> None:
        lock_path = self.root / ".paper-library.lock"
        with lock_path.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            item = {
                "pending": True,
                "citation_key": "example2026locked",
                "entry_type": "article",
                "title": "Synthetic locked record",
                "fields": {"author": "Example, Ada", "date": "2026"},
            }
            result = self.run_manifest(self.manifest([item]), "--lock-timeout", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("library is busy", result.stderr)

    def test_pending_item_rejects_file_properties(self) -> None:
        item = {
            "pending": True,
            "source_file": "Inbox/not-needed.pdf",
            "canonical_filename": "NotNeeded.pdf",
            "citation_key": "example2026pendingconflict",
            "entry_type": "article",
            "title": "Synthetic pending conflict",
            "fields": {
                "author": "Example, Ada",
                "journaltitle": "Journal of Synthetic Examples",
                "date": "2026",
            },
        }

        result = self.run_manifest(self.manifest([item]))

        self.assertEqual(result.returncode, 2)
        self.assertIn("is pending and must omit file properties", result.stderr)

    def test_public_audit_rejects_pending_catalog_citations_in_template(self) -> None:
        audit_root = self.root / "audit-fixture"
        scripts = audit_root / "scripts"
        templates = audit_root / "templates"
        scripts.mkdir(parents=True)
        templates.mkdir()
        auditor = scripts / "public-repo"
        shutil.copy2(REPOSITORY_ROOT / "scripts/public-repo", auditor)
        (templates / "library.bib").write_text(
            "% Empty sanitized bibliography template.\n",
            encoding="utf-8",
        )
        (templates / "main.typ").write_text(
            '#let bibliography-file = "library.bib"\n'
            "- Synthetic pending title @example2026private\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(auditor), "audit"],
            cwd=audit_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "catalog template contains a real citation: templates/main.typ",
            result.stderr,
        )

    def test_legacy_pdf_manifest_aliases_remain_supported(self) -> None:
        pdf = self.inbox / "legacy.pdf"
        self.write_pdf(pdf)
        item = self.item(
            "Inbox/legacy.pdf",
            "LegacyPdfManifest.pdf",
            "example2026legacypdf",
            "Legacy PDF manifest",
            entry_type="article",
        )
        item["source_pdf"] = item.pop("source_file")
        manifest = self.manifest([])
        manifest["papers"] = [item]
        del manifest["items"]

        result = self.run_manifest(manifest)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FORMAT PDF", result.stdout)
        self.assertTrue(pdf.exists())

    def test_epub_requires_the_ocf_mimetype_first(self) -> None:
        invalid = self.inbox / "invalid.epub"
        with zipfile.ZipFile(invalid, "w") as archive:
            archive.writestr("META-INF/container.xml", "<container/>")
            archive.writestr("mimetype", "application/epub+zip")
        manifest = self.manifest(
            [
                self.item(
                    "Inbox/invalid.epub",
                    "InvalidEpub.epub",
                    "example2026invalidepub",
                    "Invalid EPUB",
                )
            ]
        )

        result = self.run_manifest(manifest)

        self.assertEqual(result.returncode, 2)
        self.assertIn("EPUB does not begin with a mimetype entry", result.stderr)

    def test_mobi_requires_the_bookmobi_palmdb_signature(self) -> None:
        invalid = self.inbox / "invalid.mobi"
        invalid.write_bytes(b"not a MOBI file")
        manifest = self.manifest(
            [
                self.item(
                    "Inbox/invalid.mobi",
                    "InvalidMobi.mobi",
                    "example2026invalidmobi",
                    "Invalid MOBI",
                )
            ]
        )

        result = self.run_manifest(manifest)

        self.assertEqual(result.returncode, 2)
        self.assertIn("MOBI PalmDB signature", result.stderr)

    def test_intake_rejects_format_changing_renames(self) -> None:
        epub = self.inbox / "source.epub"
        self.write_epub(epub)
        manifest = self.manifest(
            [
                self.item(
                    "Inbox/source.epub",
                    "WrongExtension.mobi",
                    "example2026wrongextension",
                    "Wrong extension",
                )
            ]
        )

        result = self.run_manifest(manifest)

        self.assertEqual(result.returncode, 2)
        self.assertIn("must keep the source format: .epub", result.stderr)

    def test_catalog_embeds_the_configured_korean_fallback(self) -> None:
        typst = shutil.which("typst")
        pdffonts = shutil.which("pdffonts")
        if not typst or not pdffonts:
            self.skipTest("typst and pdffonts are required for the font smoke test")

        available_fonts = subprocess.run(
            [typst, "fonts"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        available_font_names = set(available_fonts.stdout.splitlines())
        if "NanumGothicCoding" not in available_font_names:
            self.skipTest("NanumGothicCoding is not available to Typst")

        main_path = self.root / "main.typ"
        main_text = main_path.read_text(encoding="utf-8")
        self.assertIn(
            '#let catalog-fonts = ("New Computer Modern Sans", korean-font)',
            main_text,
        )
        marker = (
            "// The intake engine inserts topic headings and catalog citations here."
        )
        self.assertIn(marker, main_text)
        main_path.write_text(
            main_text.replace(
                marker,
                "Latin font smoke test.\n\n한국어 글꼴 확인.",
                1,
            ),
            encoding="utf-8",
        )
        output = self.root / "font-smoke.pdf"

        compilation = subprocess.run(
            [typst, "compile", str(main_path), str(output)],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(compilation.returncode, 0, compilation.stderr)

        embedded_fonts = subprocess.run(
            [pdffonts, str(output)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(embedded_fonts.returncode, 0, embedded_fonts.stderr)
        font_report = embedded_fonts.stdout.replace(" ", "")
        self.assertIn("NanumGothicCoding", font_report)
        if "New Computer Modern Sans" in available_font_names:
            self.assertIn("NewCMSans", font_report)


if __name__ == "__main__":
    unittest.main()
