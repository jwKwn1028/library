# Paper Library Template

A reusable Typst catalog for papers, books, albums, and films. See the
[usage guide](docs/usage.md) or [agent rules](AGENTS.md).

## Setup

```sh
./scripts/init-library
./scripts/install-hooks
```

## Common commands

```sh
./scripts/stage-papers /path/to/document.pdf [--apply]
./scripts/intake-papers --manifest /tmp/intake.json [--apply]
./scripts/search-bibliography embedding
./scripts/validate-library.sh
./scripts/test
./scripts/export-bibliography
./scripts/public-repo audit
```

Private library data and exports are Git-ignored; back them up separately.

MIT licensed; see [LICENSE](LICENSE). Private records and media are excluded.
