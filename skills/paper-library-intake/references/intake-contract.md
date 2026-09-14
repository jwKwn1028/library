# Intake contract

Read this reference before constructing an intake manifest.

## Judgment that must precede automation

- Recover the official title from the document's title page, then embedded
  PDF/EPUB/MOBI metadata or identifier text. Prefer the title page when sources
  conflict.
- Classify by the item's primary contribution in the narrowest clean existing
  directory. Prefer domain-specific folders over generic ones.
- Create a category only when no existing directory fits, the topic is broader
  than one item, and it is likely to recur or already has a peer item. Use a
  concise PascalCase topic name and mention the new category in the report.
- Check likely duplicates by DOI, citation key, title, and file content. Do not
  retain a second copy unless it is a meaningfully different document such as a
  supplement.

## Canonical names and keys

- Derive a short but unambiguous filename from the official title.
- Use ASCII PascalCase without spaces or punctuation and retain the source
  format with a lowercase `.pdf`, `.epub`, or `.mobi` extension. Treat `/`,
  `-`, and `:` as word boundaries and replace `&` with `And`.
- Preserve meaningful numbers, formulas, and acronyms such as `QM9`, `OC20`,
  `CO2`, `DFT`, and `SE3`. Spell Greek letters and symbols in English.
- Keep identity terms such as `Supplementary`, `Appendix`, `Dataset`, or
  `Review` when they are part of the actual document.
- Do not add authors, years, journal names, DOI fragments, download-site names,
  or arXiv IDs unless disambiguation requires them.
- Use a stable lowercase ASCII key of the form
  `firstauthorYYYYshorttitle`. Append `a`, `b`, and so on only for collisions.

## Web metadata retrieval

The agent may browse for missing or conflicting metadata; the intake script
must not. Prefer the publisher record reached through the DOI, then Crossref,
the official arXiv record for a preprint, or an institutional repository. Use a
secondary index only when primary records are unavailable and verify important
fields independently.

Downloaded BibTeX is evidence, not the source of truth. Confirm title, authors,
document type, date, venue, volume/issue, pages or article number, and DOI
against the document or another authoritative source. Do not invent fields or
allow a remote export to overwrite `library.bib`. Put verified, normalized
values in the manifest and keep transient downloads in `/tmp` or an intake
location.

When the user explicitly requests a reading-list entry before obtaining the
document, verify the same fields against the publisher and/or an authoritative
registry. Mark the record pending and leave its file path empty. The later
download must still be inspected before it is attached to the record.

## Manifest

The script accepts one destination topic per manifest:

The preferred `items` form is described by
[`schemas/intake-manifest.schema.json`](../../../schemas/intake-manifest.schema.json).
The engine remains the final validator and additionally checks the live
bibliography, catalog, filesystem, and media contents.

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
      "source_file": "Inbox/downloaded-item.epub",
      "canonical_filename": "DistinctiveOfficialTitle.epub",
      "citation_key": "author2026distinctivetitle",
      "entry_type": "book",
      "title": "The official display title",
      "bib_title": "The official display title with {Protected Acronyms}",
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

A metadata-only item uses the same reviewed fields but has no source or
destination filename:

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
      "fields": {
        "author": "Example, Ada and Researcher, Ben",
        "journaltitle": "Journal of Synthetic Examples",
        "date": "2026",
        "doi": "10.0000/synthetic-foundational"
      }
    }
  ]
}
```

After that pending record's document has been inspected, attach it without
resubmitting metadata:

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

Rules:

- Paths are relative to the library root and cannot leave it.
- `topic.path` components and `canonical_filename` must already follow the
  canonical naming rules. The canonical extension must match the source format.
  `headings` supplies the readable Typst labels. Do not include the physical
  `Library/` prefix in `topic.path`; the script adds it to local destinations.
- `items` is the preferred collection key and `source_file` is the preferred
  source key. Existing manifests using `papers` and PDF-only `source_pdf`
  remain accepted for backward compatibility. Do not provide both aliases.
- A metadata-only item sets `pending: true` and must omit `source_file`,
  `source_pdf`, and `canonical_filename`. A normal local item omits
  `pending` (or sets it to `false`) and requires the file properties.
- An attachment item sets `attach: true`, names an existing pending
  `citation_key`, requires `source_file` and `canonical_filename`, and omits
  all metadata properties. Its manifest topic must match the record's existing
  `% Topic:` path. The engine preserves the key and metadata while updating the
  existing `file` field and catalog item.
- `title` is plain Unicode used in `main.typ`. Use optional `bib_title` only
  when BibTeX capitalization braces are needed.
- At least one of `fields.author` or `fields.editor`, plus either `fields.date`
  or `fields.year`, is required. Dates use `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`;
  if both date and year are supplied, their years must agree. Supply accurate
  fields from the item; the script does not query external metadata services.
  Both authored and editor-only books can use `entry_type: book`.
- DOI values may be bare identifiers or DOI URLs; the script stores them as
  bare identifiers and adds a DOI URL when `url` is absent.
- `keywords` and `file` are generated; do not put them in `fields`. A
  local item receives `Library/<topic.path>/<canonical_filename>`, while a
  pending item receives an empty `file` value.
- `sidecars` are informational unless `--delete-sidecars` is explicitly used.
  The script never treats downloaded sidecar metadata as authoritative.
- Unknown top-level, topic, or item properties are rejected so misspelled
  fields cannot be silently ignored. `$schema` is the only optional top-level
  annotation.
- Dry runs, status reads, and applies hold `.paper-library.lock`. A concurrent
  operation fails after the finite `--lock-timeout` instead of losing an
  update.

## Successful result

Every processed item has one record in `library.bib` and one citation under
the matching hierarchy in `main.typ`. A local item has exactly one canonical
PDF, EPUB, or MOBI file beneath `Library/` and a linked title. A pending item
has an empty `file` field, an unlinked title with no visible status label, and
an empty `Library/<topic.path>/` destination directory. No placeholder media
file is created. No DOI, key, non-empty file path, or local file content is
duplicated. The validator passes and `PaperLibrary.pdf` is rebuilt in the
library root.

For an attachment, the prior empty `file` field becomes the canonical path and
the prior unlinked item becomes linked. There is still exactly one BibTeX
record and one catalog citation for the stable key.
