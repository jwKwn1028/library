# Paper Library Template

A Typst catalog for research papers and books. See
[`docs/usage.md`](docs/usage.md) for the full guide and
[`AGENTS.md`](AGENTS.md) for agent rules.

## Quick start

```sh
./scripts/init-library    # creates private main.typ, library.bib, Library/
./scripts/install-hooks
```

## Intake

```sh
./scripts/stage-papers /path/to/document.pdf [--apply]
./scripts/intake-papers --write-template /tmp/paper-intake.json
./scripts/intake-papers --manifest /tmp/paper-intake.json [--apply]
./scripts/intake-papers status --pending
./scripts/fetch-pending --key author2026shorttitle [--apply] [--browser]
./scripts/fetch-pending --match ~/Downloads [--apply]
```

Manifests follow `schemas/intake-manifest.schema.json`.

## Validate, export, publish

```sh
./scripts/validate-library.sh
typst compile main.typ Catalog.pdf
./scripts/test
./scripts/export-bibliography    # private RIS for Zotero/EndNote
./scripts/public-repo audit      # before every commit, push, or release
./scripts/public-repo export /tmp/paper-library-template
```

Private library data is Git-ignored and not backed up; keep a separate private
or encrypted backup.
