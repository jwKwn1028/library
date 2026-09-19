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
            "/main.typ\n/library.bib\n/Catalog.pdf\n/Library/\n"
            "/exports/\n/Inbox/\n/reports/\n/.paper-library.lock\n"
            "/.paper-library-private-terms\n*.pdf\n*.epub\n"
            "*.mobi\n*.bib\n*.bibtex\n*.ris\n*.intake-report.json\n"
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

    def test_standalone_export_audit_ignores_generated_tool_caches(self) -> None:
        exported_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-standalone-export-"
        )
        self.addCleanup(exported_directory.cleanup)
        exported_root = Path(exported_directory.name)
        (exported_root / "scripts").mkdir()
        auditor = exported_root / "scripts/public-repo"
        shutil.copy2(REPOSITORY_ROOT / "scripts/public-repo", auditor)
        (exported_root / "README.md").write_text(
            "Synthetic public framework.\n", encoding="utf-8"
        )
        ruff_cache = exported_root / ".ruff_cache/0.15.22"
        ruff_cache.mkdir(parents=True)
        (ruff_cache / "cache-entry").write_bytes(b"\x00generated")
        python_cache = exported_root / "paperlib/__pycache__"
        python_cache.mkdir(parents=True)
        (python_cache / "module.cpython-313.pyc").write_bytes(b"\x00generated")

        result = subprocess.run(
            [sys.executable, str(auditor), "audit"],
            cwd=exported_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 public files passed", result.stdout)

    def test_rejects_a_private_byline_in_the_catalog_template(self) -> None:
        (self.root / "templates/main.typ").write_text(
            '#let catalog-author = "Synthetic Person"\n'
            '#let catalog-updated = "January 1, 2026"\n'
            '#let bibliography-file = "library.bib"\n'
            "#bibliography(bibliography-file)\n",
            encoding="utf-8",
        )

        result = self.audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "catalog template contains a non-empty private byline", result.stderr
        )

    def test_rejects_institutional_proxy_urls_but_allows_reserved_examples(
        self,
    ) -> None:
        readme = self.root / "README.md"
        readme.write_text(
            "PAPER_LIBRARY_PROXY_PREFIX=https://proxy.example.org/login?url=\n",
            encoding="utf-8",
        )
        allowed = self.audit()
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

        # Each synthetic proxy is split so this test file passes the real audit.
        leaked_prefixes = (
            "https://ez" + "proxy.library.university.ac.xx/login?url=",
            "https://gateway.university.ac.xx/_Lib_" + "Proxy_Url/",
            "https://login.university.ac.xx/" + "login?url=https://doi.org/10.0/x",
            "https://university.idm" + ".oclc.org/login?url=",
        )
        for leaked in leaked_prefixes:
            with self.subTest(leaked=leaked):
                readme.write_text(f"Proxy: {leaked}\n", encoding="utf-8")
                result = self.audit()
                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    "possible institutional proxy URL: README.md (working tree)",
                    result.stderr,
                )

    def test_private_terms_are_rejected_without_being_echoed(self) -> None:
        (self.root / ".paper-library-private-terms").write_text(
            "# Git-ignored identifying terms.\nSynthetic Institute\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            "Built at the synthetic institute library.\n", encoding="utf-8"
        )

        result = self.audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn("possible private term: README.md (working tree)", result.stderr)
        self.assertNotIn("synthetic institute", result.stderr.casefold())
        self.assertNotIn(".paper-library-private-terms (working tree)", result.stderr)

    def test_rejects_private_values_in_history_messages_without_echoing_them(
        self,
    ) -> None:
        readme = self.root / "README.md"
        readme.write_text("Synthetic template.\n", encoding="utf-8")
        trailer = (
            "Co-Authored-By: Synthetic Agent <agent" + chr(64) + "noreply.example.test>"
        )
        self.commit(f"add synthetic readme\n\n{trailer}")
        allowed = self.audit()
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

        # Split literals keep this test file from matching the real audit.
        leaked_email = "reader" + chr(64) + "university.xx"
        leaked_path = "/ho" + "me/reader/Downloads"
        readme.write_text("Synthetic template, revised.\n", encoding="utf-8")
        self.commit(f"import from {leaked_path} for {leaked_email}")
        self.git("tag", "-a", "v1", "-m", f"release for {leaked_email}")

        result = self.audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn("possible email address in commit message", result.stderr)
        self.assertIn(
            "possible absolute home-directory path in commit message", result.stderr
        )
        self.assertIn("possible email address in tag message v1", result.stderr)
        self.assertNotIn("university.xx", result.stderr)
        self.assertNotIn("Downloads", result.stderr)

    def test_audit_message_checks_the_message_git_will_record(self) -> None:
        (self.root / ".paper-library-private-terms").write_text(
            "Synthetic Institute\n", encoding="utf-8"
        )
        message = self.root / ".git/COMMIT_EDITMSG"
        leaked_email = "reader" + chr(64) + "university.xx"

        def audit_message(text: str) -> subprocess.CompletedProcess[str]:
            message.write_text(text, encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(self.root / "scripts/public-repo"),
                    "audit-message",
                    str(message),
                ],
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        accepted = audit_message(
            "fix: synthetic change\n\n"
            "Co-Authored-By: Synthetic Agent <agent"
            + chr(64)
            + "noreply.example.test>\n"
            "# Lines starting with '#' are not recorded.\n"
            "# ------------------------ >8 ------------------------\n"
            f"-removed contact {leaked_email}\n"
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        rejected = audit_message(
            f"fix: thanks to the synthetic institute and {leaked_email}\n"
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("commit message failed the privacy audit", rejected.stderr)
        self.assertIn("possible email address", rejected.stderr)
        self.assertIn("possible private term", rejected.stderr)
        self.assertNotIn("university.xx", rejected.stderr)
        self.assertNotIn("synthetic institute", rejected.stderr.casefold())

    def test_rejects_a_private_term_too_short_to_be_meaningful(self) -> None:
        (self.root / ".paper-library-private-terms").write_text(
            "ab\n", encoding="utf-8"
        )

        result = self.audit()

        self.assertEqual(result.returncode, 1)
        self.assertIn("line 1 is shorter than 3 characters", result.stderr)


if __name__ == "__main__":
    unittest.main()
