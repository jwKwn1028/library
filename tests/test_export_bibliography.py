from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = REPOSITORY_ROOT / "scripts" / "export-bibliography"
SYNTHETIC_BIBLIOGRAPHY = """% Synthetic test bibliography.

@article{example2024dft,
  author       = {Example, Ada and Researcher, Ben},
  title        = {A {DFT} Study of Møller Theory},
  journaltitle = {Journal of Synthetic Examples},
  date         = {2024-03-04},
  volume       = {12},
  number       = {3},
  pages        = {10--19},
  doi          = {10.0000/synthetic-article},
  url          = {https://doi.org/10.0000/synthetic-article},
  keywords     = {QuantumChemistry, ElectronicStructure},
  file         = {Library/QuantumChemistry/SyntheticArticle.pdf}
}

@book{consortium2020handbook,
  author    = {{Example Research Consortium}},
  title     = {Synthetic Handbook},
  date      = {2020},
  publisher = {Example Press},
  location  = {Example City},
  edition   = {2},
  isbn      = {978-0-000-00000-2},
  url       = {https://example.test/~consortium/handbook},
  keywords  = {Literature, DigitalBooks},
  file      = {}
}
"""


class BibliographyExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="paper-library-export-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "library.bib").write_text(
            SYNTHETIC_BIBLIOGRAPHY,
            encoding="utf-8",
        )

    def run_export(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(EXPORT_SCRIPT),
                "--root",
                str(self.root),
                *arguments,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_exports_portable_utf8_ris_without_file_paths(self) -> None:
        result = self.run_export("--output", "exports/references.ris")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Exported 2 record(s)", result.stdout)

        output = self.root / "exports/references.ris"
        raw = output.read_bytes()
        exported = raw.decode("utf-8")
        self.assertIn(b"\r\n", raw)
        self.assertEqual(exported.count("TY  - "), 2)
        self.assertEqual(exported.count("ER  -"), 2)
        self.assertIn("TY  - JOUR\r\n", exported)
        self.assertIn("ID  - example2024dft\r\n", exported)
        self.assertIn("AU  - Example, Ada\r\n", exported)
        self.assertIn("AU  - Researcher, Ben\r\n", exported)
        self.assertIn("TI  - A DFT Study of Møller Theory\r\n", exported)
        self.assertIn("JF  - Journal of Synthetic Examples\r\n", exported)
        self.assertIn("PY  - 2024\r\n", exported)
        self.assertIn("DA  - 2024/03/04\r\n", exported)
        self.assertIn("SP  - 10\r\n", exported)
        self.assertIn("EP  - 19\r\n", exported)
        self.assertIn("KW  - QuantumChemistry\r\n", exported)
        self.assertIn("TY  - BOOK\r\n", exported)
        self.assertIn("AU  - Example Research Consortium\r\n", exported)
        self.assertIn("SN  - 978-0-000-00000-2\r\n", exported)
        self.assertIn("UR  - https://example.test/~consortium/handbook\r\n", exported)
        self.assertNotIn("Library/", exported)
        self.assertNotIn("file         =", exported)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_exports_albums_and_films_as_recording_types(self) -> None:
        (self.root / "library.bib").write_text(
            """% Topic: Music / Jazz

@audio{example2026syntheticsessions,
  author    = {{Example Ensemble} and Example, Ada},
  title     = {Synthetic Sessions},
  date      = {2026-01-15},
  publisher = {Example Records},
  url       = {https://music.example.test/album/synthetic},
  keywords  = {Music, Jazz},
  file      = {}
}

% Topic: Film / ScienceFiction

@movie{director2026synthetichorizon,
  author   = {Director, Dana},
  title    = {Synthetic Horizon},
  date     = {2026-03-01},
  keywords = {Film, ScienceFiction},
  file     = {}
}

@video{director2026syntheticcut,
  author   = {Director, Dana},
  title    = {Synthetic Horizon: The Long Cut},
  date     = {2027},
  keywords = {Film, ScienceFiction},
  file     = {}
}
""",
            encoding="utf-8",
        )

        result = self.run_export("--output", "exports/recordings.ris")

        self.assertEqual(result.returncode, 0, result.stderr)
        exported = (self.root / "exports/recordings.ris").read_text(encoding="utf-8")
        self.assertIn("TY  - SOUND\n", exported)
        self.assertIn("TY  - MPCT\n", exported)
        self.assertIn("TY  - VIDEO\n", exported)
        self.assertIn("AU  - Example Ensemble\n", exported)
        self.assertIn("AU  - Example, Ada\n", exported)
        self.assertIn("PB  - Example Records\n", exported)

    def test_refuses_overwrite_without_force(self) -> None:
        output = self.root / "references.ris"
        first = self.run_export("--output", output.as_posix())
        self.assertEqual(first.returncode, 0, first.stderr)
        original = output.read_bytes()

        refused = self.run_export("--output", output.as_posix())
        self.assertEqual(refused.returncode, 2)
        self.assertIn("output already exists", refused.stderr)
        self.assertEqual(output.read_bytes(), original)

        replaced = self.run_export("--output", output.as_posix(), "--force")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertEqual(output.read_bytes(), original)

    def test_rejects_malformed_bibliography_without_output(self) -> None:
        (self.root / "library.bib").write_text(
            "@article{broken2024entry,\n  title = {Unclosed}\n",
            encoding="utf-8",
        )
        output = self.root / "broken.ris"

        result = self.run_export("--output", output.as_posix())

        self.assertEqual(result.returncode, 2)
        self.assertIn("unclosed brace", result.stderr)
        self.assertFalse(output.exists())

    def test_shared_parser_accepts_quoted_and_multiline_fields(self) -> None:
        (self.root / "library.bib").write_text(
            """@book{editor2022multiline,
  editor = "Editor, Erin and Curator, Casey",
  title = {A Synthetic
    Multiline Handbook},
  date = 2022,
  publisher = {Example Press},
  keywords = "Literature, DigitalBooks",
  file = {}
}
""",
            encoding="utf-8",
        )

        result = self.run_export("--output", "multiline.ris")

        self.assertEqual(result.returncode, 0, result.stderr)
        exported = (self.root / "multiline.ris").read_text(encoding="utf-8")
        self.assertIn("ED  - Editor, Erin\n", exported)
        self.assertIn("ED  - Curator, Casey\n", exported)
        self.assertIn("TI  - A Synthetic Multiline Handbook\n", exported)
        self.assertIn("PY  - 2022\n", exported)


if __name__ == "__main__":
    unittest.main()
