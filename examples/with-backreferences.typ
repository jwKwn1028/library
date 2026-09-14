// OPTIONAL THIRD-PARTY PACKAGE: cited-on-page backlinks.
// The first compilation needs access to Typst Universe (or a cached package).
// Compile from the project root:
// typst compile --root . examples/with-backreferences.typ backreferences.pdf
// Package documentation: https://typst.app/universe/package/retrofit/
// Check the rendered page numbers and links before submitting a manuscript.

#import "@preview/retrofit:0.2.0": backrefs

#show: backrefs.with(
  read: path => read(path),
  format: links => [ (Cited on #links.join(", ", last: " and "))],
)

// Retrofit resolves this bibliography through the read callback above,
// which is defined in THIS directory. Keep the path relative to this file.
#set page(paper: "a4", margin: 25mm, numbering: "1")
#set text(size: 11pt, lang: "en")
#text(size: 22pt, weight: "bold")[Bibliography backreferences]

On this page, cite a journal article @shannon1948communication and a book
@knuth1984texbook.

#pagebreak()

#text(size: 16pt, weight: "bold")[A second citation location]

Cite the same article on another page @shannon1948communication.
Also cite a conference paper @vaswani2017attention.

The links following each reference should take the reader back to the pages
where that work was cited. This is an optional enhancement, not a requirement
for standard citation management.

#bibliography("references.bib", title: [References], style: "apa")
