from __future__ import annotations

from datetime import date
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
        shutil.copytree(REPOSITORY_ROOT / "styles", self.root / "styles")
        validator = scripts / "validate-library.sh"
        shutil.copy2(REPOSITORY_ROOT / "scripts/validate-library.sh", validator)
        validator.chmod(0o755)
        shutil.copytree(REPOSITORY_ROOT / "paperlib", self.root / "paperlib")

    def run_manifest(
        self, manifest: dict[str, object], *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_manifests([manifest], *arguments)

    def run_manifests(
        self, manifests: list[dict[str, object]], *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        manifest_arguments: list[str] = []
        for index, manifest in enumerate(manifests):
            manifest_path = self.root / f"intake-{index}.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest_arguments.extend(["--manifest", str(manifest_path)])
        return subprocess.run(
            [
                sys.executable,
                str(INTAKE_ENGINE),
                "--root",
                str(self.root),
                *manifest_arguments,
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

    def run_topics(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(INTAKE_ENGINE),
                "topics",
                "--root",
                str(self.root),
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
                "path": "Literature/DigitalBooks",
                "headings": ["Literature", "Digital Books"],
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
            "Library/Literature/DigitalBooks/SyntheticPdfGuide.pdf",
            "Library/Literature/DigitalBooks/SyntheticEpubGuide.epub",
            "Library/Literature/DigitalBooks/SyntheticMobiGuide.mobi",
        ]
        for source in (pdf, epub, mobi):
            self.assertFalse(source.exists())
        for relative in destinations:
            self.assertTrue((self.root / relative).is_file())

        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        today = date.today()
        expected_update = f"{today.strftime('%B')} {today.day}, {today.year}"
        self.assertIn(
            f'#let catalog-updated = "{expected_update}"',
            catalog,
        )
        for relative in destinations:
            self.assertIn(f"= {{{relative}}}", bibliography)
            self.assertIn(f'#link("{relative}")', catalog)
        for item in items:
            self.assertIn(
                f"#reference-title(<{item['citation_key']}>)",
                catalog,
            )
        self.assertEqual(catalog.count("#reference-title("), 3)
        self.assertIn(r"\[PDF\]", catalog)
        self.assertIn(r"\[EPUB\]", catalog)
        self.assertIn(r"\[MOBI\]", catalog)
        self.assertIn("@article{example2026pdfguide,", bibliography)
        self.assertIn("@book{example2026epubguide,", bibliography)
        self.assertIn("@book{example2026mobiguide,", bibliography)
        self.assertGreater((self.root / "Catalog.pdf").stat().st_size, 0)

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

    def test_multi_topic_batch_and_private_provenance_report(self) -> None:
        pdf = self.inbox / "study.pdf"
        epub = self.inbox / "handbook.epub"
        unrelated = self.inbox / "unrelated.mobi"
        self.write_pdf(pdf)
        self.write_epub(epub)
        self.write_mobi(unrelated)

        study = self.item(
            "Inbox/study.pdf",
            "SyntheticFoundationalStudy.pdf",
            "example2026foundationalstudy",
            "Synthetic foundational study",
            entry_type="article",
        )
        study["metadata_sources"] = [
            "https://doi.org/10.0000/synthetic-study",
            "https://api.crossref.org/works/10.0000%2Fsynthetic-study",
        ]
        study["fields"]["doi"] = "10.0000/synthetic-study"
        first = {
            "topic": {
                "path": "Perspectives/PhilosophyOfScience",
                "headings": ["Perspectives", "Philosophy of Science"],
            },
            "items": [study],
        }
        second = self.manifest(
            [
                self.item(
                    "Inbox/handbook.epub",
                    "SyntheticDigitalHandbook.epub",
                    "example2026digitalhandbook",
                    "Synthetic digital handbook",
                )
            ]
        )
        report = self.root / "reports/batch.json"

        dry_run = self.run_manifests([first, second], "--report-json", str(report))
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("BATCH 2 manifest(s)", dry_run.stdout)
        self.assertTrue(pdf.is_file())
        self.assertTrue(epub.is_file())
        dry_report = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(dry_report["status"], "dry-run")
        today = date.today()
        expected_update = f"{today.strftime('%B')} {today.day}, {today.year}"
        self.assertEqual(dry_report["catalog_updated"], expected_update)
        self.assertEqual(dry_report["summary"]["manifests"], 2)
        self.assertEqual(dry_report["summary"]["topics"], 2)
        self.assertEqual(
            dry_report["topics"][0]["items"][0]["metadata_sources"],
            study["metadata_sources"],
        )
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)

        refused = self.run_manifests([first, second], "--report-json", str(report))
        self.assertEqual(refused.returncode, 2)
        self.assertIn("refusing to overwrite existing report", refused.stderr)

        applied = self.run_manifests(
            [first, second],
            "--apply",
            "--report-json",
            str(report),
            "--force-report",
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Applied 2 item(s) across 2 topic(s)", applied.stdout)
        self.assertFalse(pdf.exists())
        self.assertFalse(epub.exists())
        self.assertTrue(unrelated.is_file())
        self.assertTrue(
            (
                self.root / "Library/Perspectives/PhilosophyOfScience/"
                "SyntheticFoundationalStudy.pdf"
            ).is_file()
        )
        self.assertTrue(
            (
                self.root / "Library/Literature/DigitalBooks/"
                "SyntheticDigitalHandbook.epub"
            ).is_file()
        )
        report_data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(report_data["status"], "applied")
        self.assertEqual(report_data["validation"], "passed")
        self.assertEqual(report_data["catalog_build"], "passed")
        self.assertEqual(report_data["summary"]["items"], 2)
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        self.assertNotIn("metadata_sources", bibliography)
        self.assertNotIn("api.crossref.org", bibliography)
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        self.assertIn("== Philosophy of Science", catalog)

        topics_result = self.run_topics("--json")
        self.assertEqual(topics_result.returncode, 0, topics_result.stderr)
        topics = json.loads(topics_result.stdout)
        self.assertEqual(
            [topic["path"] for topic in topics],
            [
                "Literature/DigitalBooks",
                "Perspectives/PhilosophyOfScience",
            ],
        )
        self.assertEqual(
            topics[0],
            {
                "path": "Literature/DigitalBooks",
                "headings": ["Literature", "Digital Books"],
                "records": 1,
                "local_files": 1,
                "pending": 0,
                "directory": "Library/Literature/DigitalBooks",
            },
        )

    def test_report_base_keeps_dry_run_and_applied_reports(self) -> None:
        item = {
            "pending": True,
            "citation_key": "example2026pairedreport",
            "entry_type": "article",
            "title": "Synthetic paired report",
            "fields": {"author": "Example, Ada", "date": "2026"},
        }
        manifest = self.manifest([item])
        report_base = self.root / "reports/paired-intake"

        dry_run = self.run_manifest(manifest, "--report-base", str(report_base))
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        dry_path = self.root / "reports/paired-intake.dry-run.json"
        applied_path = self.root / "reports/paired-intake.applied.json"
        self.assertTrue(dry_path.is_file())
        self.assertFalse(applied_path.exists())
        self.assertEqual(
            json.loads(dry_path.read_text(encoding="utf-8"))["status"], "dry-run"
        )

        repeated_dry_run = self.run_manifest(
            manifest, "--report-base", str(report_base)
        )
        self.assertEqual(repeated_dry_run.returncode, 2)
        self.assertIn("refusing to overwrite existing report", repeated_dry_run.stderr)

        applied = self.run_manifest(
            manifest, "--apply", "--report-base", str(report_base)
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue(dry_path.is_file())
        self.assertTrue(applied_path.is_file())
        self.assertEqual(
            json.loads(applied_path.read_text(encoding="utf-8"))["status"],
            "applied",
        )

    def test_multi_topic_preflight_rejects_cross_manifest_duplicate(self) -> None:
        original_bib = (self.root / "library.bib").read_bytes()
        first_item = {
            "pending": True,
            "citation_key": "example2026firstduplicate",
            "entry_type": "article",
            "title": "Synthetic duplicate work",
            "fields": {"author": "Example, Ada", "date": "2026"},
        }
        second_item = {
            "pending": True,
            "citation_key": "researcher2026secondduplicate",
            "entry_type": "article",
            "title": "Synthetic duplicate work",
            "fields": {"author": "Researcher, Ben", "date": "2026"},
        }

        result = self.run_manifests(
            [self.manifest([first_item]), self.manifest([second_item])], "--apply"
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate normalized title", result.stderr)
        self.assertEqual((self.root / "library.bib").read_bytes(), original_bib)
        self.assertFalse((self.root / "Library").exists())

    def test_multi_topic_preflight_rejects_reused_source_file(self) -> None:
        source = self.inbox / "shared.pdf"
        self.write_pdf(source)
        first = self.item(
            "Inbox/shared.pdf",
            "SyntheticFirstStudy.pdf",
            "example2026firststudy",
            "Synthetic first study",
            entry_type="article",
        )
        second = self.item(
            "Inbox/shared.pdf",
            "SyntheticSecondStudy.pdf",
            "researcher2026secondstudy",
            "Synthetic second study",
            entry_type="article",
        )

        result = self.run_manifests(
            [self.manifest([first]), self.manifest([second])], "--apply"
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("source file appears in more than one manifest", result.stderr)
        self.assertTrue(source.is_file())
        self.assertFalse((self.root / "Library").exists())

    def test_topic_heading_identity_is_checked_during_dry_run(self) -> None:
        item = {
            "pending": True,
            "citation_key": "example2026headingcheck",
            "entry_type": "article",
            "title": "Synthetic heading check",
            "fields": {"author": "Example, Ada", "date": "2026"},
        }
        manifest = {
            "topic": {
                "path": "Perspectives/PhilosophyOfScience",
                "headings": ["Perspectives", "Philosophy of Physics"],
            },
            "items": [item],
        }

        result = self.run_manifest(manifest)

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "must match topic.path component PhilosophyOfScience", result.stderr
        )

    def test_intake_requires_the_catalog_updated_marker(self) -> None:
        main_path = self.root / "main.typ"
        main_text = main_path.read_text(encoding="utf-8")
        main_path.write_text(
            main_text.replace('#let catalog-updated = ""\n', "", 1),
            encoding="utf-8",
        )
        item = {
            "pending": True,
            "citation_key": "example2026missingupdatedmarker",
            "entry_type": "article",
            "title": "Synthetic missing update marker",
            "fields": {"author": "Example, Ada", "date": "2026"},
        }

        result = self.run_manifest(self.manifest([item]))

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "must define exactly one quoted #let catalog-updated", result.stderr
        )

    def test_metadata_sources_require_safe_web_urls(self) -> None:
        item = {
            "pending": True,
            "citation_key": "example2026metadatasource",
            "entry_type": "article",
            "title": "Synthetic metadata source",
            "fields": {"author": "Example, Ada", "date": "2026"},
            "metadata_sources": ["file:///tmp/private-record.json"],
        }

        result = self.run_manifest(self.manifest([item]))

        self.assertEqual(result.returncode, 2)
        self.assertIn("must be an HTTP(S) URL", result.stderr)

    def test_report_rejects_a_symlinked_parent(self) -> None:
        item = {
            "pending": True,
            "citation_key": "example2026symlinkreport",
            "entry_type": "article",
            "title": "Synthetic symlink report",
            "fields": {"author": "Example, Ada", "date": "2026"},
        }
        external_reports = self.root.parent / "external-reports"
        external_reports.mkdir()
        (self.root / "reports").symlink_to(external_reports, target_is_directory=True)

        result = self.run_manifest(
            self.manifest([item]),
            "--report-json",
            str(self.root / "reports/intake.json"),
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must not use a symlinked path component", result.stderr)
        self.assertEqual(list(external_reports.iterdir()), [])

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
            "DIR   Library/Literature/DigitalBooks (create if missing)",
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
        self.assertEqual(catalog.count("#reference-title("), 2)
        self.assertTrue((self.root / "Library/Literature/DigitalBooks").is_dir())
        self.assertIn("0 library files, 2 pending downloads", applied.stdout)
        self.assertGreater((self.root / "Catalog.pdf").stat().st_size, 0)

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
                "isbn": "0-000-00000-0",
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
            "Library/Literature/DigitalBooks",
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
            self.root / "Library/Literature/DigitalBooks/"
            "SyntheticEditedPendingBook.epub"
        )
        self.assertTrue(destination.is_file())
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        relative = destination.relative_to(self.root).as_posix()
        self.assertIn(f"file      = {{{relative}}}", bibliography)
        self.assertIn(f'#link("{relative}")', catalog)
        self.assertIn(
            "#reference-title(<editor2026pendingbook>)[\n"
            '    #text("Synthetic edited pending book")',
            catalog,
        )
        self.assertIn(r"\[EPUB\]", catalog)
        self.assertIn("editor    = {Editor, Erin}", bibliography)
        self.assertEqual(json.loads(self.run_status("--json").stdout), [])

    def test_pending_status_accepts_an_initialized_empty_library(self) -> None:
        result = self.run_status("--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_topics_accepts_an_initialized_empty_library(self) -> None:
        result = self.run_topics("--json")

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

    def test_subtitle_is_stored_separately_and_shown_in_catalog(self) -> None:
        first_item = {
            "pending": True,
            "citation_key": "example2026subtitle",
            "entry_type": "book",
            "title": "Synthetic collected work",
            "fields": {
                "author": "Example, Ada",
                "subtitle": "The first proper subtitle",
                "publisher": "Example Press",
                "date": "2026",
            },
        }
        second_item = {
            "pending": True,
            "citation_key": "example2026subtitleb",
            "entry_type": "book",
            "title": "Synthetic collected work",
            "fields": {
                "author": "Example, Ada",
                "subtitle": "The second proper subtitle",
                "publisher": "Example Press",
                "date": "2026",
            },
        }

        result = self.run_manifest(self.manifest([first_item, second_item]), "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        self.assertEqual(
            bibliography.count("title     = {Synthetic collected work}"), 2
        )
        self.assertIn("subtitle  = {The first proper subtitle}", bibliography)
        self.assertIn("subtitle  = {The second proper subtitle}", bibliography)
        self.assertIn(
            '#text("Synthetic collected work: The first proper subtitle")',
            catalog,
        )
        self.assertIn(
            '#text("Synthetic collected work: The second proper subtitle")',
            catalog,
        )
        status = json.loads(self.run_status("--json").stdout)
        self.assertEqual(
            {record["title"] for record in status},
            {
                "Synthetic collected work: The first proper subtitle",
                "Synthetic collected work: The second proper subtitle",
            },
        )

    def test_numbered_series_uses_structured_catalog_label(self) -> None:
        items = []
        for number, key in (
            ("1", "example2026seriesone"),
            ("2", "example2026seriestwo"),
        ):
            items.append(
                {
                    "pending": True,
                    "citation_key": key,
                    "entry_type": "book",
                    "title": "A Repeated Volume Title",
                    "fields": {
                        "author": "Example, Ada",
                        "series": "Synthetic Cycle",
                        "number": number,
                        "publisher": "Example Press",
                        "date": "2026",
                    },
                }
            )

        result = self.run_manifest(self.manifest(items), "--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        self.assertEqual(bibliography.count("title     = {A Repeated Volume Title}"), 2)
        self.assertEqual(bibliography.count("series    = {Synthetic Cycle}"), 2)
        self.assertIn('#text("Synthetic Cycle #1: A Repeated Volume Title")', catalog)
        self.assertIn('#text("Synthetic Cycle #2: A Repeated Volume Title")', catalog)

    def test_isbn_is_normalized_and_deduplicated_across_isbn10_and_isbn13(self) -> None:
        first_item = {
            "pending": True,
            "citation_key": "example2026isbnfirst",
            "entry_type": "book",
            "title": "Synthetic ISBN first edition",
            "fields": {
                "author": "Example, Ada",
                "publisher": "Example Press",
                "date": "2026",
                "isbn": "ISBN-10: 0-000-00000-0",
            },
        }
        applied = self.run_manifest(self.manifest([first_item]), "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        self.assertIn("isbn      = {9780000000002}", bibliography)

        duplicate_item = {
            "pending": True,
            "citation_key": "example2026isbnsecond",
            "entry_type": "book",
            "title": "Synthetic ISBN duplicate edition",
            "fields": {
                "author": "Example, Ada",
                "publisher": "Example Press",
                "date": "2026",
                "isbn": "978-0-000-00000-2",
            },
        }
        duplicate = self.run_manifest(self.manifest([duplicate_item]))
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("duplicate ISBN: 9780000000002", duplicate.stderr)

        invalid_item = {
            "pending": True,
            "citation_key": "example2026invalidisbn",
            "entry_type": "book",
            "title": "Synthetic invalid ISBN",
            "fields": {
                "author": "Example, Ada",
                "publisher": "Example Press",
                "date": "2026",
                "isbn": "978-0-000-00000-3",
            },
        }
        invalid = self.run_manifest(self.manifest([invalid_item]))
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid ISBN", invalid.stderr)

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

    @staticmethod
    def recording_manifest(
        path: str, headings: list[str], items: list[dict[str, object]]
    ) -> dict[str, object]:
        return {"topic": {"path": path, "headings": headings}, "items": items}

    @staticmethod
    def film_item(citation_key: str, date: str, **fields: str) -> dict[str, object]:
        return {
            "pending": True,
            "citation_key": citation_key,
            "entry_type": "movie",
            "title": "Synthetic Horizon",
            "fields": {
                "author": "Director, Dana",
                "date": date,
                "publisher": "Example Pictures",
                "type": "Film",
                **fields,
            },
        }

    def test_albums_and_films_link_their_url_while_the_path_is_pending(self) -> None:
        album_url = "https://music.example.test/album/synthetic?list=1&x=a%20b"
        film_url = "https://watch.example.test/title/synthetic-horizon"
        album = {
            "pending": True,
            "citation_key": "example2026syntheticsessions",
            "entry_type": "audio",
            "title": "Synthetic Sessions",
            "metadata_sources": [
                "https://musicbrainz.org/release-group/"
                "00000000-0000-4000-8000-000000000001"
            ],
            "fields": {
                "author": "{Example Ensemble}",
                "date": "2026-01-15",
                "publisher": "Example Records",
                "type": "Album",
                "musicbrainz": "https://musicbrainz.org/release-group/"
                "00000000-0000-4000-8000-00000000000A",
                "url": album_url,
            },
        }
        song = {
            "pending": True,
            "citation_key": "example2026edgesynthesis",
            "entry_type": "audio",
            "title": "To the Edge of Synthesis",
            "fields": {
                "author": "{Example Ensemble}",
                "booktitle": "Synthetic Sessions",
                "date": "2026-01-15",
                "publisher": "Example Records",
                "type": "Song",
                "musicbrainz": "https://musicbrainz.org/recording/"
                "00000000-0000-4000-8000-00000000000B",
                "url": "https://music.example.test/track/edge",
            },
        }
        film = self.film_item(
            "director2026synthetichorizon",
            "2026-03-01",
            imdb="https://www.imdb.com/title/tt0000000/?ref_=example",
            wikidata="q4115189",
            url=film_url,
        )
        manifests = [
            self.recording_manifest(
                "Music/JazzBlues", ["Music", "Jazz & Blues"], [album, song]
            ),
            self.recording_manifest(
                "Film/ScienceFiction", ["Film", "Science Fiction"], [film]
            ),
        ]

        dry_run = self.run_manifests(manifests)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertEqual(dry_run.stdout.count("FILE  PENDING LOCAL PATH"), 3)
        self.assertIn(f"LINK  [URL] {film_url}", dry_run.stdout)
        self.assertIn("ID    imdb tt0000000", dry_run.stdout)
        self.assertIn("ID    wikidata Q4115189", dry_run.stdout)
        self.assertIn(
            "ID    musicbrainz 00000000-0000-4000-8000-00000000000a", dry_run.stdout
        )
        self.assertIn(
            "ID    musicbrainz 00000000-0000-4000-8000-00000000000b", dry_run.stdout
        )

        applied = self.run_manifests(manifests, "--apply")
        self.assertEqual(
            applied.returncode,
            0,
            f"stdout:\n{applied.stdout}\nstderr:\n{applied.stderr}",
        )
        bibliography = (self.root / "library.bib").read_text(encoding="utf-8")
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        self.assertIn("@audio{example2026syntheticsessions,", bibliography)
        self.assertIn("@movie{director2026synthetichorizon,", bibliography)
        self.assertRegex(bibliography, r"imdb\s+= \{tt0000000\}")
        self.assertRegex(bibliography, r"wikidata\s+= \{Q4115189\}")
        self.assertRegex(
            bibliography, r"musicbrainz\s+= \{00000000-0000-4000-8000-00000000000a\}"
        )
        self.assertEqual(bibliography.count("= {}"), 3)
        self.assertIn("@audio{example2026edgesynthesis,", bibliography)
        self.assertRegex(bibliography, r"booktitle\s+= \{Synthetic Sessions\}")
        self.assertIn(
            "#reference-title(<director2026synthetichorizon>)[\n"
            '    #text("Synthetic Horizon")\n'
            f'  ] #h(0pt) #link("{film_url}")[\n'
            '    #text(size: 8pt, weight: "bold")[\\[URL\\]]\n'
            "  ] @director2026synthetichorizon",
            catalog,
        )
        self.assertIn(f'#link("{album_url}")[', catalog)
        self.assertEqual(catalog.count(r"\[URL\]"), 3)
        self.assertTrue((self.root / "Library/Music/JazzBlues").is_dir())
        self.assertTrue((self.root / "Library/Film/ScienceFiction").is_dir())
        self.assertIn("0 library files, 3 pending downloads", applied.stdout)

        status = {
            record["citation_key"]: record
            for record in json.loads(self.run_status("--json").stdout)
        }
        self.assertEqual(status["director2026synthetichorizon"]["url"], film_url)
        self.assertEqual(status["example2026syntheticsessions"]["entry_type"], "audio")

    def test_recording_identity_allows_shared_titles_but_rejects_duplicates(
        self,
    ) -> None:
        novel = {
            "pending": True,
            "citation_key": "writer2026synthetichorizon",
            "entry_type": "book",
            "title": "Synthetic Horizon",
            "fields": {
                "author": "Writer, Wren",
                "publisher": "Example Press",
                "date": "2026",
                "url": "https://books.example.test/synthetic-horizon",
            },
        }
        soundtrack = {
            "pending": True,
            "citation_key": "director2026synthetichorizonsound",
            "entry_type": "audio",
            "title": "Synthetic Horizon",
            "fields": {
                "author": "Director, Dana",
                "date": "2026-02-01",
                "type": "Album",
            },
        }
        manifests = [
            self.recording_manifest(
                "Literature/ScienceFiction", ["Literature", "Science Fiction"], [novel]
            ),
            self.recording_manifest(
                "Film/ScienceFiction",
                ["Film", "Science Fiction"],
                [
                    self.film_item("director2026synthetichorizon", "2026-03-01"),
                    self.film_item(
                        "remaker2031synthetichorizon",
                        "2031-05-01",
                        author="Remaker, Rae",
                    ),
                ],
            ),
            self.recording_manifest(
                "Music/Soundtracks", ["Music", "Soundtracks"], [soundtrack]
            ),
        ]

        applied = self.run_manifests(manifests, "--apply")

        self.assertEqual(
            applied.returncode,
            0,
            f"stdout:\n{applied.stdout}\nstderr:\n{applied.stderr}",
        )
        catalog = (self.root / "main.typ").read_text(encoding="utf-8")
        self.assertIn(
            "#reference-title(<writer2026synthetichorizon>)[\n"
            '    #text("Synthetic Horizon")\n'
            "  ] #h(0pt) @writer2026synthetichorizon",
            catalog,
        )
        self.assertNotIn(r"\[URL\]", catalog)

        duplicate = self.run_manifest(
            self.recording_manifest(
                "Film/ScienceFiction",
                ["Film", "Science Fiction"],
                [self.film_item("director2026synthetichorizona", "2026-11-20")],
            )
        )
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn(
            "duplicate recording (same title, release year, and first creator)",
            duplicate.stderr,
        )

    def test_recording_identifiers_and_urls_are_validated(self) -> None:
        cases = [
            ({"imdb": "tt12"}, "invalid imdb identifier"),
            (
                {
                    "musicbrainz": "https://musicbrainz.org/release/"
                    "00000000-0000-4000-8000-000000000001"
                },
                "invalid musicbrainz identifier",
            ),
            ({"url": "ftp://files.example.test/film"}, "must be an HTTP(S) URL"),
            ({"url": "https://user:secret@localhost/film"}, "must be an HTTP(S) URL"),
        ]
        for fields, message in cases:
            with self.subTest(message=message, fields=fields):
                result = self.run_manifest(
                    self.recording_manifest(
                        "Film/ScienceFiction",
                        ["Film", "Science Fiction"],
                        [
                            self.film_item(
                                "director2026synthetichorizon", "2026-03-01", **fields
                            )
                        ],
                    )
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)

        duplicate = self.run_manifest(
            self.recording_manifest(
                "Film/ScienceFiction",
                ["Film", "Science Fiction"],
                [
                    self.film_item(
                        "director2026synthetichorizon",
                        "2026-03-01",
                        wikidata="Q4115189",
                    ),
                    self.film_item(
                        "remaker2031synthetichorizon",
                        "2031-05-01",
                        author="Remaker, Rae",
                        wikidata="https://www.wikidata.org/wiki/Q4115189",
                    ),
                ],
            )
        )
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("duplicate wikidata identifier: Q4115189", duplicate.stderr)

    def test_catalog_embeds_the_configured_korean_fallback(self) -> None:
        typst = shutil.which("typst")
        pdffonts = shutil.which("pdffonts")
        pdftotext = shutil.which("pdftotext")
        if not typst or not pdffonts or not pdftotext:
            self.skipTest(
                "typst, pdffonts, and pdftotext are required for the catalog smoke test"
            )

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
        self.assertIn(") <references>", main_text)
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

        rendered_text = subprocess.run(
            [pdftotext, str(output), "-"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(rendered_text.returncode, 0, rendered_text.stderr)
        self.assertNotIn("Titles open References.", rendered_text.stdout)

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
