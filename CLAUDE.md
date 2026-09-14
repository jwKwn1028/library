# Claude Code Instructions

Before changing this paper library, read and follow `./AGENTS.md`. It is the
authoritative repository guide; this file intentionally does not duplicate the
full policy so the two instruction sets cannot drift.

This public repository contains sanitized templates and examples. The working
root `main.typ`, `library.bib`, the complete `Library/` media tree, and
`PaperLibrary.pdf` are private Git-ignored state. Canonical PDF/EPUB/MOBI files
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
3. Inspect the document's title page and embedded metadata before trusting a
   citation export. Supported library formats are PDF, EPUB, and MOBI.
4. Retrieve missing BibTeX metadata from authoritative web sources as an agent
   task; do not add networking to the transactional intake script.
5. Prepare and review a manifest with `scripts/intake-papers` before using
   `--apply`.
6. Keep the private root `library.bib` and `main.typ` as the local sources of
   truth.
7. Finish by running `scripts/validate-library.sh` and rebuilding the root-level
   `PaperLibrary.pdf`.

For an explicitly requested metadata-only reading list, verify each complete
record from authoritative web sources, use `pending: true`, and omit
`source_file` and `canonical_filename`. Never invent a local path or create a
placeholder document. Pending titles stay unlinked without visible status text,
their BibTeX `file` fields stay empty, and apply creates the empty destination
topic directory under `Library/` for the future file.

List pending records with `scripts/intake-papers status --pending`. When one is
downloaded, use an `attach: true` manifest item with its existing citation key;
the transaction connects the inspected file without duplicating or rewriting
the record. Editor-only books are valid. The preferred manifest schema is
`schemas/intake-manifest.schema.json`, and commands use the repository's
advisory intake lock.

Preserve New Computer Modern Sans as the primary catalog face and the
overridable `korean-font` input as its Hangul fallback. The checked-in default
matches the Korean sans-serif selected by Fontconfig on the originating system.

Do not mass-reorganize existing items or delete citation sidecars unless the
user's request explicitly includes that scope.

Before committing, pushing, or publishing, run `scripts/public-repo audit`.
Never force-add ignored local library data; prefer an independently audited
export produced by `scripts/public-repo export <empty-directory>`. Use a
public-safe Git name and provider no-reply author/committer address because the
audit checks configured and reachable history identities. Run `scripts/test`
after framework changes.
