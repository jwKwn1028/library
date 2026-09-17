# Claude Code Instructions

Before changing this paper library, read and follow `./AGENTS.md`. It is the
authoritative repository guide; this file intentionally does not duplicate the
full policy so the two instruction sets cannot drift.

This public repository contains sanitized templates and examples. The working
root `main.typ`, `library.bib`, the complete `Library/` media tree, and
`Catalog.pdf` are private Git-ignored state. Canonical PDF/EPUB/MOBI files
live at `Library/<topic.path>/<CanonicalFilename>`. If the two root source
files are missing, initialize them with `scripts/init-library`; it also creates
`Library/` when absent. Never copy private content back into `templates/`.

Use `docs/usage.md` as the comprehensive public operating guide. Keep it in sync
when changing commands, manifest behavior, template invariants, or publication
safeguards, without adding private library content.

Use `scripts/export-bibliography` for a portable Zotero/EndNote RIS file.
Treat its output as private derived metadata: keep `library.bib` canonical,
omit local attachment paths, and never copy a real export into public examples.

For any request to add, organize, rename, or catalog papers or books:

1. Read `skills/paper-library-intake/SKILL.md` and its linked intake contract.
2. Run `scripts/init-library` if root `main.typ` or `library.bib` is absent.
3. For external files, review `scripts/stage-papers <path...>` and repeat it
   with `--apply` to copy them into the ignored `Inbox/` while preserving the
   originals.
4. Inspect the document's title page and embedded metadata before trusting a
   citation export. Supported library formats are PDF, EPUB, and MOBI.
5. Retrieve missing BibTeX metadata from authoritative web sources as an agent
   task; do not add networking to the transactional intake script.
6. Prepare one manifest per topic and review it with `scripts/intake-papers`
   before using `--apply`. Repeat `--manifest` for one transactional
   multi-topic batch. Optional `metadata_sources` and `--report-json` retain
   provenance only in a private, Git-ignored JSON report.
7. Keep the private root `library.bib` and `main.typ` as the local sources of
   truth.
8. Finish by running `scripts/validate-library.sh` and rebuilding the root-level
   `Catalog.pdf`.

A successful intake apply updates the private quoted `catalog-updated` value to
the current local date within the same rollback boundary. Dry runs do not alter
it. Keep the public template's `catalog-author` and `catalog-updated` defaults
empty; never copy a private byline into public files.

For an explicitly requested metadata-only reading list, verify each complete
record from authoritative web sources, use `pending: true`, and omit
`source_file` and `canonical_filename`. Never invent a local path or create a
placeholder document. Pending titles link to their individual bibliography
entries without visible status text, their BibTeX `file` fields stay empty,
and apply creates the empty destination topic directory under `Library/` for
the future file. Every title retains that link; a local item also has a
separate `[PDF]`, `[EPUB]`, or `[MOBI]` attachment link. Keep the explanation
of missing local attachments in public documentation rather than displaying it
inside the generated catalog.

List pending records with `scripts/intake-papers status --pending`. When one is
downloaded, use an `attach: true` manifest item with its existing citation key;
the transaction connects the inspected file without duplicating or rewriting
the record. Editor-only books are valid. The preferred manifest schema is
`schemas/intake-manifest.schema.json`, and commands use the repository's
advisory intake lock.

When the user requests downloads, use `scripts/fetch-pending --key KEY` as a
network lookup dry run and repeat with `--apply` to stage accessible,
identity-checked PDFs in ignored `Inbox/`. Use `--all` only when explicitly
requested. `PAPER_LIBRARY_FETCH_EMAIL` enables Unpaywall at runtime and must
never be stored or printed. The fetcher must not use cookies, credentials, or
paywall bypasses and never edits canonical bibliography/catalog state; inspect
each result and finish through the ordinary attachment manifest. For records it
cannot reach, `--browser` only opens publisher pages in the user's own browser,
optionally through the runtime `PAPER_LIBRARY_PROXY_PREFIX`; after the user
downloads them, `--match <directory>` identifies the PDFs and `--apply` copies
unique matches into `Inbox/`. Never read browser state, and keep proxy prefixes
and browser commands out of public files.

Preserve New Computer Modern Sans as the primary catalog face and the
overridable `korean-font` input as its Hangul fallback. The checked-in default
matches the Korean sans-serif selected by Fontconfig on the originating system.

Do not mass-reorganize existing items or delete citation sidecars unless the
user's request explicitly includes that scope.

Before committing, pushing, or publishing, run `scripts/public-repo audit`.
Never force-add ignored local library data; prefer an independently audited
export produced by `scripts/public-repo export <empty-directory>`. Use a
public-safe Git name and provider no-reply author/committer address because the
audit checks configured and reachable history identities. Standalone exports
may ignore only known generated Python and lint/test caches; other unexpected
paths remain audit failures. The audit also rejects institutional proxy URLs
and every term listed in the Git-ignored `.paper-library-private-terms`; never
copy that file's contents into public files. Run `scripts/test` after framework
changes.
