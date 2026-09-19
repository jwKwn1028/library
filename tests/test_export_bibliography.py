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


FILTER_BIBLIOGRAPHY = """% Topic: QuantumChemistry / ElectronicStructure

@article{example2024dft,
  author       = {Example, Ada},
  title        = {A Synthetic Density Study},
  journaltitle = {Journal of Synthetic Examples},
  date         = {2024},
  keywords     = {QuantumChemistry, ElectronicStructure},
  file         = {}
}

@online{example2025preprint,
  author   = {Example, Ada},
  title    = {A Synthetic Preprint},
  date     = {2025},
  url      = {https://preprints.example.test/2025.00001},
  keywords = {QuantumChemistry, ElectronicStructure},
  file     = {}
}

% Topic: Literature / ScienceFiction

@book{writer2020novel,
  author    = {Writer, Wren},
  title     = {A Synthetic Novel},
  date      = {2020},
  publisher = {Example Press},
  keywords  = {Literature, ScienceFiction},
  file      = {}
}

@incollection{writer2021story,
  author    = {Writer, Wren},
  title     = {A Synthetic Story},
  booktitle = {Synthetic Anthology},
  date      = {2021},
  keywords  = {Literature, ScienceFiction},
  file      = {}
}

% Topic: Film / ScienceFiction

@movie{director2026horizon,
  author   = {Director, Dana},
  title    = {Synthetic Horizon},
  date     = {2026},
  keywords = {Film, ScienceFiction},
  file     = {}
}

% Topic: Film / Crime

@video{director2027heist,
  author   = {Director, Dana},
  title    = {Synthetic Heist},
  date     = {2027},
  keywords = {Film, Crime},
  file     = {}
}

% Topic: Music / Jazz

@audio{ensemble2026sessions,
  author   = {{Example Ensemble}},
  title    = {Synthetic Sessions},
  date     = {2026},
  keywords = {Music, Jazz},
  file     = {}
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

    def test_exports_subtitles_and_series_numbers(self) -> None:
        (self.root / "library.bib").write_text(
            """% Topic: Literature / DigitalBooks

@book{example2026subtitled,
  author    = {Example, Ada},
  title     = {Synthetic Collected Work},
  subtitle  = {A Structured Subtitle},
  series    = {Synthetic Cycle},
  number    = {7},
  date      = {2026},
  publisher = {Example Press},
  keywords  = {Literature, DigitalBooks},
  file      = {}
}

@incollection{example2026chapter,
  author    = {Example, Ada},
  title     = {Synthetic Chapter},
  booktitle = {Synthetic Proceedings},
  series    = {Synthetic Lecture Notes},
  number    = {12},
  date      = {2026},
  keywords  = {Literature, DigitalBooks},
  file      = {}
}

@article{example2026issue,
  author       = {Example, Ada},
  title        = {Synthetic Issue Study},
  journaltitle = {Journal of Synthetic Examples},
  series       = {3},
  number       = {4},
  date         = {2026},
  keywords     = {Literature, DigitalBooks},
  file         = {}
}
""",
            encoding="utf-8",
        )

        result = self.run_export("--output", "exports/series.ris")

        self.assertEqual(result.returncode, 0, result.stderr)
        records = (
            (self.root / "exports/series.ris")
            .read_text(encoding="utf-8")
            .split("ER  -")
        )
        book, chapter, article = records[:3]
        self.assertIn("TI  - Synthetic Collected Work: A Structured Subtitle\n", book)
        self.assertIn("T3  - Synthetic Cycle\n", book)
        self.assertIn("M1  - 7\n", book)
        self.assertNotIn("IS  - ", book)
        self.assertIn("SV  - 12\n", chapter)
        self.assertNotIn("IS  - ", chapter)
        self.assertIn("IS  - 4\n", article)
        self.assertNotIn("M1  - ", article)

    def export_ids(self, *filters: str) -> list[str]:
        (self.root / "library.bib").write_text(FILTER_BIBLIOGRAPHY, encoding="utf-8")
        result = self.run_export("--output", "subset.ris", "--force", *filters)
        self.assertEqual(result.returncode, 0, result.stderr)
        exported = (self.root / "subset.ris").read_text(encoding="utf-8")
        return [
            line.removeprefix("ID  - ")
            for line in exported.splitlines()
            if line.startswith("ID  - ")
        ]

    def test_filters_by_kind_of_record_or_exact_entry_type(self) -> None:
        cases = [
            (["--type", "film"], ["director2026horizon", "director2027heist"]),
            (["--type", "papers"], ["example2024dft", "example2025preprint"]),
            (["--type", "book"], ["writer2020novel", "writer2021story"]),
            (["--type", "album"], ["ensemble2026sessions"]),
            (["--type", "Online"], ["example2025preprint"]),
            (
                ["--type", "music,film"],
                ["director2026horizon", "director2027heist", "ensemble2026sessions"],
            ),
            (
                ["--type", "movie", "--type", "article"],
                ["example2024dft", "director2026horizon"],
            ),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                self.assertEqual(self.export_ids(*filters), expected)

    def test_filters_by_topic_and_subtopic(self) -> None:
        cases = [
            (
                ["--topic", "Quantum Chemistry"],
                ["example2024dft", "example2025preprint"],
            ),
            (
                ["--topic", "film", "--topic", "Music"],
                ["director2026horizon", "director2027heist", "ensemble2026sessions"],
            ),
            (["--subtopic", "Film/Crime"], ["director2027heist"]),
            (
                ["--subtopic", "ScienceFiction"],
                ["writer2020novel", "writer2021story", "director2026horizon"],
            ),
            # Different options must all match.
            (
                ["--topic", "Film", "--subtopic", "ScienceFiction"],
                ["director2026horizon"],
            ),
            (
                ["--type", "book", "--subtopic", "ScienceFiction"],
                ["writer2020novel", "writer2021story"],
            ),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                self.assertEqual(self.export_ids(*filters), expected)

        result = self.run_export(
            "--output", "subset.ris", "--force", "--type", "film", "--topic", "Film"
        )
        self.assertIn(
            "Exported 2 of 7 record(s) matching type film; topic Film", result.stdout
        )

    def test_rejects_unknown_or_empty_filters_without_writing(self) -> None:
        (self.root / "library.bib").write_text(FILTER_BIBLIOGRAPHY, encoding="utf-8")
        cases = [
            (
                ["--topic", "Chemistry"],
                "unknown topic: Chemistry; available topics: "
                "Film, Literature, Music, QuantumChemistry",
            ),
            (["--topic", "Film/Crime"], "use --subtopic Film/Crime"),
            (["--subtopic", "Film"], "it is a top-level topic, so use --topic"),
            (["--subtopic", "Horror"], "unknown subtopic: Horror"),
            (["--subtopic", "Film/"], "invalid subtopic: Film/"),
            (["--type", "flim"], "unknown record type: flim"),
            (
                ["--type", "music", "--topic", "Film"],
                "no records match type music; topic Film; nothing was written",
            ),
        ]
        output = self.root / "subset.ris"
        for filters, message in cases:
            with self.subTest(filters=filters):
                result = self.run_export("--output", output.as_posix(), *filters)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
                self.assertFalse(output.exists())

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
