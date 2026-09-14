// Native multiple bibliographies: requires Typst 0.15 or newer.
// No Alexandria or Pergamon package is needed for this example.
// Compile from the project root:
// typst compile --root . examples/chapter-bibliographies.typ chapters.pdf
#assert(sys.version >= version(0, 15, 0), message: "Use Typst 0.15+ for native multiple bibliographies.")
#set page(paper: "a4", margin: 25mm, numbering: "1")
#set text(size: 11pt, lang: "en")
#set heading(numbering: "1.1")

#text(size: 22pt, weight: "bold")[Chapter-specific references]

Each citation is picked up by the closest following bibliography that contains
its key. Each chapter below reads the same database but lists its own citations.

= First chapter

This chapter cites a journal article @shannon1948communication and a book
@knuth1984texbook.

#bibliography(
  "references.bib",
  title: [References for chapter 1],
  style: "apa",
)

#pagebreak()
= Second chapter

This chapter cites a conference paper @vaswani2017attention and the same
journal article again @shannon1948communication.

#bibliography(
  "references.bib",
  title: [References for chapter 2],
  style: "apa",
)

// For one combined reference list, use ONE bibliography at the document end
// instead. Multiple source files in one bibliography are a different feature.
