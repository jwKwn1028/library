# Paper Library Template

A Typst Library Catalog for research papers and books.

## Quick start

Initialize the private files and install the repository hooks:

```sh
./scripts/init-library
./scripts/install-hooks
```

`init-library` preserves existing files and creates the ignored `Library/`
media root when needed.

Generate, review, and apply an intake manifest:

```sh
./scripts/stage-papers /path/to/document.pdf
./scripts/stage-papers /path/to/document.pdf --apply
./scripts/intake-papers --write-template /tmp/paper-intake.json
./scripts/intake-papers --manifest /tmp/paper-intake.json
./scripts/intake-papers --manifest /tmp/paper-intake.json --apply
./scripts/intake-papers status --pending
./scripts/fetch-pending --key author2026shorttitle
```

Local documents are stored at
`Library/<topic.path>/<CanonicalFilename>`. For a verified metadata-only item,
use `pending: true` and omit `source_file` and `canonical_filename`.
Use `attach: true` in a later manifest to connect its downloaded document.
The preferred manifest shape is documented by
`schemas/intake-manifest.schema.json`.
Repeat `--manifest` for an atomic multi-topic batch. Use optional
`metadata_sources` with `--report-json reports/<name>.json` for a private
provenance record. Each successful apply updates the catalog's private
last-updated date.

## Validate and publish

Validate the private library and build its catalog:

```sh
./scripts/validate-library.sh
typst compile main.typ Catalog.pdf
./scripts/test
```

Export portable RIS metadata for Zotero or EndNote:

```sh
./scripts/export-bibliography
```

Audit before every public commit, push, or release:

```sh
./scripts/public-repo audit
```

For a clean public-only tree:

```sh
./scripts/public-repo export /tmp/paper-library-template
```

Ignored private data is not backed up. Store it separately in a private or
encrypted backup.
