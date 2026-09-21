# Paper Library User Guide

This guide explains how to initialize, operate, validate, back up, and publish
the Paper Library template. It is written for both direct command-line use and
agent-assisted document intake.

## Contents

- [The repository model](#the-repository-model)
- [Requirements](#requirements)
- [First-time setup](#first-time-setup)
- [Repository layout](#repository-layout)
- [Search the bibliography](#search-the-bibliography)
- [Intake a library item](#intake-a-library-item)
- [Add a metadata-only reading list](#add-a-metadata-only-reading-list)
- [Attach a downloaded pending item](#attach-a-downloaded-pending-item)
- [Fetch accessible pending PDFs](#fetch-accessible-pending-pdfs)
- [Add music and film records](#add-music-and-film-records)
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
GNU `find`, `sed`, or `sha256sum`. Only the optional `fetch-pending` and
`lookup-media` helpers need network access.

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
pre-commit and pre-push hooks run the publication privacy audit, and the
commit-msg hook checks each new commit message. Git does not activate
repository-provided hooks automatically, so run this command once in every new
clone.

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
├── CLAUDE.md                 # imports AGENTS.md for Claude Code
├── LICENSE                   # MIT, public framework only
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
│   ├── fetch-pending
│   ├── init-library
│   ├── install-hooks
│   ├── intake-papers
│   ├── lookup-media
│   ├── public-repo
│   ├── search-bibliography
│   ├── stage-papers
│   ├── test
│   └── validate-library.sh
├── skills/
│   ├── music-film-intake/    # albums and films as URL-linked pending records
│   └── paper-library-intake/
├── styles/
│   └── title-link.csl       # renders titles as entry-specific citation links
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

## Search the bibliography

Search the canonical `library.bib` by title (including subtitle and numbered
series), author or editor, citation key, topic path, or DOI:

```sh
./scripts/search-bibliography embedding
./scripts/search-bibliography "electronic structure" --pending
./scripts/search-bibliography synthetic handbook --local
./scripts/search-bibliography example2024study --json
```

Every whitespace-separated term must occur in at least one searchable field
of the same record. Terms can match different fields. Matching uses literal
substrings, ignores letter case and combining accents, and removes BibTeX
grouping braces from displayed metadata. Shell quotes group arguments; they do
not enable exact-phrase matching. Topics accept PascalCase fragments or separate
words, so `ElectronicStructure` and `electronic structure` both work.

Results are sorted by citation key and include the title, creators, date,
topic, DOI, and local attachment path when present. `--pending` selects empty
`file` fields; `--local` selects populated paths without checking the media on
disk. These options are mutually exclusive. Without either, all record types
and attachment states are searched, including books, music, and films.

`--json` prints only an array of objects with `citation_key`, `entry_type`,
`title`, `author`, `editor`, `date`, `topic` (an array of components), `doi`,
`file`, and `pending` fields. Missing text fields are empty strings. Results
contain private metadata; save them only in an ignored location such as
`reports/` when needed.

The command runs offline, reads only `library.bib`, and uses the shared library
lock. It does not update the bibliography, catalog, or documents. Use
`--root PATH` to search a different library and `--lock-timeout SECONDS` to change the
default five-second lock wait. No matches, including an empty bibliography,
is a successful search (exit 0, an empty JSON array or `Matches: 0`). Missing
queries, invalid options, parsing failures, and unavailable libraries exit 2.

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

The validator scans only `Library/` for canonical media, so unrelated staged
documents may wait in `Inbox/` while another batch is applied, and notes or
exports elsewhere in the root are ignored. Intake, staging, and `fetch-pending
--match` still compare new content with everything in `Library/` and `Inbox/`.
Only files beneath `Library/` are canonical attachments. For several items going to one topic, include them
in one manifest; for several topics, prepare one manifest per topic and submit
all of them in the same intake command.

After a successful intake, explicitly reviewed citation prompts and retained
sidecars may be moved into `Inbox/Processed/<batch-date>/`, using an ISO date
such as `2026-01-15`. Preserve their names and contents, refuse destination
collisions, and hold the shared `.paper-library.lock` during the move. Only
archive completed batches; leave new arrivals at the top of `Inbox/`.
Historical JSON reports retain the paths recorded at intake time. This is a
manual housekeeping convention, not an automatic part of intake; sidecars are
still retained in place by default. Canonical media remains under `Library/`.

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
./scripts/search-bibliography "distinctive title fragment"
./scripts/search-bibliography "bare-doi"
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
broader than one item, and the category is likely to recur. Keep books, films,
and albums out of `AdjacentFields`, the catch-all for adjacent research: a book
belongs under its subject topic or `Literature`, a film under `Film`, and an
album under `Music`.

Inspect the current taxonomy before deciding:

```sh
./scripts/intake-papers topics
./scripts/intake-papers topics --json
```

Each result includes the canonical path, readable headings, total records,
local-file count, pending count, and expected `Library/` directory. The command
is read-only and uses the same advisory lock as intake.

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
        "isbn": "978-0-000-00000-2"
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
  --manifest /tmp/perspectives.json
```

Without `--apply`, no library file is changed. Review every printed value:

- source and destination paths;
- detected source format;
- citation key;
- official display title;
- DOI, when present;
- normalized ISBN-13, when present;
- normalized `imdb`, `musicbrainz`, and `wikidata` identifiers (`ID` lines);
- the `[URL]` link target of an album or film (`LINK` line);
- any reviewed `distinct_from` assertion (`DISTINCT FROM` line);
- metadata provenance URLs, when present;
- sidecar disposition;
- topic path and readable heading hierarchy;
- the `Library/<topic.path>/` directory that apply will create if absent;
- output catalog name.

The dry run also applies the validator's text rules to the planned
`library.bib` and `main.typ`. A plan that the post-apply validation would
reject, including one blocked by an existing inconsistency, fails here with
the same messages before anything changes.

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
  --manifest /tmp/perspectives.json \
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

To retain both review phases without overwriting either, use one report base on
the dry run and repeat it on apply:

```sh
./scripts/intake-papers \
  --manifest /tmp/paper-intake.json \
  --report-base reports/paper-intake

./scripts/intake-papers \
  --manifest /tmp/paper-intake.json \
  --apply \
  --report-base reports/paper-intake
```

This creates `paper-intake.dry-run.json` and `paper-intake.applied.json`.
`--report-json PATH` remains available when one exact output path is desired.
An existing phase report is not replaced unless `--force-report` is explicit.

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
- adds its title and citation key to `main.typ`, linking the title to its
  individual bibliography entry;
- adds no visible pending-status label to the catalog;
- creates the empty `Library/<topic.path>/` destination directory but no
  placeholder media file; and
- validates and rebuilds the catalog transactionally.

Empty file values are intentional state, not broken links. Duplicate key, DOI,
ISBN, and normalized-catalog-title checks still apply.

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
`file` field, retains the title's individual bibliography-entry link, and adds
a bracketed direct media link. It then validates and rebuilds the catalog. It does not create a
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

1. Unpaywall open-access locations, when an identifying email is supplied at
   runtime;
2. Semantic Scholar open-access copies, often institutional repositories;
3. Crossref full-text links from the publisher;
4. preprints: an arXiv copy recorded by Semantic Scholar, then any preprint
   the publisher registered with Crossref (`has-preprint`), such as arXiv,
   ChemRxiv, or bioRxiv; and
5. the DOI resolver.

When a candidate returns an HTML landing page that declares the standard
`citation_pdf_url` metadata, that PDF link is tried once. Several preprint
servers answer scripted requests with a bot check, so non-arXiv preprints often
still need the browser handoff below.

OpenAlex is no longer queried. It has required an API key since February 2026,
and Unpaywall now serves the same open-access location data. Unpaywall
requires an identifying email; enable it for the current process without
writing it to a file:

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
where it was. A title shorter than four words is often a common phrase, so its
match also needs the first author's or editor's family name as a whole word.
Downloads from `--apply` pass the same identity check. Ambiguous, duplicate, already staged, and unreadable PDFs are
reported instead. Scanned PDFs without a text layer cannot be identified
automatically; check their title pages and stage them with
`scripts/stage-papers`.

Fetching deliberately stops at `Inbox/`. Inspect each PDF and create the normal
reviewed `attach: true` manifest with a canonical filename. The attachment
transaction then moves the document, updates the empty `file` field and catalog
link, validates the library, and rebuilds `Catalog.pdf`.

## Add music and film records

Albums and films are ordinary bibliography records that stay pending: the
BibTeX `file` field is empty until a local copy exists, and the record's `url`
becomes a bracketed `[URL]` link beside the catalog title. The title still
opens the record's References entry. Local audio and video files are not yet
supported as attachments, so these records have no attachment step.

Use `@audio` with `type = {Album}` (or `EP`, `Single`) for an album and
`@movie` with `type = {Film}` for a film; the engine also treats `@music` and
`@video` as audiovisual. Put the credited artist or the directors in `author`,
because Typst omits an `editor`-only director from a film's reference. The
`music-film-intake` skill documents the full conventions and source priority.

### Look up metadata

The read-only helper searches MusicBrainz release groups and Wikidata films:

```sh
./scripts/lookup-media music "Album Title" --artist "Artist Name"
./scripts/lookup-media film "Film Title" --year 2026 --director "Name"
```

Draft one record from the chosen identifier or its page URL:

```sh
./scripts/lookup-media music --id MUSICBRAINZ-RELEASE-GROUP-ID
./scripts/lookup-media film --id WIKIDATA-QID --language ko
```

The draft is a complete pending manifest item with a suggested citation key,
normalized fields, `metadata_sources`, and a `url`. It also lists alternative
links and review notes, such as a year-only date, several credited artists, a
key collision, or an identifier already in the library. By default the `url`
is a streaming or watch page when one is known; `--link reference` prefers a
stable reference page instead. For films, `--language` selects the title: `en`
by default, another Wikidata language code, or `original`. YouTube videos
shorter than 90% of the film's runtime, usually trailers or partial uploads,
are listed but never selected. `--json` prints machine-readable output.

The helper writes nothing and paces MusicBrainz requests to its limit of one
per second. Both services ask clients to identify a contact; supply one only
in the runtime environment:

```sh
PAPER_LIBRARY_LOOKUP_CONTACT="$CONTACT_URL_OR_EMAIL" \
  ./scripts/lookup-media music "Album Title"
```

The value is sent only in the request User-Agent and is never printed or
stored.

### Review, dry-run, and apply

A synthetic album manifest looks like this:

```json
{
  "topic": {
    "path": "Music/Jazz",
    "headings": ["Music", "Jazz"]
  },
  "items": [
    {
      "pending": true,
      "citation_key": "example2026syntheticsessions",
      "entry_type": "audio",
      "title": "Synthetic Sessions",
      "metadata_sources": [
        "https://musicbrainz.org/release-group/00000000-0000-4000-8000-000000000001"
      ],
      "fields": {
        "author": "{Example Ensemble}",
        "date": "2026-01-15",
        "publisher": "Example Records",
        "type": "Album",
        "musicbrainz": "00000000-0000-4000-8000-000000000001",
        "url": "https://music.example.org/album/synthetic-sessions"
      }
    }
  ]
}
```

Run the same dry-run and apply commands as for documents. The plan prints
`FILE  PENDING LOCAL PATH`, one `ID` line per normalized identifier, and
`LINK  [URL] <url>`. A successful apply adds the record with `file = {}`,
creates `Library/<topic.path>/`, inserts the title and its `[URL]` link, and
validates and rebuilds the catalog in the same transaction.

Rules specific to albums and films:

- `url` must be an absolute HTTP(S) URL without credentials; remove tracking
  parameters such as `si` or `utm_*`. Other record types never show `[URL]`,
  even when they have a `url`.
- `musicbrainz` (an album's release-group or a song's recording ID), `imdb`
  (`tt…`), and `wikidata` (`Q…`) accept bare IDs or page URLs. Intake stores
  bare IDs and rejects an identifier already used by another record.
- A song is `@audio` with `type = {Song}` and its album in `booktitle`; Typst's
  APA style omits the album, but other BibLaTeX styles and reference managers
  use it. `lookup-media` drafts albums, not songs.
- Duplicate detection combines the normalized title with the medium, release
  year, and first creator. A film may share a novel's title, a remake its
  original's, and a soundtrack its film's.
- Prefer a full `YYYY-MM-DD` release date: Typst's APA style renders a
  year-only audiovisual date as `(2026,)`.
- File albums under `Music` and films under `Film`, never under
  `AdjacentFields`.

`scripts/fetch-pending` ignores albums and films, even when a film carries an
EIDR DOI.

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
| `title` | yes | Plain Unicode work title; structured subtitle and numbered-series fields are added to the catalog label |
| `bib_title` | no | BibTeX title with capitalization braces if needed |
| `metadata_sources` | no | Unique HTTP(S) URLs used to verify metadata; retained only in reports |
| `distinct_from` | no | Citation keys of verified distinct works that share this item's normalized title; see below |
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

`distinct_from` is the reviewed exception to title-based duplicate detection.
A new record whose normalized catalog title matches an existing record is
rejected, because the usual cause is a second copy of the same work: a
preprint and its published version, a paperback and hardcover, or a
re-download. Albums and films also compare the release year and first creator.
When the records are genuinely different works, such as a review article and
a textbook that share a title, verify that and list every matching key:

```json
"distinct_from": ["example2015syntheticlearning"]
```

The engine rejects the item unless the list names exactly the records that
share its identity. It stores the assertion as a `distinctfrom` BibTeX field,
which the validator requires for every pair of records with the same identity.
Only a new record carries this key; it is never used for attachments.

Field rules:

- at least one of `author` or `editor` is required;
- either `date` or `year` is required;
- dates use `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`, and a supplied `year` must
  agree with `date`;
- `title`, `keywords`, `file`, and `distinctfrom` are reserved and cannot
  appear in `fields`;
- `subtitle` remains a separate BibLaTeX field and is displayed as
  `title: subtitle` in the catalog topic list;
- a numbered series uses the individual work in `title`, its collection in
  `series`, and its sequence in `number`; the catalog displays
  `series #number: title: subtitle`, omitting absent segments;
- field names begin with a letter and contain only letters, numbers,
  underscores, or hyphens;
- field values are normalized to single spaces, must have balanced braces,
  and cannot end in an unpaired backslash;
- a DOI can be supplied bare, with a `doi:` prefix, or as a DOI URL;
- the engine stores a bare DOI and adds its URL when `url` is absent;
- one ISBN-10 or ISBN-13 may identify the cataloged edition; its checksum must
  be valid, new intake stores it as an unseparated ISBN-13, and equivalent
  ISBN-10/13 values are rejected as duplicates;
- optional `musicbrainz` (release group or recording), `imdb`, and `wikidata`
  values accept bare IDs or page URLs, are stored as bare IDs, and must be
  unique;
- for `audio`, `music`, `movie`, and `video` records, `url` must be a
  credential-free HTTP(S) URL and becomes the catalog `[URL]` link;
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
2. preflight validates every manifest in command-line order, checks both
   current-state and cross-manifest duplicates, and applies the validator's
   text rules to the planned `library.bib` and `main.typ`;
3. current `library.bib`, `main.typ`, output catalog PDF, and optionally deleted
   sidecars are snapshotted;
4. every requested `Library/<topic.path>/` is created, even for pending-only
   manifests, and local library files are moved when present;
5. new BibTeX records are rendered under a `% Topic:` section, or an attachment
   updates the parsed `file` value of its existing record;
6. catalog headings with the same normalized identity are found, or the
   supplied naturally cased headings are created before the bibliography block;
   an item for a topic that already has subtopics is placed before the first
   subtopic heading, so it stays in its own topic;
7. every title links to its individual entry in References; local items also receive a
   `[PDF]`, `[EPUB]`, or `[MOBI]` attachment link, albums and films with a
   `url` receive a separate `[URL]` link, and citation keys are inserted
   without visible pending-status labels;
8. the quoted private `catalog-updated` value is set to the current local date;
9. writes to the two text sources are atomic;
10. `scripts/validate-library.sh --no-compile` checks the semantics, files,
    and media;
11. Typst compiles a temporary catalog once, which atomically replaces the
    requested output only after success;
12. explicitly selected sidecars are removed;
13. a requested applied JSON report is written with owner-only permissions
    after validation and compilation have passed.

If a move, write, validation, build, or cleanup step fails, the engine restores
the snapshotted files, moves library files back, removes newly created empty
directories, and reports the concrete error. The same rollback runs when the
apply is interrupted by Ctrl-C (`SIGINT`), `SIGTERM`, or `SIGHUP`; the command
then exits with status 130. Further interrupts are ignored until the rollback
finishes. Treat a rollback message as an incomplete intake and resolve the
underlying cause before retrying. An abrupt `SIGKILL` or power loss cannot be
rolled back; run `scripts/validate-library.sh` afterwards to find any
half-applied state.

The lock also covers dry runs, pending-status reads, and taxonomy reads. It
waits five seconds by default; `--lock-timeout SECONDS` accepts a finite
non-negative override.
The script is designed for new intake and pending attachment, not bulk
recategorization or mass-renaming of existing items.

## Private intake reports

Prefer `--report-base PATH`. The dry run writes `PATH.dry-run.json`; apply
writes `PATH.applied.json`, so both provenance phases survive without
`--force-report`. A dry-run report has `status: "dry-run"` and leaves the
library unchanged. An apply report has `status: "applied"` and records that
validation and catalog compilation passed. `--report-json PATH` retains the
single exact-path behavior. Every report includes:

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
existing phase reports unless `--force-report` is supplied. Symlinked parent
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
- maps articles, books, chapters, conference papers, theses, reports, albums
  (`SOUND`), films (`MPCT`, or `VIDEO` for `@video`), and other common BibTeX
  entry types to RIS types;
- preserves citation keys as `ID`, authors and editors, publication fields,
  DOI/URL values, and taxonomy keywords;
- writes a structured subtitle into the title as `title: subtitle`, and a
  numbered series as `T3` with its number in `M1` for a book or `SV` for a
  chapter, the tags Zotero reads as a series number (an article's `number`
  stays its issue, `IS`);
- includes both local and pending records, or only the subset selected by
  the filters described below; and
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

### Export a subset

Three filters select records by kind and taxonomy:

| Option | Selects | Example values |
| --- | --- | --- |
| `--type` | A kind of record: `paper`, `book`, `music` (or `album`), `film`; or an exact BibTeX entry type | `film`, `paper,book`, `online` |
| `--topic` | A top-level topic with all of its subtopics | `QuantumChemistry`, `"Quantum Chemistry"` |
| `--subtopic` | A topic path, or a subtopic name under any topic | `Film/Crime`, `ScienceFiction` |

Kinds group BibTeX entry types. `book` covers books, chapters, collections,
and proceedings volumes; `music` covers `@audio` and `@music`; `film` covers
`@movie` and `@video`; `paper` covers every other document, including articles,
conference papers, reports, theses, and online preprints. Use an exact entry
type such as `article` or `online` when a kind is too broad.

Repeat an option or separate its values with commas to match any of them.
Records must match every option given. So `--type film --topic Film,Music`
exports the films in either topic, while `--topic Film --subtopic
ScienceFiction` exports only `Film/ScienceFiction`. Without the `--topic`, a
bare subtopic name such as `ScienceFiction` also matches
`Literature/ScienceFiction`. Topic names ignore case, spacing, and
punctuation, like catalog headings.

```sh
./scripts/export-bibliography --type film --output exports/films.ris
./scripts/export-bibliography --type paper --topic QuantumChemistry \
  --output exports/quantum-chemistry-papers.ris
./scripts/export-bibliography --subtopic Film/Crime,Literature/ScienceFiction \
  --output exports/crime-and-science-fiction.ris
```

Give each subset its own `--output`, so a partial export is never mistaken for
the full `exports/library.ris`. The summary reports how many records matched,
for example `Exported 2 of 40 record(s) matching type film`. An unknown type,
topic, or subtopic, or a combination that matches nothing, is reported as an
error and nothing is written. The error lists the available top-level topics;
`./scripts/intake-papers topics` lists every subtopic.

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
  values, and normalized titles (for albums and films, the title plus medium,
  release year, and first creator), except for records that a reviewed
  `distinctfrom` field declares to be distinct works;
- canonical, unique `musicbrainz`, `imdb`, and `wikidata` identifiers;
- one title, author or editor, canonical date/year, topic marker, `keywords`,
  and `file` field per record;
- exact agreement among `% Topic:` markers, keyword paths, physical topic
  directories, and readable Typst heading hierarchies;
- exactly one catalog item per key, matching BibTeX and catalog titles, and no
  duplicate citations or links hidden by set deduplication;
- a References-section title link for every record, plus an exact,
  correctly-labeled media link for every local record and no attachment or
  visible status label for pending records;
- exactly one `[URL]` link to its safe HTTP(S) `url` for every album or film
  that has one, and no `[URL]` link on any other record;
- canonical, safe, non-symlink paths rooted at `Library/` and an exact match
  between bibliography paths and the PDF/EPUB/MOBI files beneath `Library/`;
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

Catalog titles open their individual entries in References. The small public
`styles/title-link.csl` file provides this custom-text citation link. A local
item additionally shows `[PDF]`, `[EPUB]`, or `[MOBI]`, which opens its relative
attachment. A PDF viewer cannot portably detect a failed external-file action
and redirect automatically. Therefore, when a shared `Catalog.pdf` has no
accompanying `Library/` tree, the viewer may report `File not found`; return to
the catalog, select the linked title or citation, and follow the DOI or URL in
References.
This portability guidance is documentation only and is not printed in
`Catalog.pdf`.

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
agents. `CLAUDE.md` imports it through Claude Code's `@` file-import syntax, so
both agents read one policy that cannot drift. The reusable intake
skill lives at `skills/paper-library-intake/`; albums and films use
`skills/music-film-intake/`, for example with "Use $music-film-intake to add
this album with a listening link."

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
- staged index blobs;
- every path/blob pairing reachable from existing Git history; and
- every reachable commit message and annotated tag message.

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

Commit and tag messages are published with history, so they get the same
text scans and private terms. The one difference is that no-reply addresses,
such as a `Co-Authored-By` trailer, are accepted in messages. The
`.githooks/commit-msg` hook runs `./scripts/public-repo audit-message` on each
new message before Git records it; comment lines and anything below a
verbose-commit scissors line are ignored, because Git drops them too.

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

The framework is released under the MIT License in `LICENSE`. The license
covers the public framework only; your private library records and media keep
whatever terms apply to them and are never part of a public export.

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
| `scripts/search-bibliography TERM... [--pending\|--local] [--json]` | Search titles, creators, citation keys, topics, and DOIs | No |
| `scripts/export-bibliography` | Export private metadata to `exports/library.ris` | Writes derived RIS output only |
| `scripts/fetch-pending --key KEY [--apply]` | Discover or stage an accessible pending PDF | Writes only ignored `Inbox/` with `--apply` |
| `scripts/fetch-pending --key KEY --browser` | Open the record's publisher page in your browser | No |
| `scripts/fetch-pending --match PATH... [--apply]` | Identify browser-downloaded PDFs and stage unique matches | Writes only ignored `Inbox/` with `--apply` |
| `scripts/export-bibliography --output PATH --force` | Replace a selected RIS export | Replaces derived RIS output only |
| `scripts/export-bibliography --type T --topic T --subtopic S --output PATH` | Export only matching records | Writes derived RIS output only |
| `scripts/stage-papers PATH...` | Validate and print a plan to copy external media into `Inbox/` | No |
| `scripts/stage-papers PATH... --apply` | Copy verified media into `Inbox/` while preserving originals | Adds private inbox copies |
| `scripts/intake-papers --write-template PATH` | Write a starter JSON manifest | Writes only the requested new path |
| `scripts/intake-papers status --pending [--json]` | List records awaiting documents | No |
| `scripts/intake-papers topics [--json]` | List taxonomy paths, headings, and local/pending counts | No |
| `scripts/intake-papers --manifest PATH` | Validate and print an intake plan | No |
| repeated `--manifest PATH` arguments | Preflight or apply several topics as one transaction | Follows dry-run or apply mode |
| `scripts/intake-papers --manifest PATH --apply` | Apply, validate, and build transactionally | Yes |
| `scripts/intake-papers --manifest PATH --report-json PATH` | Write a private dry-run provenance report | Writes only the report |
| `scripts/intake-papers --manifest PATH --apply --report-json PATH` | Apply and write a private success report after validation/build | Yes |
| `scripts/intake-papers --manifest PATH --report-base PATH` | Write phase-specific `.dry-run.json` or `.applied.json` provenance | Dry run writes only its report; apply mutates library data |
| attachment manifest with `--apply` | Connect a document to one pending record | Yes |
| `scripts/intake-papers --manifest PATH --apply --delete-sidecars` | Apply and remove listed sidecars after success | Yes |
| `scripts/intake-papers --manifest PATH --output NAME.pdf --apply` | Build a custom root-level catalog filename | Yes |
| `scripts/lookup-media music\|film QUERY` | Search MusicBrainz albums or Wikidata films | No |
| `scripts/lookup-media music\|film --id ID` | Print a draft pending manifest item for review | No |
| `scripts/validate-library.sh` | Check the complete private library and Typst build | No persistent output |
| `scripts/test` | Run the complete framework and private-state gate | No persistent output |
| `scripts/public-repo audit` | Audit publishable files, index, and history | No |
| `scripts/public-repo export DIRECTORY` | Create an audited public-only tree | Writes only the destination |

Use built-in help for current command syntax:

```sh
./scripts/export-bibliography --help
./scripts/search-bibliography --help
./scripts/stage-papers --help
./scripts/intake-papers --help
./scripts/intake-papers status --help
./scripts/lookup-media music --help
./scripts/lookup-media film --help
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

Review the reported missing or uncataloged paths. A common cause is an
unrelated PDF, EPUB, or MOBI file placed inside `Library/`, a manually moved
canonical file, a stale `file` field, or an item omitted from the manifest.
Media outside `Library/`, including staged files in `Inbox/`, is not checked
here.

### `refusing to overwrite existing report without --force-report`

Choose a new private report path, or inspect the existing report and repeat the
command with `--force-report` only when replacing it is intentional.

### Duplicate DOI, ISBN, title, key, path, or content

Do not work around the check by changing arbitrary metadata. Determine whether
the incoming document is an existing item, a distinct version, a correction,
or supplementary material. Only genuinely distinct documents belong as
separate records.

A shared title is reported with the matching citation keys. If verification
shows a genuinely different work with the same title, add those keys to the
item's `distinct_from` array (see the manifest reference) and rerun the dry
run. Never use it to keep a second copy of the same work.

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

### `duplicate recording (same title, release year, and first creator)`

The library already has an album or film with that title, medium, year, and
first creator. Check whether it is the same work before changing anything; for
a genuinely different release, confirm its title, date, and credits against
the sources rather than editing them to pass. If the verified metadata really
is identical for two different works, list the existing key in the item's
`distinct_from` array.

### `lookup-media` reports HTTP 403, 429, or 503

The service is refusing or throttling requests. The helper retries twice after
429 or 503. Wait before retrying, keep lookups serial, and set
`PAPER_LIBRARY_LOOKUP_CONTACT` so the service can identify the client.

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
- its bibliography remains labeled `<references>` and title links use the
  dedicated citation-link style so every title has a specific internal destination;
- `styles/title-link.csl` remains public and renders only the supplied title
  text while preserving Typst's bibliography-entry hyperlink;
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
- `scripts/lookup-media` stays networked, read-only, and separate from the
  engine, and never prints or stores the runtime lookup contact;
- the catalog `[URL]` link derives only from an audio or video record's `url`,
  and those records stay pending until local audio and video are supported;
- the shared `paperlib/` parser and media checks remain the single
  interpretation used by intake, export, and validation, and the intake dry run
  applies the validator's text checks to its planned state;
- an apply rolls back on any error and on `SIGINT`, `SIGTERM`, or `SIGHUP`;
- the validator treats only `Library/` as canonical media; duplicate-content
  checks also cover `Inbox/`;
- records may share a normalized identity only through a reviewed
  `distinctfrom` assertion;
- pending attachment changes only an existing empty `file` field and adds a
  bracketed catalog media link while retaining the References title link and
  holding the advisory lock;
- staging copies explicit external media into ignored `Inbox/`, preserves the
  originals, and shares the advisory lock;
- repeated topic manifests are preflighted and applied as one transaction;
- heading labels and path components retain the same normalized identity;
- metadata provenance stays in optional private reports and never becomes
  canonical bibliography or catalog data;
- `schemas/intake-manifest.schema.json` tracks the preferred manifest form,
  and `tests/test_manifest_schema.py` keeps its properties and patterns in step
  with the engine;
- the RIS exporter remains offline, read-only with respect to canonical state,
  and excludes local `file` values;
- root private files, `Inbox/`, `reports/`, and the entire `Library/` tree
  remain ignored;
- new public files are added deliberately to the privacy allowlist;
- changes to manifest behavior update the intake contract and this guide; and
- changes to privacy behavior update this guide and `AGENTS.md`, which
  `CLAUDE.md` imports instead of repeating.

After framework changes, run:

```sh
./scripts/test
```

Also test a fresh audited export by running `scripts/init-library`, performing a
dry-run intake with synthetic metadata, and confirming that no private local
state appears in `git status`.
