// OPTIONAL THIRD-PARTY PACKAGE: inspect every record in a .bib database.
// This is an inventory / reading-notes page, not a CSL-formatted bibliography.
// The first compilation needs access to Typst Universe (or a cached package).
// Compile from the project root:
// typst compile --root . examples/bibliography-inventory.typ inventory.pdf
// Package documentation: https://typst.app/universe/package/citegeist/

#import "@preview/citegeist:0.3.1": load-bibliography

// Read in the caller, because the package cannot read your project directly.
#let database = load-bibliography(
  read("references.bib"),
  source: "references.bib",
)

// Keep your own annotations here, NOT in an auto-exported Zotero .bib file.
// Keys must match the citation keys in this directory's references.bib.
#let notes = (
  shannon1948communication: (
    status: "To read",
    summary: "Replace with your own summary after reading.",
    relevance: "Record the claim or section this source will support.",
  ),
  vaswani2017attention: (
    status: "To read",
    summary: "Replace with your own summary after reading.",
    relevance: "Record methods, comparisons, or limitations worth citing.",
  ),
)

#set page(paper: "a4", margin: 23mm, numbering: "1")
#set text(size: 10.5pt, lang: "en")
#set par(leading: 0.6em)

#text(size: 22pt, weight: "bold")[Bibliography inventory]

There are #database.len() entries in the database. This page lists all of them,
whether or not they are cited in your manuscript. Imported fields are displayed
as plain text, not evaluated as Typst code.

#for key in database.keys().sorted() {
  let entry = database.at(key)
  let fields = entry.fields
  let note = notes.at(key, default: (
    status: "Not triaged",
    summary: "Add a summary in the notes dictionary.",
    relevance: "Add why this source belongs in the project.",
  ))
  block(breakable: false, inset: 10pt, stroke: 0.4pt + luma(75%), above: 12pt)[
    #text(weight: "bold")[#fields.at("title", default: key)] \
    #raw(key) #h(0.5em) | #entry.entry_type

    *Author:* #fields.at("author", default: "Not supplied") \
    *Date:* #fields.at("date", default: fields.at("year", default: "Not supplied")) \
    *Status:* #note.status

    *Summary:* #note.summary

    *Relevance:* #note.relevance
  ]
}
