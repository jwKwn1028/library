---
name: paper-library-intake
description: Intake or attach research papers and books in PDF, EPUB, or MOBI format, or add explicitly requested metadata-only reading-list records, by recovering and verifying metadata, checking duplicates, classifying items, consolidating BibTeX in library.bib, updating main.typ, validating, and rebuilding the catalog. Use for requests to add, organize, rename, recommend, complete pending downloads, or catalog research documents in this workspace; do not use for unsolicited mass reorganization of existing items.
---

# Paper Library Intake

Use the bundled manifest-driven script for filesystem and catalog changes. Keep
title recovery, taxonomy selection, and title shortening as reviewed decisions;
they are not safe to infer mechanically.

## Intake

1. Work from the paper-library root. If root `main.typ` or `library.bib` is
   missing, run `./scripts/init-library` to copy the sanitized public seeds.
   This also creates the ignored `Library/` media root when absent. Never
   overwrite existing local files or copy private records into `templates/`.
2. For local intake, inspect only the new PDF, EPUB, or MOBI files and their
   downloaded `.bib` or `.bibtex` sidecars. For PDFs, use `pdfinfo` and
   first-page `pdftotext` output. For ebooks, inspect embedded metadata and the
   title page with an available ebook reader or metadata tool. Recover the
   official title and identifiers from the document itself before trusting a
   citation export. For an explicitly requested metadata-only reading list,
   verify the complete record from authoritative web sources and mark the
   manifest item `pending: true`.
3. If local metadata is incomplete or inconsistent, retrieve metadata as an
   agent task from the publisher/DOI record, Crossref, or another authoritative
   primary source. Verify it against the document. Do not add network access to the
   intake script or copy remote BibTeX directly into `library.bib`.
4. Read [references/intake-contract.md](references/intake-contract.md). Apply
   its naming, classification, metadata, and duplicate rules before preparing
   the manifest. The preferred manifest also has a machine-readable schema at
   `../../schemas/intake-manifest.schema.json` from the repository root.
5. Create one JSON manifest per destination subtopic. A pending item omits
   `source_file` and `canonical_filename`; a local item requires both. Prefer
   a temporary manifest outside the library. Generate a starter when useful:

   ```sh
   ./scripts/intake-papers --write-template /tmp/paper-intake.json
   ```

6. Run a dry run and inspect every proposed move, source format, key, DOI, and
   destination:

   ```sh
   ./scripts/intake-papers --manifest /tmp/paper-intake.json
   ```

7. If the plan matches the request, apply it. `--apply` moves local library
   files to `Library/<topic.path>/` when present, creates that topic directory
   even for a pending-only manifest, appends normalized entries to
   `library.bib`, inserts linked local citations or unlinked pending citations
   without visible status labels into the requested `main.typ` hierarchy, runs
   `scripts/validate-library.sh`, and atomically rebuilds `PaperLibrary.pdf` in
   the root:

   ```sh
   ./scripts/intake-papers --manifest /tmp/paper-intake.json --apply
   ```

8. Keep source sidecars by default. Add `--delete-sidecars` only when their
   removal is explicitly within scope; deletion occurs after successful
   validation and build and participates in rollback.

## Complete a pending record

1. List outstanding records with
   `./scripts/intake-papers status --pending`; use `--json` for automation.
2. Inspect the downloaded document and confirm that its identity matches the
   existing record.
3. Create a manifest for the record's existing topic with `attach: true`, its
   established `citation_key`, `source_file`, and `canonical_filename`. Omit
   `pending`, titles, entry type, and `fields`.
4. Dry-run and apply normally. The transaction fills the existing empty
   `file` field and links the existing catalog item without changing its key or
   metadata.

## Guardrails

- Do not use the script to recategorize or rename already cataloged items.
- An attachment manifest is the only routine update to an existing item.
- Keep root `main.typ`, root `library.bib`, the entire `Library/` tree,
  generated catalogs, manifests, and citation sidecars private and Git-ignored.
  Do not force-add them.
- Do not bypass dry-run review. Resolve warnings or conflicts instead of
  weakening checks.
- Preserve stable citation keys even if a display title or filename changes.
- Accept a reviewed editor-only book; records require an author or an editor,
  not necessarily both.
- Prefer the document's title page when downloaded metadata conflicts with it.
- Never invent a file path or create a placeholder document for a pending
  recommendation. Its BibTeX `file` field must stay empty; only its destination
  topic directory is created.
- Treat all downloaded BibTeX as untrusted input. Prefer publisher/DOI metadata,
  then Crossref, then an official preprint or institutional record; use a
  secondary index only as a verified fallback.
- When a user requests a Zotero/EndNote interchange file, use
  `scripts/export-bibliography` to derive private UTF-8 RIS metadata. Keep
  `library.bib` canonical and do not add attachment paths to the export.
- Report each original filename, format, canonical path, citation key, metadata
  correction, new category, and retained or removed sidecar.
- If the script rolls back or validation fails, leave the goal incomplete and
  report the concrete error; do not claim partial changes as successful intake.
