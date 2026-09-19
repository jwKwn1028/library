from __future__ import annotations

import fcntl
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STAGE_ENGINE = (
    REPOSITORY_ROOT / "skills" / "paper-library-intake" / "scripts" / "stage_papers.py"
)
if str(STAGE_ENGINE.parent) not in sys.path:
    sys.path.insert(0, str(STAGE_ENGINE.parent))

import stage_papers  # noqa: E402


class StagePapersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-stage-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        temporary_root = Path(self.temporary_directory.name)
        self.root = temporary_root / "library"
        self.external = temporary_root / "external"
        self.root.mkdir()
        self.external.mkdir()

    @staticmethod
    def write_epub(destination: Path, identifier: str) -> None:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(mimetype, b"application/epub+zip")
            archive.writestr(
                "META-INF/container.xml",
                f"<container><identifier>{identifier}</identifier></container>",
            )

    def run_stage(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(STAGE_ENGINE),
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

    def test_dry_run_then_apply_preserves_external_source(self) -> None:
        source = self.external / "incoming.epub"
        self.write_epub(source, "first")
        original = source.read_bytes()

        dry_run = self.run_stage(str(source))

        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertIn("DRY RUN — no files changed", dry_run.stdout)
        self.assertFalse((self.root / "Inbox/incoming.epub").exists())

        applied = self.run_stage(str(source), "--apply")

        self.assertEqual(applied.returncode, 0, applied.stderr)
        destination = self.root / "Inbox/incoming.epub"
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(destination.read_bytes(), original)
        self.assertIn("originals were preserved", applied.stdout)

    def test_rejects_symlinks_and_duplicate_content(self) -> None:
        source = self.external / "source.epub"
        duplicate = self.external / "duplicate.epub"
        self.write_epub(source, "same")
        duplicate.write_bytes(source.read_bytes())
        symlink = self.external / "linked.epub"
        symlink.symlink_to(source)

        linked_result = self.run_stage(str(symlink))
        self.assertEqual(linked_result.returncode, 2)
        self.assertIn("must not be a symlink", linked_result.stderr)

        duplicate_result = self.run_stage(str(source), str(duplicate))
        self.assertEqual(duplicate_result.returncode, 2)
        self.assertIn("duplicates existing content", duplicate_result.stderr)
        self.assertFalse((self.root / "Inbox").exists())

    def test_uses_the_shared_library_lock(self) -> None:
        source = self.external / "locked.epub"
        self.write_epub(source, "locked")
        lock_path = self.root / ".paper-library.lock"

        with lock_path.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_stage(str(source), "--lock-timeout", "0")

        self.assertEqual(result.returncode, 2)
        self.assertIn("library is busy", result.stderr)
        self.assertFalse((self.root / "Inbox").exists())

    def test_interrupted_copy_leaves_no_partial_inbox_files(self) -> None:
        plans = []
        for name in ("first.epub", "second.epub"):
            source = self.external / name
            self.write_epub(source, name)
            plans.append(
                stage_papers.StagePlan(
                    source, self.root / "Inbox" / name, stage_papers.sha256(source)
                )
            )

        # The second copy is interrupted after the first has been published.
        with (
            mock.patch.object(
                stage_papers, "validate_media", side_effect=[None, KeyboardInterrupt]
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            stage_papers.copy_plans(self.root, plans)

        self.assertFalse((self.root / "Inbox").exists())

    def test_rejects_a_symlinked_inbox(self) -> None:
        source = self.external / "incoming.epub"
        self.write_epub(source, "unsafe-inbox")
        unsafe_destination = self.external / "redirected-inbox"
        unsafe_destination.mkdir()
        (self.root / "Inbox").symlink_to(unsafe_destination, target_is_directory=True)

        result = self.run_stage(str(source), "--apply")

        self.assertEqual(result.returncode, 2)
        self.assertIn("private media root must not be a symlink", result.stderr)
        self.assertEqual(list(unsafe_destination.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
