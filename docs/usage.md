# Paper Library User Guide

This guide explains how to initialize, operate, validate, back up, and publish
the Paper Library template. It is written for both direct command-line use and
agent-assisted document intake.

## Contents

- [The repository model](#the-repository-model)
- [Requirements](#requirements)
- [First-time setup](#first-time-setup)
- [Repository layout](#repository-layout)
- [Intake a library item](#intake-a-library-item)
- [Add a metadata-only reading list](#add-a-metadata-only-reading-list)
- [Attach a downloaded pending item](#attach-a-downloaded-pending-item)
- [Fetch accessible pending PDFs](#fetch-accessible-pending-pdfs)
- [Manifest reference](#manifest-reference)
- [What an apply operation does](#what-an-apply-operation-does)
- [Private intake reports](#private-intake-reports)
- [Export to Zotero or EndNote](#export-to-zotero-or-endnote)
- [Validate and build the catalog](#validate-and-build-the-catalog)
- [Use the Typst examples](#use-the-typst-examples)
- [Use an agent](#use-an-agent)
- [Publish the reusable framework safely](#publish-the-reusable-framework-safely)
- [Back up or migrate the private library](#back-up-or-migrate-the-private-library)
- [Command reference](#command-reference)
- [Troubleshooting](#troubleshooting)
- [Maintainer invariants](#maintainer-invariants)

## The repository model

The project deliberately separates reusable behavior from personal library
state.

| Reusable public framework | Private state in a working clone |
| --- | --- |
| Empty catalog and bibliography seeds in `templates/` | Populated root `main.typ` and `library.bib` |
| Synthetic demonstrations in `examples/` | The complete `Library/` media tree and retained sidecars |
| Intake and validation scripts | Generated `Catalog.pdf` and RIS exports |
| Agent instructions and intake skill | Inbox files, manifests, and intake reports |
| Privacy audit and export tooling | Local editor, agent, and credential files |

The public templates preserve the catalog configuration and insertion points
needed by the real workflow, but contain no real library records or file links.
The intake engine always works on the private root files. It never treats the
templates as the live catalog and never synchronizes private content back into
them.

The normal data flow is:

```text
external PDF/EPUB/MOBI file
          |
          v
   stage-papers -> Inbox/
          |
          v
document inspection + reviewed metadata
          |
          v
one JSON manifest per topic
          |
          v
multi-topic dry run
          |
          v
 transactional apply
    |          |           |
    v          v           v
library.bib  main.typ  private JSON report
    \          /
     +- validate/build -+
              |
              v
         Catalog.pdf
```

Judgment stays outside the transaction: a person or agent determines the
official title, metadata, classification, filename, and citation key. The
offline intake engine validates that reviewed plan and applies it consistently.

## Requirements

The workflow is Linux-first. Runtime commands require:

- Python 3.10 or newer;
- Bash;
- Typst; and
- Git for hooks, history auditing, and publication.

Poppler tools (`pdfinfo` and `pdftotext`) and Ripgrep (`rg`) are recommended for
document inspection. Framework development also requires Ruff and ShellCheck;
`scripts/test` checks for them. The public `ruff.toml` selects the intended lint
rules explicitly so local and hosted checks do not depend on Ruff's changing
defaults. The semantic validator itself is Python-based and does not depend on
GNU `find`, `sed`, or `sha256sum`.

Check the main tools before starting:

```sh
python3 --version
typst --version
git --version
rg --version
pdfinfo -v
pdftotext -v
fc-match 'sans-serif:lang=ko'
typst fonts | rg 'New Computer Modern Sans|NanumGothicCoding'
```

The empty Typst template compiles without third-party packages. Two optional
documents in `examples/` use pinned Typst packages and can need network access
on their first build.

An ebook metadata reader such as Calibre's `ebook-meta` is useful for EPUB and
MOBI review but is not required by the transaction engine. EPUB containers and
MOBI headers are validated with Python's standard library and built-in binary
checks.

## First-time setup

From the repository root, initialize the private catalog and install the local
Git hooks:

```sh
./scripts/init-library
./scripts/install-hooks
```

`init-library` copies:

- `templates/main.typ` to root `main.typ`; and
- `templates/library.bib` to root `library.bib`.

It also creates the ignored root `Library/` media directory when absent.

The public catalog seed keeps `catalog-author` and `catalog-updated` empty.
Set an author only in ignored root `main.typ`. Leave `catalog-updated` quoted;
the first successful intake apply fills it with that operation's local date,
which the catalog displays without a label. The public seed includes its
right-aligned Spanish epigraph above the generated topic hierarchy.

It is idempotent: if either destination exists, that file is retained without
modification. This makes the command safe to rerun and prevents a template from
overwriting a populated library.

`install-hooks` sets this clone's `core.hooksPath` to `.githooks`. The
pre-commit and pre-push hooks run the publication privacy audit. Git does not
activate repository-provided hooks automatically, so run this command once in
every new clone.

Verify setup without exposing ignored content:

```sh
git check-ignore main.typ library.bib Library/ExampleTopic/example.dat
git config --local --get core.hooksPath
./scripts/public-repo audit
```

The first command should print all three private paths, and the second should
print `.githooks`.

An initialized but empty bibliography is a valid starting point. The full
library validator intentionally reports "contains no entries" until at least
one item has been successfully added.

## Repository layout

```text
paper-library/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── docs/
│   └── usage.md
├── examples/
│   ├── references.bib
│   └── *.typ
├── paperlib/                 # shared BibTeX/catalog/media implementation
├── schemas/
│   └── intake-manifest.schema.json
├── scripts/
│   ├── export-bibliography
│   ├── init-library
│   ├── install-hooks
│   ├── intake-papers
│   ├── public-repo
│   ├── stage-papers
│   ├── test
│   └── validate-library.sh
├── skills/
│   └── paper-library-intake/
├── templates/
│   ├── library.bib
│   └── main.typ
├── tests/
│   └── test_*.py
├── main.typ                  # private, created locally
├── library.bib               # private, created locally
├── Catalog.pdf               # private, generated locally
├── exports/                  # private reference-manager exports
├── Inbox/                    # private staging area
├── reports/                  # private intake provenance
└── Library/                  # private, wholly Git-ignored media root
    └── TopicalDirectory/     # conceptual subject taxonomy
        └── Subtopic/
            └── CanonicalItemName.<pdf|epub|mobi>
```

Only the framework on the left side of the public/private model belongs in the
public repository. An ignored file is also not backed up by Git; arrange a
separate private backup for the working library.

## Intake a library item

### 1. Stage only the items being processed

For files already inside the repository, place the incoming PDF, EPUB, or MOBI
file and any citation export in the ignored `Inbox/`. For explicit paths
elsewhere on the machine, use the staging command:

```sh
./scripts/stage-papers /path/to/first.pdf /path/to/second.epub
./scripts/stage-papers /path/to/first.pdf /path/to/second.epub --apply
```

The first command is a dry run. The second copies verified media into `Inbox/`
without modifying the originals. Staging rejects symlinks, invalid media,
destination collisions, and duplicate content already present in the batch,
`Inbox/`, or `Library/`; it uses the same advisory lock as intake.

`Inbox/` is intentionally excluded from canonical orphan validation, so
unrelated staged documents may wait there while another batch is applied. They
still participate in duplicate-content checks. Only files beneath `Library/`
are canonical attachments. For several items going to one topic, include them
in one manifest; for several topics, prepare one manifest per topic and submit
all of them in the same intake command.

### 2. Recover and verify identity

For a PDF, inspect metadata and the first page:

```sh
pdfinfo Inbox/downloaded-paper.pdf
pdftotext -f 1 -l 1 Inbox/downloaded-paper.pdf -
sha256sum Inbox/downloaded-paper.pdf
```

For EPUB or MOBI, inspect embedded metadata and the rendered title page with an
available ebook reader or metadata tool. When Calibre is installed, for example:

```sh
ebook-meta Inbox/downloaded-book.epub
ebook-meta Inbox/downloaded-book.mobi
```

Use the visible title page when it conflicts with unreliable embedded metadata.
Check the document type, authors, editors, publication year, venue or publisher,
pagination or edition, and DOI or ISBN. Determine whether the file is an
article, preprint, book, correction, supplement, or another distinct object.

Search the existing private catalog before preparing an addition:

```sh
rg -n -i 'distinctive title fragment|bare-doi' library.bib main.typ
```

The engine also rejects duplicate citation keys, DOI values, normalized titles,
target paths, source paths, and file-content hashes. Human review is still
needed to distinguish versions such as a preprint and version of record.

### 3. Complete missing metadata

Downloaded BibTeX is evidence, not authoritative input. Prefer metadata in this
order:

1. publisher or DOI landing page;
2. Crossref record for a registered DOI;
3. official preprint record;
4. institutional repository;
5. a secondary index only as a verified fallback.

Compare remote values with the document. Do not invent missing fields. Keep
temporary downloads in `/tmp` or the ignored inbox, and never overwrite
`library.bib` with a web export.

Network retrieval belongs to the reviewing agent or person. The intake engine
has no network behavior and consumes only the reviewed JSON manifest.

### 4. Choose the topic, filename, and citation key

Choose the narrowest existing directory that matches the item's primary
contribution. Prefer an existing taxonomy over creating a category. Create a
new PascalCase topic only when no clean existing fit exists, the subject is
broader than one item, and the category is likely to recur.

The library-file destination follows:

```text
Library/TopicalDirectory/Subtopic/CompactDistinctiveTitle.<pdf|epub|mobi>
```

The manifest `topic.path` remains `TopicalDirectory/Subtopic`; the intake
engine adds the physical `Library/` prefix. BibTeX `keywords` likewise contain
only conceptual topic components, not `Library`.

Filename rules:

- use ASCII PascalCase and retain the source format with a lowercase `.pdf`,
  `.epub`, or `.mobi` extension;
- remove punctuation and separators;
- treat slashes, hyphens, and colons as word boundaries;
- replace `&` with `And`;
- preserve established formulas, acronyms, and title numbers;
- spell symbols and Greek letters in English;
- retain identity terms such as `Supplementary`, `Appendix`, `Dataset`, or
  `Review` when relevant;
- do not add authors, years, venues, DOI fragments, or download-site names
  unless required for disambiguation.

Intake renames files but does not convert between formats. Each catalog record
points to one canonical file, so alternate formats of the same bibliographic
work are not stored as duplicate records by this workflow.

Citation keys use stable lowercase ASCII:

```text
firstauthorYYYYshorttitle
```

Append `a`, `b`, and so on only when otherwise identical keys collide. Once a
key is in use, do not change it just because display wording or a filename
changes.

### 5. Generate and edit a manifest

Generate a starter outside the repository:

```sh
./scripts/intake-papers --write-template /tmp/paper-intake.json
```

The command refuses to overwrite an existing file. Edit the generated JSON
after completing the review. One manifest represents exactly one destination
topic but can contain multiple items for that topic. Readable headings must
identify their corresponding path components after spaces, punctuation, and
case are ignored. For example, `Philosophy of Science` is the natural heading
for `PhilosophyOfScience`; `Philosophy of Physics` is rejected during preflight.

A synthetic manifest looks like this:

```json
{
  "topic": {
    "path": "QuantumChemistry/ElectronicStructure/AnalyticalGradients",
    "headings": [
      "Quantum Chemistry",
      "Electronic Structure",
      "Analytical Gradients"
    ]
  },
  "items": [
    {
      "source_file": "Inbox/downloaded-book.epub",
      "canonical_filename": "DistinctiveOfficialTitle.epub",
      "citation_key": "author2026distinctivetitle",
      "entry_type": "book",
      "title": "The official display title",
      "bib_title": "The official display title with {Protected Acronyms}",
      "metadata_sources": [
        "https://doi.org/10.0000/synthetic-item",
        "https://api.crossref.org/works/10.0000%2Fsynthetic-item"
      ],
      "fields": {
        "author": "Author, First and Researcher, Second",
        "publisher": "Publisher Name",
        "date": "2026",
        "edition": "2",
        "isbn": "978-0-00-000000-0"
      },
      "sidecars": ["Inbox/downloaded-citation.bib"]
    }
  ]
}
```

See the authoritative
[`intake-contract.md`](../skills/paper-library-intake/references/intake-contract.md)
for the concise contract. Editors and JSON tooling can use the public
[`intake-manifest.schema.json`](../schemas/intake-manifest.schema.json). The
schema describes the preferred `items` form; the intake engine remains the
final gate because it also checks current private state and media contents.

### 6. Run and review the dry run

```sh
./scripts/intake-papers --manifest /tmp/paper-intake.json
```

For several destination topics, repeat `--manifest`. All manifests are checked
against current library state and one another before any apply can begin:

```sh
./scripts/intake-papers \
  --manifest /tmp/quantum-chemistry.json \
  --manifest /tmp/peripheral-esoteric.json
```

Without `--apply`, no library file is changed. Review every printed value:

- source and destination paths;
- detected source format;
- citation key;
- official display title;
- DOI, when present;
- metadata provenance URLs, when present;
- sidecar disposition;
- topic path and readable heading hierarchy;
- the `Library/<topic.path>/` directory that apply will create if absent;
- output catalog name.

Treat any discrepancy as a manifest problem. Correct the JSON and rerun the dry
run; do not weaken a validation rule to force an uncertain record through.

### 7. Apply the reviewed plan

```sh
./scripts/intake-papers --manifest /tmp/paper-intake.json --apply
```

The multi-topic form is also one transaction:

```sh
./scripts/intake-papers \
  --manifest /tmp/quantum-chemistry.json \
  --manifest /tmp/peripheral-esoteric.json \
  --apply
```

By default, listed sidecars remain in place as intake evidence. Remove them only
when cleanup is explicitly desired:

```sh
./scripts/intake-papers \
  --manifest /tmp/paper-intake.json \
  --apply \
  --delete-sidecars
```

To use another root-level output filename:

```sh
./scripts/intake-papers \
  --manifest /tmp/paper-intake.json \
  --output ResearchCatalog.pdf \
  --apply
```

The custom output must be a filename ending in `.pdf`, not a path containing
directories.

To retain a private, machine-readable record, add a report to either the
dry-run or apply command:

```sh
./scripts/intake-papers \
  --manifest /tmp/paper-intake.json \
  --report-json reports/paper-intake.json
```

An existing report is not replaced unless `--force-report` is explicit.

### 8. Review the result

After a successful apply:

- each source file has moved to one canonical path beneath `Library/`;
- `library.bib` has one normalized record per item;
- generated `keywords` match the conceptual topic path without `Library`;
- generated `file` values are root-relative PDF, EPUB, or MOBI paths beneath
  `Library/`;
- `main.typ` contains matching headings, links, and citation keys;
- validation has passed; and
- the root catalog PDF has been rebuilt.

Open the generated catalog and follow a library-file link as a final visual
check.

## Add a metadata-only reading list

Use pending mode only when a person explicitly requests recommendations before
obtaining the documents. It is not a shortcut for skipping inspection of an
available file.

Research each candidate before creating the manifest. Prefer the publisher's
record, then Crossref, an official preprint record, or an institutional
repository. Verify the title, complete author list, publication type, year,
venue, volume and issue, pages or article number, and DOI or ISBN. If an
important field conflicts, resolve it with another authoritative source rather
than guessing.

A synthetic pending manifest omits all file properties:

```json
{
  "topic": {
    "path": "QuantumChemistry/ElectronicStructure/ExampleTheory",
    "headings": [
      "Quantum Chemistry",
      "Electronic Structure",
      "Example Theory"
    ]
  },
  "items": [
    {
      "pending": true,
      "citation_key": "example2026foundational",
      "entry_type": "article",
      "title": "A Synthetic Foundational Study",
      "metadata_sources": [
        "https://doi.org/10.0000/synthetic-foundational"
      ],
      "fields": {
        "author": "Example, Ada and Researcher, Ben",
        "journaltitle": "Journal of Synthetic Examples",
        "date": "2026",
        "volume": "12",
        "number": "3",
        "pages": "101--120",
        "doi": "10.0000/synthetic-foundational"
      }
    }
  ]
}
```

Run the same dry-run and apply commands used for local documents. The plan
prints `FILE PENDING DOWNLOAD`. A successful apply:

- adds the verified record to `library.bib` with `file = {}`;
- adds its title and citation key to `main.typ`, linking the title to the
  References section;
- adds no visible pending-status label to the catalog;
- creates the empty `Library/<topic.path>/` destination directory but no
  placeholder media file; and
- validates and rebuilds the catalog transactionally.

Empty file values are intentional state, not broken links. Duplicate key, DOI,
and normalized-title checks still apply.

List outstanding downloads at any time:

```sh
./scripts/intake-papers status --pending
./scripts/intake-papers status --pending --json
```

The JSON form reports each key, title, DOI, topic components, and expected
destination directory without modifying the library.

## Attach a downloaded pending item

Inspect the downloaded document exactly as in normal intake and confirm it is
the same work. Preserve the existing key and reviewed metadata. Use an
attachment manifest for the record's existing topic:

```json
{
  "topic": {
    "path": "QuantumChemistry/ElectronicStructure/ExampleTheory",
    "headings": [
      "Quantum Chemistry",
      "Electronic Structure",
      "Example Theory"
    ]
  },
  "items": [
    {
      "attach": true,
      "citation_key": "example2026foundational",
      "source_file": "Inbox/downloaded-foundational.pdf",
      "canonical_filename": "SyntheticFoundationalStudy.pdf"
    }
  ]
}
```

Run the ordinary dry run, inspect the `ATTACH` source and destination, then
apply it. The transaction moves the file, fills the existing empty BibTeX
`file` field, retains the title's References link, and adds a bracketed direct
media link. It then validates and rebuilds the catalog. It does not create a
second record or change metadata. An attachment is rejected if its key is
absent, is no longer pending, appears ambiguously in the catalog, or belongs to
another topic.

## Fetch accessible pending PDFs

The optional network helper discovers PDFs for existing DOI-backed pending
records. Its default mode queries metadata but does not write files:

```sh
./scripts/fetch-pending --key example2026foundational
./scripts/fetch-pending --key example2026foundational --apply
```

Repeat `--key` for a reviewed group. Use `--all` only when intentionally trying
the complete pending set. `--apply` tests candidates in order and writes a
successful result as `Inbox/<citation-key>.pdf`. It accepts only bounded,
parseable PDFs whose first pages match the expected DOI or title/author;
publisher landing pages, login HTML, mismatched works, and oversized responses
are rejected.

Candidates are tried in this order:

1. Unpaywall, when an identifying email is supplied at runtime;
2. anonymous OpenAlex open-access locations;
3. Semantic Scholar open-access copies, often institutional repositories;
4. Crossref full-text links from the publisher;
5. an arXiv preprint recorded by Semantic Scholar; and
6. the DOI resolver.

When a candidate returns an HTML landing page that declares the standard
`citation_pdf_url` metadata, that PDF link is tried once. Unpaywall requires an
identifying email; enable it for the current process without writing it to a
file:

```sh
PAPER_LIBRARY_FETCH_EMAIL="$CONTACT_EMAIL" \
  ./scripts/fetch-pending --key example2026foundational --apply
```

The value is sent only to APIs that accept or require it and is not printed or
stored. The helper does not use browser cookies, institutional credentials, or
access-control workarounds. Many publisher sites reject scripted requests even
for free articles, so subscription and publisher-hosted items often remain
unavailable to `--apply`.

### Download the rest through your browser

`--browser` hands each unresolved record's registered publisher page to your
own browser, where you can sign in and download it. Combined with `--apply`, it
opens only the records that could not be downloaded automatically; alone, it
opens every selected record not already staged in `Inbox/`:

```sh
./scripts/fetch-pending --all --apply --browser
```

Two optional runtime variables control the handoff:

| Variable | Purpose | Example |
| --- | --- | --- |
| `PAPER_LIBRARY_BROWSER` | Browser command; each URL is appended | `firefox --new-tab` |
| `PAPER_LIBRARY_PROXY_PREFIX` | Institutional proxy prefix placed before each publisher URL | `https://proxy.example.org/login?url=` |

Without `PAPER_LIBRARY_BROWSER`, the system default browser is used. Keep both
values in your shell environment, not in repository files. The fetcher only
opens URLs: sign-in, access decisions, and downloads remain yours, and it never
reads browser profiles or cookies. Open tabs in modest `--key` batches to
respect publisher and proxy usage terms.

Once the PDFs are downloaded, identify them against the pending records:

```sh
./scripts/fetch-pending --match ~/Downloads
./scripts/fetch-pending --match ~/Downloads --apply
```

`--match` accepts PDF files or directories (not recursively) and works
offline. A PDF is copied to `Inbox/<citation-key>.pdf` only when its first
pages match exactly one pending record by DOI or title; the original stays
where it was. Ambiguous, duplicate, already staged, and unreadable PDFs are
reported instead. Scanned PDFs without a text layer cannot be identified
automatically; check their title pages and stage them with
`scripts/stage-papers`.

Fetching deliberately stops at `Inbox/`. Inspect each PDF and create the normal
reviewed `attach: true` manifest with a canonical filename. The attachment
transaction then moves the document, updates the empty `file` field and catalog
link, validates the library, and rebuilds `Catalog.pdf`.

## Manifest reference

Top-level keys:

| Key | Required | Meaning |
| --- | --- | --- |
| `topic` | yes | One destination topic and its readable headings |
| `items` | yes | A non-empty array of documents for that topic |

`topic` keys:

| Key | Required | Rules |
| --- | --- | --- |
| `path` | yes | Slash-separated ASCII PascalCase components |
| `headings` | yes | One safe, readable heading per path component |

Item keys:

| Key | Required | Rules |
| --- | --- | --- |
| `attach` | no | Set to `true` only when connecting a document to an existing pending key |
| `pending` | no | Set to `true` only for a verified metadata-only record |
| `source_file` | unless pending | Regular, non-symlink PDF, EPUB, or MOBI inside the library root |
| `canonical_filename` | unless pending | ASCII PascalCase with a matching lowercase supported extension |
| `citation_key` | yes | Lowercase `firstauthorYYYYshorttitle` form |
| `entry_type` | no | Letters only; defaults to `article` |
| `title` | yes | Plain Unicode display title for `main.typ` |
| `bib_title` | no | BibTeX title with capitalization braces if needed |
| `metadata_sources` | no | Unique HTTP(S) URLs used to verify metadata; retained only in reports |
| `fields` | yes | Reviewed BibTeX fields |
| `sidecars` | no | Array of `.bib` or `.bibtex` files inside the root |

`items` and `source_file` are the preferred names. Existing manifests using the
legacy `papers` collection and PDF-only `source_pdf` key remain accepted. A
manifest must not provide both forms of either alias.

A pending item must omit `source_file`, `source_pdf`, and
`canonical_filename`. A local item must omit `pending` or set it to
`false`, and it requires the normal file properties.

An attachment item contains only `attach: true`, the existing `citation_key`,
`source_file`, `canonical_filename`, and optional `sidecars`. It must use the
record's current topic. Do not repeat title or bibliographic fields: the
transaction deliberately preserves them. Unknown properties at every manifest
level are rejected. An optional top-level `$schema` annotation is accepted.

`metadata_sources` may be used on a normal, pending, or attachment item. URLs
must be non-empty HTTP(S) locations without embedded credentials. They are
printed in the plan and copied into an optional private intake report, but are
not written to `library.bib` or `main.typ`. Avoid signed URLs, private query
parameters, or any provenance location that itself contains sensitive data.

Field rules:

- at least one of `author` or `editor` is required;
- either `date` or `year` is required;
- dates use `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`, and a supplied `year` must
  agree with `date`;
- `title`, `keywords`, and `file` are reserved and cannot appear in `fields`;
- field names begin with a letter and contain only letters, numbers,
  underscores, or hyphens;
- field values are normalized to single spaces and must have balanced braces;
- a DOI can be supplied bare, with a `doi:` prefix, or as a DOI URL;
- the engine stores a bare DOI and adds its URL when `url` is absent;
- `keywords` and `file` are generated. Local items receive the reviewed
  `Library/<topic.path>/<canonical_filename>` destination; pending items
  receive an empty `file` value.

The source and canonical extensions must match; renaming an EPUB to `.mobi`,
for example, is rejected. Authored and editor-only books can use
`entry_type: book`.

All resolved source and sidecar paths must remain within the library root.
Manifests themselves may live outside it, which is why `/tmp` is recommended.

## What an apply operation does

An apply is transactional across every repeated `--manifest` argument:

1. an advisory `.paper-library.lock` is acquired so concurrent commands cannot
   overwrite one another;
2. preflight validates every manifest in command-line order and checks both
   current-state and cross-manifest duplicates;
3. current `library.bib`, `main.typ`, output catalog PDF, and optionally deleted
   sidecars are snapshotted;
4. every requested `Library/<topic.path>/` is created, even for pending-only
   manifests, and local library files are moved when present;
5. new BibTeX records are rendered under a `% Topic:` section, or an attachment
   updates the parsed `file` value of its existing record;
6. catalog headings with the same normalized identity are found, or the
   supplied naturally cased headings are created before the bibliography block;
7. every title links to the References section; local items also receive a
   `[PDF]`, `[EPUB]`, or `[MOBI]` attachment link, and citation keys are
   inserted without visible pending-status labels;
8. the quoted private `catalog-updated` value is set to the current local date;
9. writes to the two text sources are atomic;
10. `scripts/validate-library.sh` runs;
11. Typst compiles a temporary catalog, which atomically replaces the requested
   output only after success;
12. explicitly selected sidecars are removed;
13. a requested applied JSON report is written with owner-only permissions
    after validation and compilation have passed.

If a move, write, validation, build, or cleanup step fails, the engine restores
the snapshotted files, moves library files back, removes newly created empty
directories, and reports the concrete error. Treat a rollback message as an
incomplete intake and resolve the underlying cause before retrying.

The lock also covers dry runs and pending-status reads. It waits five seconds
by default; `--lock-timeout SECONDS` accepts a finite non-negative override.
The script is designed for new intake and pending attachment, not bulk
recategorization or mass-renaming of existing items.

## Private intake reports

`--report-json PATH` writes deterministic UTF-8 JSON for the reviewed run. A
dry-run report has `status: "dry-run"` and leaves the library unchanged. An
apply report has `status: "applied"` and records that validation and catalog
compilation passed. It includes:

- every manifest and topic;
- action, citation key, title, normalized fields, and pending state;
- source and destination paths, detected format, and SHA-256 hash;
- `metadata_sources` and sidecar disposition; and
- aggregate item counts, the requested catalog output, and the proposed or
  applied last-updated date.

Reports may be written outside the repository when their parent directory
already exists. A report inside the repository must be beneath `reports/` or
end in `.intake-report.json`, ensuring that the repository's ignore rules cover
it. The command refuses symlink outputs, collisions with intake files, and
existing reports unless `--force-report` is supplied. Symlinked parent
directories are refused as well. Reports contain private
bibliographic and filesystem data, are created with mode `0600`, must not be
force-added, and are not a source of truth. During apply, report creation joins
the same rollback boundary as document moves and catalog updates.

## Export to Zotero or EndNote

The canonical `library.bib` is BibLaTeX and can be imported directly by Zotero.
Use the RIS exporter when you want one portable metadata file accepted by both
Zotero and EndNote:

```sh
./scripts/export-bibliography
```

The default destination is the ignored private file `exports/library.ris`.
The exporter:

- reads `library.bib` without modifying it;
- writes UTF-8 RIS with CRLF line endings;
- maps articles, books, chapters, conference papers, theses, reports, and other
  common BibTeX entry types to RIS types;
- preserves citation keys as `ID`, authors and editors, publication fields,
  DOI/URL values, and taxonomy keywords;
- includes both local and pending records; and
- omits every BibTeX `file` value so machine-specific attachment paths are not
  leaked or misinterpreted.

The output is created with owner-only permissions and is never a source of
truth. Re-export after changing `library.bib`. Existing output is protected;
replace it explicitly with:

```sh
./scripts/export-bibliography --force
```

Choose another `.ris` destination with `--output`. Relative paths are resolved
from the library root; absolute paths are also accepted:

```sh
./scripts/export-bibliography --output /tmp/paper-library.ris
```

In Zotero, use **File → Import → A file** and select either `library.bib` or the
RIS export. In EndNote, import the RIS file with the **Reference Manager (RIS)**
import option. Review imported records in a temporary library before merging
them into an established reference-manager library.

RIS is a metadata interchange format, not an attachment archive. Add local
documents through the reference manager after import if attachments are
desired. Generated `.ris` files and the root `exports/` directory are ignored
by Git and must remain private because they contain the real bibliography.

Official format references: [Zotero standardized-format import](https://www.zotero.org/support/kb/importing_standardized_formats)
and [EndNote RIS import](https://docs.endnote.com/docs/endnote/2025/v1/windows/en/content/08import/import_options.htm).

## Validate and build the catalog

Run the complete consistency gate from the repository root:

```sh
./scripts/validate-library.sh
```

It checks:

- a structurally valid bibliography with unique, correctly formed keys, DOI
  values, and normalized titles;
- one title, author or editor, canonical date/year, topic marker, `keywords`,
  and `file` field per record;
- exact agreement among `% Topic:` markers, keyword paths, physical topic
  directories, and readable Typst heading hierarchies;
- exactly one catalog item per key, matching BibTeX and catalog titles, and no
  duplicate citations or links hidden by set deduplication;
- a References-section title link for every record, plus an exact,
  correctly-labeled media link for every local record and no attachment or
  visible status label for pending records;
- canonical, safe, non-symlink paths rooted at `Library/` and an exact match
  between bibliography paths and all on-disk PDF/EPUB/MOBI files;
- actual PDF, EPUB, and MOBI signatures/containers on every validation run;
- unique file content by SHA-256;
- exactly one `library.bib` selection in `main.typ`; and
- successful Typst compilation.

Catalog-link validation accepts both compact one-line `#link(...)` calls and
the equivalent multiline form produced by Typst formatters.

Compile manually when needed:

```sh
typst compile main.typ Catalog.pdf
```

Watch for changes:

```sh
typst watch main.typ Catalog.pdf
```

Use another supported citation style without editing the source:

```sh
typst compile --input style=ieee main.typ Catalog.pdf
```

The catalog uses New Computer Modern Sans as its primary face, followed by the
`korean-font` input for Hangul. On the originating system,
`fc-match 'sans-serif:lang=ko'` selects `NanumGothicCoding`, so that is the
template default. To match another system, identify its Korean sans-serif and
override the fallback without editing the source:

```sh
typst compile \
  --input korean-font="Noto Sans CJK KR" \
  main.typ Catalog.pdf
```

The selected family must appear in `typst fonts`. Keep the output in the
repository root so its relative links to local PDF, EPUB, and MOBI files resolve
correctly.

Catalog titles always open the References section. A local item additionally
shows `[PDF]`, `[EPUB]`, or `[MOBI]`, which opens its relative attachment. A
PDF viewer cannot portably detect a failed external-file action and redirect
automatically. Therefore, when a shared `Catalog.pdf` has no accompanying
`Library/` tree, the viewer may report `File not found`; return to the catalog,
select the linked title or citation, and follow the DOI or URL in References.

The optional byline is controlled by private root variables:

```typst
#let catalog-author = "Your display name"
#let catalog-updated = ""
```

Do not add a personal author to `templates/main.typ`. The intake engine requires
exactly one quoted `catalog-updated` declaration and updates it only during a
successful `--apply`. A dry run calculates and prints the proposed date but
does not modify `main.typ`; a failed apply restores its prior value.

Manual edits to `main.typ` or `library.bib` are possible, but both must remain
in lockstep. Run the validator immediately afterward. For routine additions,
the reviewed manifest workflow is safer.

Run the complete developer gate after changing framework code:

```sh
./scripts/test
```

It runs explicit test discovery, Ruff lint and format checks, ShellCheck, the
privacy audit, and private validation when initialized state exists. Tests
cover shared BibTeX parsing, RIS export, transactional formats, pending
attachment/status, editor-only books, locking, semantic catalog drift, media
revalidation, history auditing, and the configured font fallback.

## Use the Typst examples

All example documents read only `examples/references.bib`. They never read the
private root bibliography.

```sh
typst compile --root . examples/first-citation.typ first-citation.pdf
typst compile --root . examples/citation-cheatsheet.typ citation-cheatsheet.pdf
typst compile --root . examples/reading-notes.typ reading-notes.pdf
typst compile --root . examples/chapter-bibliographies.typ chapters.pdf
```

The resulting PDFs are ignored by Git. `bibliography-inventory.typ` and
`with-backreferences.typ` use optional pinned packages and may need network
access the first time Typst resolves them.

## Use an agent

`AGENTS.md` is the authoritative repository policy for compatible coding
agents. `CLAUDE.md` directs Claude Code to the same policy. The reusable intake
skill lives at `skills/paper-library-intake/`.

A useful request is:

```text
Use $paper-library-intake to inspect and intake the new PDF, EPUB, or MOBI files
in Inbox.
Recover missing metadata from authoritative sources, show the dry-run plan, and
apply it only after resolving every conflict.
```

The agent should:

1. read the skill and intake contract;
2. inspect the actual document before trusting a sidecar;
3. browse only when local metadata is incomplete or conflicting;
4. choose classification, filename, and citation key with reviewable judgment;
5. prepare a manifest;
6. run the dry run;
7. apply only a correct plan; and
8. report moves, metadata corrections, sidecar disposition, validation, and
   catalog build status.

The skill intentionally delegates web metadata retrieval to the agent. The
transaction script remains offline so a remote record cannot silently mutate
the local library.

## Publish the reusable framework safely

### Understand the protection layers

`.gitignore` excludes the populated root catalog, every file beneath
`Library/` regardless of type, all PDF/EPUB/MOBI files, all non-example BibTeX,
RIS exports, inbox data, intake reports, manifests, the advisory lock, the
private audit terms file, caches, local tool configuration, and common secret
files.

The stronger gate is:

```sh
./scripts/public-repo audit
```

In a Git working tree, it audits:

- tracked files;
- unignored untracked files;
- staged index blobs; and
- every path/blob pairing reachable from existing Git history.

It also checks the effective configured author/committer identities when Git
can resolve them, plus every author/committer identity already reachable in
history.

It enforces an exact public path allowlist, rejects PDF/EPUB/MOBI media and
non-example bibliographies, rejects symlinks, NUL-containing binary content,
oversized public files, and credential-like paths, and scans text for home
paths, email addresses, the current non-generic username, private keys, and
common token formats. It also rejects a real BibTeX record, library-file link,
or citation key copied into the public seed templates, plus any non-empty
catalog author or last-updated value in `templates/main.typ`. Reachable commit
author and committer emails must be provider no-reply addresses (the reserved
`example.invalid` and `example.test` domains are accepted for synthetic tests),
and the local username cannot be used as the Git display name.

It also rejects institutional proxy links: EZproxy and library-proxy hosts,
OCLC and OpenAthens proxy services, N2S-style library proxy paths, and
`…/login?url=` prefixes. Reserved documentation hosts such as `example.org`
and `.test` domains remain allowed for examples.

For identifying words no pattern can know, such as your institution, lab, or
city, list them in the Git-ignored `.paper-library-private-terms` file at the
repository root, one per line. Lines beginning with `#` are comments. Each term
must be at least three characters and is matched case-insensitively as literal
text in public files, staged blobs, and reachable history. `public-repo export`
applies the source repository's terms to the exported tree as well.

The audit reports finding categories and paths, not matched secret values. It
fails closed: when adding an intentional public file, also add its exact
relative path to `PUBLIC_FILES` in `scripts/public-repo`.

In a standalone public export with no Git metadata, generated Python, Ruff,
pytest, and mypy cache directories are excluded from the publishable surface so
`scripts/test` can run there. Other unexpected files still fail the allowlist.

The audit is a strong guardrail, not proof of anonymity. It cannot decide
whether an otherwise ordinary display name or prose fact is identifying.
Review the final public tree and configure a public-safe Git display name and
provider-issued no-reply address before committing.

Configure those values for this clone with `git config --local user.name` and
`git config --local user.email`, supplying your chosen public display name and
provider-issued no-reply address as the final arguments. The audit never prints
the rejected identity value.

### Audit the current repository

```sh
./scripts/public-repo audit
git status --short
```

Never use `git add -f` for an ignored library file. The audit rejects such a
file even if it was forced into the index.

### Export the safest publication tree

Use an absent or empty directory outside the source repository:

```sh
./scripts/public-repo export /tmp/paper-library-template
```

The exporter audits the source, copies only exact allowlisted files without
`.git`, and audits the destination again. It refuses a non-empty or
in-repository destination and never exports a symlinked public source file.

After reviewing the export, a generic initial publication sequence is:

```sh
cd /tmp/paper-library-template
git init -b main
./scripts/install-hooks
git add .
./scripts/public-repo audit
git commit -m 'Initial public template'
git remote add origin YOUR_PUBLIC_REPOSITORY_URL
git push -u origin main
```

Choose and add a license before publishing. This template does not guess the
owner's licensing decision.

The exporter is not a history scrubber. If the audit reports a private
historical blob, stop. Work from a backup and either reconstruct a clean
repository from reviewed public files or use appropriate history-rewrite
tooling with care. Re-run the audit before connecting or pushing any public
remote.

## Back up or migrate the private library

Git-ignored means private from this public repository, not backed up. Use a
separate private or encrypted backup for:

- root `main.typ` and `library.bib`;
- the complete root `Library/` tree;
- any retained intake evidence you want to preserve.

To migrate to a fresh clone:

1. clone the public framework;
2. copy the private root sources and complete `Library/` tree from the trusted
   backup;
3. do not copy an old `.git` directory;
4. run `scripts/install-hooks`;
5. confirm the private files are ignored;
6. run `scripts/validate-library.sh`; and
7. rebuild `Catalog.pdf`.

If no private catalog exists yet, use `scripts/init-library` instead of copying
files.

## Command reference

| Command | Purpose | Mutates library data? |
| --- | --- | --- |
| `scripts/init-library` | Create missing private root sources and `Library/` | Creates missing files/directories only |
| `scripts/install-hooks` | Select checked-in Git hooks for this clone | Changes local Git config only |
| `scripts/export-bibliography` | Export private metadata to `exports/library.ris` | Writes derived RIS output only |
| `scripts/fetch-pending --key KEY [--apply]` | Discover or stage an accessible pending PDF | Writes only ignored `Inbox/` with `--apply` |
| `scripts/fetch-pending --key KEY --browser` | Open the record's publisher page in your browser | No |
| `scripts/fetch-pending --match PATH... [--apply]` | Identify browser-downloaded PDFs and stage unique matches | Writes only ignored `Inbox/` with `--apply` |
| `scripts/export-bibliography --output PATH --force` | Replace a selected RIS export | Replaces derived RIS output only |
| `scripts/stage-papers PATH...` | Validate and print a plan to copy external media into `Inbox/` | No |
| `scripts/stage-papers PATH... --apply` | Copy verified media into `Inbox/` while preserving originals | Adds private inbox copies |
| `scripts/intake-papers --write-template PATH` | Write a starter JSON manifest | Writes only the requested new path |
| `scripts/intake-papers status --pending [--json]` | List records awaiting documents | No |
| `scripts/intake-papers --manifest PATH` | Validate and print an intake plan | No |
| repeated `--manifest PATH` arguments | Preflight or apply several topics as one transaction | Follows dry-run or apply mode |
| `scripts/intake-papers --manifest PATH --apply` | Apply, validate, and build transactionally | Yes |
| `scripts/intake-papers --manifest PATH --report-json PATH` | Write a private dry-run provenance report | Writes only the report |
| `scripts/intake-papers --manifest PATH --apply --report-json PATH` | Apply and write a private success report after validation/build | Yes |
| attachment manifest with `--apply` | Connect a document to one pending record | Yes |
| `scripts/intake-papers --manifest PATH --apply --delete-sidecars` | Apply and remove listed sidecars after success | Yes |
| `scripts/intake-papers --manifest PATH --output NAME.pdf --apply` | Build a custom root-level catalog filename | Yes |
| `scripts/validate-library.sh` | Check the complete private library and Typst build | No persistent output |
| `scripts/test` | Run the complete framework and private-state gate | No persistent output |
| `scripts/public-repo audit` | Audit publishable files, index, and history | No |
| `scripts/public-repo export DIRECTORY` | Create an audited public-only tree | Writes only the destination |

Use built-in help for current command syntax:

```sh
./scripts/export-bibliography --help
./scripts/stage-papers --help
./scripts/intake-papers --help
./scripts/intake-papers status --help
./scripts/public-repo --help
./scripts/public-repo export --help
```

## Troubleshooting

### `the library root must contain library.bib and main.typ`

Run `./scripts/init-library`. If a private backup exists, restore it instead of
initializing empty files.

### `library.bib contains no entries`

This is expected immediately after initialization. Intake the first item; the
apply transaction validates after inserting its record.

### `library files on disk and BibTeX file fields differ`

Review the reported missing or uncataloged paths. A common cause is an unrelated
PDF, EPUB, or MOBI file placed directly outside `Inbox/` and `Library/`, a
manually moved canonical file, a stale `file` field, or an item omitted from the
manifest. Staged files inside `Inbox/` are intentionally ignored by canonical
orphan validation.

### `refusing to overwrite existing report without --force-report`

Choose a new private report path, or inspect the existing report and repeat the
command with `--force-report` only when replacing it is intentional.

### Duplicate DOI, title, key, path, or content

Do not work around the check by changing arbitrary metadata. Determine whether
the incoming document is an existing item, a distinct version, a correction,
or supplementary material. Only genuinely distinct documents belong as
separate records.

### PDF, EPUB, or MOBI format validation fails

The download may be an HTML error page, a corrupt file, an EPUB without the
required uncompressed `mimetype` entry and container descriptor, or a file
without the MOBI PalmDB header. Obtain a valid file and rerun the dry run. Do
not change an extension as a substitute for format conversion.

### `destination already exists`

Inspect the existing file and catalog. It can indicate a duplicate, a filename
collision, or an incomplete earlier manual operation. Do not overwrite it
blindly.

### `attachment target is not pending`

The key already has a non-empty `file` field or was attached by another
operation. Run `scripts/intake-papers status --pending` and inspect the current
record; do not create a duplicate item.

### `library is busy`

Another intake or status command holds `.paper-library.lock`. Let it finish and
retry. Increase `--lock-timeout` only when the other operation is known to be
healthy; do not delete or bypass an actively held lock.

### `main.typ has no #bibliography block`

Restore the required unindented `#bibliography(` anchor from
`templates/main.typ`, preserving private catalog content above it.

### Typst reports a missing font

Confirm `typst fonts` lists New Computer Modern Sans and the configured Korean
fallback. Run `fc-match 'sans-serif:lang=ko'` to identify the system Korean
sans-serif, then pass its Typst family name through `--input korean-font=...`.
If adopting a new shared default, update both the local and public template
configuration.

### The apply operation rolls back

Read the first concrete validation or compilation error, confirm the original
library file and root sources were restored, fix the manifest or environment,
rerun the dry run, and only then apply again.

### The privacy audit says a path is outside the allowlist

If it is private, leave it ignored or remove it from the index. If it is a new,
intentional public framework file, review its content and add its exact path to
`PUBLIC_FILES` in `scripts/public-repo`.

### The privacy audit reports Git history

Ignoring or deleting the current file does not remove an old committed blob.
Do not push. Reconstruct a clean repository or carefully rewrite history from a
backup, then verify the complete history with the audit.

### The privacy audit reports a Git identity

Set a public-safe clone-local display name and provider no-reply address before
committing. If the finding is historical, changing configuration is not
enough: reconstruct or carefully rewrite the unpublished history and audit it
again. Identity values are intentionally omitted from diagnostics.

### Hooks do not run

Run `./scripts/install-hooks` and verify:

```sh
git config --local --get core.hooksPath
```

The result should be `.githooks`.

### Bibliography export already exists

The exporter does not overwrite by default. Review the existing RIS file, then
rerun with `scripts/export-bibliography --force` or select another `.ris` path
with `--output`.

### Public-repository export destination is rejected

Choose a directory outside this repository that is absent or completely empty.
The exporter never merges into an existing tree.

## Maintainer invariants

Preserve these rules when extending the framework:

- `templates/main.typ` stays feature-equivalent to the live catalog skeleton but
  contains no real topic headings, citations, or library-file links;
- its `#bibliography(` anchor remains unindented so catalog insertion can find
  it;
- its bibliography remains labeled `<references>` so every title has a stable,
  portable internal destination;
- it retains the exact `#let bibliography-file = "library.bib"` declaration
  required by validation;
- it retains New Computer Modern Sans as the primary face and an overridable
  `korean-font` fallback, with `NanumGothicCoding` as the originating system's
  default;
- its `catalog-author` and `catalog-updated` defaults remain empty, while the
  private root may supply an author and intake transactionally updates its date;
- it displays a populated date without a label and retains the public Spanish
  epigraph immediately above the generated topic hierarchy;
- `templates/library.bib` contains comments only and no BibTeX record;
- `examples/references.bib` remains synthetic and has no local `file` or
  taxonomy `keywords` fields;
- the intake engine remains offline and manifest-driven;
- the shared `paperlib/` parser and media checks remain the single
  interpretation used by intake, export, and validation;
- pending attachment changes only an existing empty `file` field and adds a
  bracketed catalog media link while retaining the References title link and
  holding the advisory lock;
- staging copies explicit external media into ignored `Inbox/`, preserves the
  originals, and shares the advisory lock;
- repeated topic manifests are preflighted and applied as one transaction;
- heading labels and path components retain the same normalized identity;
- metadata provenance stays in optional private reports and never becomes
  canonical bibliography or catalog data;
- `schemas/intake-manifest.schema.json` tracks the preferred manifest form;
- the RIS exporter remains offline, read-only with respect to canonical state,
  and excludes local `file` values;
- root private files, `Inbox/`, `reports/`, and the entire `Library/` tree
  remain ignored;
- new public files are added deliberately to the privacy allowlist;
- changes to manifest behavior update the intake contract and this guide; and
- changes to privacy behavior update this guide, `AGENTS.md`, and `CLAUDE.md`.

After framework changes, run:

```sh
./scripts/test
```

Also test a fresh audited export by running `scripts/init-library`, performing a
dry-run intake with synthetic metadata, and confirming that no private local
state appears in `git status`.
