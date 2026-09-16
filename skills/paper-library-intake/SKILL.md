---
name: paper-library-intake
description: Intake or attach research papers and books in PDF, EPUB, or MOBI format, fetch accessible PDFs for pending DOI-backed records, or add explicitly requested metadata-only reading-list records, by recovering and verifying metadata, checking duplicates, classifying items, consolidating BibTeX in library.bib, updating main.typ, validating, and rebuilding the catalog. Use for requests to add, organize, rename, recommend, download, complete pending records, or catalog research documents in this workspace; do not use for unsolicited mass reorganization of existing items.
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
   If the files are outside the repository, stage reviewed explicit paths with
   `./scripts/stage-papers PATH...`, inspect its dry run, then repeat with
   `--apply`. Staging copies into the ignored `Inbox/`, preserves the
   originals, verifies media signatures and hashes, and shares the intake lock.
3. If local metadata is incomplete or inconsistent, retrieve metadata as an
   agent task from the publisher/DOI record, Crossref, or another authoritative
   primary source. Verify it against the document. Do not add network access to the
   intake script or copy remote BibTeX directly into `library.bib`.
4. Read [references/intake-contract.md](references/intake-contract.md). Apply
   its naming, classification, metadata, and duplicate rules before preparing
   the manifest. The preferred manifest also has a machine-readable schema at
   `../../schemas/intake-manifest.schema.json` from the repository root.
5. Create one JSON manifest per destination subtopic. A pending item omits
   `source_file` and `canonical_filename`; a local item requires both. Add
   optional `metadata_sources` HTTP(S) URLs to retain reviewed provenance in a
   private report. Prefer a temporary manifest outside the library. Generate a
   starter when useful:

   ```sh
   ./scripts/intake-papers --write-template /tmp/paper-intake.json
   ```

6. Run a dry run and inspect every proposed move, source format, key, DOI, and
   destination. Repeat `--manifest` to preflight several topics as one batch;
   every manifest must pass before anything can be applied:

   ```sh
   ./scripts/intake-papers \
     --manifest /tmp/topic-a.json \
     --manifest /tmp/topic-b.json
   ```

7. If the plan matches the request, apply it. `--apply` moves local library
   files to `Library/<topic.path>/` when present, creates that topic directory
   even for a pending-only manifest, appends normalized entries to
   `library.bib`, inserts titles linked to the labeled References section and,
   for local media, adds a separate bracketed format link without visible
   pending-status labels,
   runs `scripts/validate-library.sh`, and atomically rebuilds `Catalog.pdf` in
   the root. It also sets the quoted private `catalog-updated` value to the
   current local date. The whole repeated-manifest batch is one transaction:

   ```sh
   ./scripts/intake-papers \
     --manifest /tmp/topic-a.json \
     --manifest /tmp/topic-b.json \
     --apply
   ```

8. Keep source sidecars by default. Add `--delete-sidecars` only when their
   removal is explicitly within scope; deletion occurs after successful
   validation and build and participates in rollback.
9. When durable provenance is useful, add `--report-json
   reports/<name>.json`. The report is private, Git-ignored, and written with
   owner-only permissions. It records the reviewed plan and
   `metadata_sources`; an applied report is committed only after validation and
   compilation pass. Use `--force-report` only to replace a known report.

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

## Fetch pending PDFs

Use the separate networked fetcher only when the user asks to download pending
documents. Keep `intake-papers` offline.

1. Select explicit citation keys by default and inspect the lookup-only run:

   ```sh
   ./scripts/fetch-pending --key author2026shorttitle
   ```

   Use `--all` only when the user explicitly requests the whole pending set.
2. Repeat with `--apply` to try accessible candidates. Downloads are bounded,
   must have a valid PDF signature/container, and must match the pending DOI or
   title-page identity before being written as `Inbox/<citation-key>.pdf`.
   HTML landing/login pages and mismatched documents are rejected; a landing
   page's standard `citation_pdf_url` is followed once.
3. Sources are tried in this order: Unpaywall (only when
   `PAPER_LIBRARY_FETCH_EMAIL` is set at runtime; never store or print it),
   anonymous OpenAlex open-access locations, Semantic Scholar open-access
   copies, Crossref full-text links, arXiv preprints, and the DOI resolver.
   The helper does not use browser cookies, credentials, paywall bypasses, or
   authenticated scraping.
4. For records that stay unavailable, add `--browser` (with `--apply`, only
   unresolved records are opened). It opens each DOI's registered publisher
   page in the user's browser (`PAPER_LIBRARY_BROWSER`, else the system
   default), prefixed by `PAPER_LIBRARY_PROXY_PREFIX` for an institutional
   proxy. The user signs in and downloads; the fetcher never reads browser
   state or automates clicks. Keep both variables in the user's environment,
   never in public files.
5. Identify browser downloads with
   `./scripts/fetch-pending --match <download-directory>`, then repeat with
   `--apply`. Only PDFs whose first pages uniquely match one pending record's
   DOI or title are copied to `Inbox/<citation-key>.pdf`; originals are
   preserved. Ambiguous, duplicate, already staged, and text-less scanned PDFs
   are reported for manual staging.
6. Inspect every staged PDF, choose a reviewed canonical filename, and complete
   the ordinary `attach: true` manifest workflow. The fetcher intentionally
   does not edit `library.bib`, `main.typ`, or `Catalog.pdf`; the existing
   transactional intake performs those changes.

## Guardrails

- Do not use the script to recategorize or rename already cataloged items.
- An attachment manifest is the only routine update to an existing item.
- Keep root `main.typ`, root `library.bib`, the entire `Library/` tree,
  generated catalogs, `Inbox/`, reports, manifests, and citation sidecars
  private and Git-ignored. Do not force-add them.
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
