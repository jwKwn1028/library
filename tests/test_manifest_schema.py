from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPOSITORY_ROOT / "skills/paper-library-intake/scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

import intake_papers  # noqa: E402


SCHEMA = json.loads(
    (REPOSITORY_ROOT / "schemas/intake-manifest.schema.json").read_text(
        encoding="utf-8"
    )
)


def definition(name: str) -> dict:
    return SCHEMA["$defs"][name]


class ManifestSchemaTests(unittest.TestCase):
    """Keep the public manifest schema and the intake engine in step."""

    def test_schema_properties_match_the_engine(self) -> None:
        self.assertEqual(set(SCHEMA["properties"]), intake_papers.MANIFEST_PROPERTIES)
        self.assertEqual(
            set(definition("topic")["properties"]), intake_papers.TOPIC_PROPERTIES
        )
        self.assertEqual(
            set(definition("localItem")["properties"]),
            intake_papers.NEW_ITEM_PROPERTIES,
        )
        self.assertEqual(
            set(definition("pendingItem")["properties"]),
            intake_papers.NEW_ITEM_PROPERTIES - {"source_file", "canonical_filename"},
        )
        self.assertEqual(
            set(definition("attachmentItem")["properties"]),
            intake_papers.ATTACHMENT_PROPERTIES,
        )
        self.assertEqual(
            set(definition("fields")["propertyNames"]["not"]["enum"]),
            intake_papers.RESERVED_FIELDS,
        )

    def test_schema_patterns_accept_what_the_engine_accepts(self) -> None:
        samples = {
            "citationKey": (
                intake_papers.KEY_RE,
                [
                    "example2026study",
                    "ab1234c",
                    "Example2026study",
                    "example26study",
                    "example2026",
                    "example2026-study",
                ],
            ),
            "canonicalFilename": (
                intake_papers.NAME_RE,
                [
                    "SyntheticStudy.pdf",
                    "OC20Benchmark.epub",
                    "Guide.mobi",
                    "syntheticStudy.pdf",
                    "Synthetic Study.pdf",
                    "Synthetic.PDF",
                    "Synthetic.docx",
                ],
            ),
        }
        for name, (engine_pattern, values) in samples.items():
            schema_pattern = re.compile(definition(name)["pattern"])
            for value in values:
                with self.subTest(definition=name, value=value):
                    self.assertEqual(
                        schema_pattern.search(value) is not None,
                        engine_pattern.fullmatch(value) is not None,
                    )

        topic_pattern = re.compile(definition("topic")["properties"]["path"]["pattern"])
        for value in (
            "Literature",
            "Film/Crime",
            "QuantumChemistry/DFT2",
            "literature",
            "Film/",
            "Film//Crime",
            "Film Crime",
        ):
            with self.subTest(topic=value):
                engine_accepts = all(
                    intake_papers.TOPIC_RE.fullmatch(part) for part in value.split("/")
                )
                self.assertEqual(
                    topic_pattern.search(value) is not None, engine_accepts
                )

    def test_written_template_uses_only_schema_properties(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paper-library-schema-") as directory:
            path = Path(directory) / "manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_SCRIPTS / "intake_papers.py"),
                    "--write-template",
                    str(path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertLessEqual(set(manifest), set(SCHEMA["properties"]))
        for item in manifest["items"]:
            self.assertLessEqual(set(item), set(definition("localItem")["properties"]))
            self.assertRegex(item["citation_key"], definition("citationKey")["pattern"])
            self.assertRegex(
                item["canonical_filename"], definition("canonicalFilename")["pattern"]
            )


if __name__ == "__main__":
    unittest.main()
