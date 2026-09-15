# Paper Library Agent Guide

## Scope

- These instructions apply to this directory and all descendants.
- This repository is a reusable research-document library and Typst catalog
  framework. A working clone also contains private, Git-ignored library data.
- Apply intake rules to newly added PDF, EPUB, and MOBI files. Do not
  mass-rename, recategorize, or reorganize existing items unless the user
  explicitly requests it.
- Metadata-only reading-list additions are allowed when explicitly requested.
  Represent them as pending downloads; do not fabricate local file paths or
  create placeholder media files. Applying a pending manifest still creates
  its empty destination topic directory beneath `Library/`.
- Ignore presentations, notes, generated previews, and temporary exports unless
  the task explicitly includes them.

## Public/private boundary

- Public seed files live in `templates/`; synthetic demonstrations live in
  `examples/`.
- Root `main.typ`, root `library.bib`, the entire root `Library/` tree,
  `Catalog.pdf`, `Inbox/`, JSON intake reports, intake manifests, and
  downloaded citation sidecars are private local state and must remain ignored
  by Git. Store canonical PDF/EPUB/MOBI files beneath `Library/`.
- If root `main.typ` or `library.bib` is absent, run `scripts/init-library`.
  It copies the public templates without overwriting existing local files and
  creates the ignored `Library/` media root when absent.
- Normal intake modifies only private root state and topical directories below
  `Library/`. Do not update the public templates to reflect a user's items or
  taxonomy.
- Never force-add an ignored file. Before any commit, push, release, or public
  export, run `scripts/public-repo audit`. Prefer publishing a tree made by
  `scripts/public-repo export <empty-directory>`.
- In a standalone exported tree, the audit may ignore only known generated
  Python and lint/test cache directories; every other unexpected path must
  still fail the public allowlist.
- Do not write names, email addresses, usernames, home-directory paths, account
  identifiers, credentials, or real bibliography records into public files.

## Sources of truth

- The private root `library.bib` is the canonical bibliography for local
  library items.
- The private root `main.typ` is the canonical local catalog source.
- Its quoted `catalog-updated` value is transactional private state. Every
  successful intake apply sets it to the current local calendar date; dry runs
  and rolled-back applies must leave it unchanged.
- `Catalog.pdf` is generated from `main.typ` and must remain in the library
  root so relative library-file links work.
- `Library/` is the fixed physical root for canonical media and topic
  directories. It is not part of the conceptual taxonomy or BibTeX keywords.
- RIS files produced by `scripts/export-bibliography` are private derived
  metadata, never a second source of truth.
- JSON reports produced by `scripts/intake-papers --report-json` are private
  provenance snapshots, never a bibliography or catalog source of truth.
- `templates/main.typ` and `templates/library.bib` are sanitized initialization
  seeds, not mirrors or backups of private state. Its `catalog-author` and
  `catalog-updated` defaults must remain empty.
- `examples/references.bib` is sample data used only by `examples/`.
- `docs/usage.md` is the public, comprehensive user guide. Keep it generic and
  update it whenever command behavior, manifest behavior, template invariants,
  or publication safeguards change.
- Per-item `.bib` or `.bibtex` sidecars are temporary intake evidence, not
  canonical metadata. Retain them by default during automated intake; remove
  them after consolidation only when sidecar cleanup is explicitly in scope.
- Every canonical record has exactly one `file` field. Its value is empty only
  for an explicitly requested, independently verified pending-download record.
- A record must identify at least one author or editor. Editor-only books are
  supported; do not invent an author to satisfy a schema.

For document intake, load and follow `paper-library-intake` when available. Its
workspace source is `skills/paper-library-intake/SKILL.md`. Use
`scripts/intake-papers` for reviewed manifest changes and
`scripts/validate-library.sh` as the final consistency gate.

For a requested reading list with no local documents, verify metadata against
the publisher and/or an authoritative registry, set `pending: true` in each
manifest item, and omit `source_file` and `canonical_filename`. Pending
records still require duplicate checks, classification, a stable citation key,
reviewed metadata, a dry run, transactional apply, validation, and compilation.
Applying the manifest creates `Library/<topic.path>/` even though no media file
exists yet.

When the document for a pending record arrives, inspect it and use an
`attach: true` manifest item with the existing citation key, `source_file`, and
`canonical_filename`. Do not submit it as a second record or edit the paired
BibTeX/catalog paths by hand. The dry run and apply update only the existing
empty `file` field and replace the catalog title's reference-section fallback
with a direct media link while preserving its key and metadata. Use
`scripts/intake-papers status --pending` (optionally `--json`) to list
outstanding records.

## Intake workflow

For each new PDF, EPUB, or MOBI item:

1. Confirm root `main.typ` and `library.bib` exist; otherwise run
   `scripts/init-library`.
2. If a document is outside the repository, run `scripts/stage-papers <path...>`
   and review its dry run, then repeat with `--apply`. This copies the explicit
   files into the ignored `Inbox/`, preserves the originals, verifies content,
   and uses the shared library lock.
3. Inspect the document's embedded metadata and title page to recover the
   official title, authors, publication identity, and DOI or ISBN. For PDFs,
   use `pdfinfo` and first-page `pdftotext`; for EPUB/MOBI files, use an
   available ebook reader or metadata tool.
4. Treat supplied or downloaded BibTeX as untrusted input. Reconcile it with the
   document and correct missing or conflicting fields.
5. Obtain missing metadata from authoritative web sources when needed, following
   the web-metadata policy below.
6. Determine the item's primary contribution and select the narrowest matching
   existing topic directory.
7. Choose a short, distinctive canonical filename and stable citation key.
8. Check for duplicate DOI, key, normalized title, local path, and file content.
9. Create one reviewed JSON manifest per destination topic as documented in
   `skills/paper-library-intake/references/intake-contract.md`.
   The preferred form also has a public machine-readable schema at
   `schemas/intake-manifest.schema.json`. Record optional `metadata_sources`
   HTTP(S) URLs when durable provenance is useful.
10. Run `scripts/intake-papers --manifest <path>` and review the dry run. Repeat
    `--manifest` to preflight several topics as one batch.
11. Apply with `--apply` only when every proposed move and metadata field is
    correct. The repeated-manifest batch is one transaction. Use
    `--delete-sidecars` only when sidecar removal is in scope.
12. When requested or useful for a complex batch, write a private provenance
    snapshot with `--report-json reports/<name>.json`; use `--force-report` only
    to replace a known report.
13. Confirm `scripts/validate-library.sh` passes and `Catalog.pdf` builds in
    the root.

The intake command takes an advisory `.paper-library.lock` for dry runs,
status reads, and applies. Do not bypass it; resolve a busy-library error or
use a reviewed finite `--lock-timeout`.

## Web metadata and BibTeX policy

Web metadata retrieval belongs to the intake agent, not the transactional
intake script. `scripts/fetch-pending` is the separate network-aware acquisition
helper for explicitly requested DOI-backed pending downloads; it may write only
verified PDFs to ignored `Inbox/`. `intake-papers` must remain deterministic,
offline, and limited to reviewed manifest data.

Run the fetcher without `--apply` first and prefer explicit `--key` selections.
Use `--all` only when the user requests the full pending set. Set
`PAPER_LIBRARY_FETCH_EMAIL` at runtime when Unpaywall lookup is desired; never
persist or print it. Do not capture browser cookies, automate institutional
credentials, bypass access controls, or treat an HTML landing/login page as a
document. Inspect each staged PDF before creating and applying its attachment
manifest. Inaccessible records remain pending.

Retrieve web metadata when the local document and supplied sidecar do not
provide a complete, internally consistent record, or when the user explicitly
requests a metadata-only reading list. Prefer sources in this order:

1. The publisher's article page or BibTeX export reached through the DOI.
2. Crossref metadata for a registered DOI.
3. The official arXiv record for a preprint.
4. An institutional repository or other authoritative primary record.
5. A secondary index only as a fallback, with important fields independently
   verified.

Never copy a web record blindly into `library.bib`. Verify at least the title,
author list, document type, publication year, venue, volume/issue, pages or
article number, and DOI or ISBN against the document or another authoritative
source. Do not invent unavailable fields. Store DOI values as bare identifiers
and add a DOI URL when appropriate.

For a pending record, the document itself is unavailable by definition.
Cross-check ambiguous fields with a second authoritative source and retain the
empty `file` value until the downloaded document has been inspected.

Keep downloaded web exports in `/tmp` or a clearly temporary intake location.
Do not let a publisher export, Crossref response, Zotero export, or other remote
record overwrite `library.bib`. Normalize verified values into the manifest,
then let the intake script update the canonical database transactionally.

## Canonical library-file naming

Use:

`Library/<TopicalDirectory>/<NormalizedTitle>.<pdf|epub|mobi>`

Rules:

- Start from the official title, preferring the document's title page when
  embedded metadata conflicts with it.
- Reduce it to the shortest distinctive form that remains unambiguous.
- Use ASCII PascalCase with no spaces and retain the source format using a
  lowercase `.pdf`, `.epub`, or `.mobi` extension. Intake does not convert
  between formats.
- Remove punctuation and separators. Replace `&` with `And`; treat `/`, `-`,
  and `:` as word boundaries.
- Preserve meaningful title numbers such as `QM9`, `OC20`, `UniMol2`, and
  `Reinvent4`.
- Preserve obvious acronyms and formulas such as `DFT`, `GNN`, `HER`, `ORR`,
  `CO2`, `TiO2`, `HfO2`, and `SE3`.
- Spell Greek letters and symbols in English before PascalCase conversion.
- Keep `Supplementary`, `Appendix`, `Dataset`, or `Review` when part of the
  actual document identity.
- Do not prepend authors, journals, years, DOI fragments, download-site names,
  or arXiv IDs unless disambiguation requires them.

Examples:

- `Attention Is All You Need` -> `AttentionIsAllYouNeed.pdf`
- `OC20: Benchmarking Open Catalyst 2020` ->
  `OC20BenchmarkingOpenCatalyst2020.pdf`
- `CO2 electroreduction trends` -> `CO2ElectroreductionTrends.pdf`
- `A Mathematical Theory of Communication` ->
  `AMathematicalTheoryOfCommunication.pdf`
- `Example Computational Chemistry Handbook` (EPUB) ->
  `ExampleComputationalChemistryHandbook.epub`
- `Example Molecular Modeling Monograph` (MOBI) ->
  `ExampleMolecularModelingMonograph.mobi`

## Citation keys and BibTeX records

- Use a stable lowercase ASCII key of the form
  `firstauthorYYYYshorttitle`, adding `a`, `b`, and so on only for collisions.
- Do not change a stable key merely because the display title or filename
  changes.
- Each item record must contain accurate bibliographic fields, one `keywords`
  field representing the full topic path, and one `file` field. Store a
  root-relative path beginning with `Library/` for a local item and an empty
  value for a pending download.
- Use the exact PascalCase topic components as comma-separated keywords; omit
  the physical `Library` prefix.
- Protect capitalization in BibTeX where required, while keeping the plain
  Unicode display title in `main.typ`.
- Do not store downloaded abstracts or redundant URLs unless they add ongoing
  value to the library.

## Classification

Choose the most specific existing directory matching the item's primary
contribution. When an item spans a method and an application, classify by the
main contribution rather than a secondary use case. Use `PeripheralEsoteric`
only for adjacent or foundational material outside the core domains.

Recognized top-level topics include:

- `DeepLearningForMaterialsScience`
- `HeterogeneousCatalysis`
- `LOHC`
- `Optimization`
- `PeripheralEsoteric`
- `QuantumChemistry`

Create a directory only when no existing directory is a clean fit, the topic is
broader than one item, and it is likely to recur or already has a nearby peer.
Use concise PascalCase topic names and prefer nesting beneath an existing
top-level topic. If the case is still ambiguous, use the closest existing
directory, explain the ambiguity, and suggest a future category.

## Catalog requirements

- Mirror the directory hierarchy with readable headings in `main.typ`.
- Add one official title and its citation key beneath the deepest topic
  heading. Link the title directly to its PDF, EPUB, or MOBI file when present;
  otherwise link it to the labeled References section without adding visible
  download-status text. Keep the bibliography target labeled `<references>`.
- Keep New Computer Modern Sans as the primary catalog font and the
  `korean-font` input as its Hangul fallback. Its default is
  `NanumGothicCoding`, the Korean sans-serif selected by this system's
  Fontconfig configuration; users may override it for another system.
- Keep `library.bib` as the single bibliography source for `main.typ`.
- Keep the private `catalog-author` value out of public files. Intake updates
  only `catalog-updated`, using a human-readable local date after preflight and
  inside the same transaction as the catalog changes.
- Generate the catalog with `typst compile main.typ Catalog.pdf` from the
  root.

## Reference-manager export

- Zotero can import the canonical BibLaTeX `library.bib` directly.
- For a portable Zotero/EndNote interchange file, run
  `scripts/export-bibliography`. It generates UTF-8 RIS, preserves citation
  keys and taxonomy keywords, and omits local attachment paths.
- The exporter is deterministic and offline. It must never edit `library.bib`
  or `main.typ`, and it must refuse to replace an output unless `--force` is
  explicit.
- Keep generated RIS files private and Git-ignored. Do not add them to public
  examples because they contain real bibliography records.

## Framework validation

- The validator uses the shared parser in `paperlib/`; do not add independent
  regex-based interpretations of BibTeX or catalog items.
- `Inbox/` is a private staging area, not canonical media. The validator ignores
  it when checking cataloged media, while intake and staging still use its files
  for duplicate-content checks.
- It must compare titles, citation multiplicity, topic markers, keywords,
  heading paths, attachment links, on-disk paths, media signatures, and hashes.
- Run `scripts/test` after framework changes. It is the local equivalent of the
  public CI workflow and includes unit tests, formatting/linting, shell checks,
  the privacy audit, and private validation when private root state exists.

## Duplicate and conflict handling

- Do not retain a second copy of the same item unless it is meaningfully
  different, such as a supplement or appendix.
- Prefer canonical naming when filenames differ only by punctuation or case.
- If two incoming items claim the same DOI but differ in content, stop and
  investigate rather than choosing one automatically.
- If a downloaded record conflicts with the title page, follow the title page
  unless another authoritative source establishes that the file is a reprint,
  correction, supplement, or different publication.

## Reporting

Report each original filename, format, canonical destination, citation key,
corrected metadata, new category, and sidecar disposition. State whether
validation and catalog compilation passed. If the transaction rolls back,
report the concrete failure and do not describe the intake as complete.

When a JSON intake report is produced, identify its private path and whether it
records a dry run or successful apply. Do not publish or force-add it.

For metadata-only work, report the citation keys and categories, the
authoritative sources used, that the file paths remain empty, and which empty
directories were created beneath `Library/`.

For publication work, also state whether the privacy audit passed and whether
the result was exported. Do not echo a detected secret or personal value; name
only the affected file and finding category.

The privacy audit checks both configured and reachable Git author/committer
identities. Use a provider no-reply address (or the documented synthetic test
domains) and a public-safe display name before creating public history.
