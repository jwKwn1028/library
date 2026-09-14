from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PublicRepositoryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-public-audit-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "scripts").mkdir()
        (self.root / "templates").mkdir()
        (self.root / "examples").mkdir()
        auditor = self.root / "scripts/public-repo"
        shutil.copy2(REPOSITORY_ROOT / "scripts/public-repo", auditor)
        auditor.chmod(0o755)
        (self.root / ".gitignore").write_text(
            "/main.typ\n/library.bib\n/PaperLibrary.pdf\n/Library/\n"
            "/exports/\n/Inbox/\n/.paper-library.lock\n*.pdf\n*.epub\n"
            "*.mobi\n*.bib\n*.bibtex\n*.ris\n"
            "!examples/references.bib\n!templates/library.bib\n",
            encoding="utf-8",
        )
        (self.root / "templates/library.bib").write_text(
            "% Empty sanitized bibliography.\n", encoding="utf-8"
        )
        (self.root / "examples/references.bib").write_text(
            "% Synthetic example.\n", encoding="utf-8"
        )
        self.git("init")
        self.git("config", "user.name", "Public Contributor")
        self.git(
            "config",
            "user.email",
            "12345+public-contributor" + chr(64) + "users.noreply.github.com",
        )

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        for name in (
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        ):
            environment.pop(name, None)
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def commit(self, message: str) -> None:
        self.git("add", ".")
        self.git("commit", "-m", message)

    def audit(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/public-repo"), "audit"],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_historical_blob_is_checked_again_for_each_path(self) -> None:
        shared_data = "- Synthetic catalog item @example2024record\n"
        (self.root / "README.md").write_text(shared_data, encoding="utf-8")
        (self.root / "templates/main.typ").write_text(shared_data, encoding="utf-8")
        self.commit("add shared historical blob")
        (self.root / "templates/main.typ").write_text(
            '#let bibliography-file = "library.bib"\n#bibliography(bibliography-file)\n',
            encoding="utf-8",
        )
        self.commit("sanitize catalog template")

        result = self.audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "catalog template contains a real citation: templates/main.typ "
            "(Git history)",
            result.stderr,
        )

    def test_rejects_non_noreply_git_identity_without_echoing_it(self) -> None:
        (self.root / "README.md").write_text("Synthetic template.\n", encoding="utf-8")
        (self.root / "templates/main.typ").write_text(
            '#let bibliography-file = "library.bib"\n#bibliography(bibliography-file)\n',
            encoding="utf-8",
        )
        self.git(
            "config",
            "user.email",
            "private-address" + chr(64) + "personal.invalid",
        )
        self.commit("use unsafe identity")

        result = self.audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn("non-noreply author email", result.stderr)
        self.assertIn("non-noreply committer email", result.stderr)
        self.assertNotIn("private-address", result.stderr)


if __name__ == "__main__":
    unittest.main()
