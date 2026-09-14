// PAPER LIBRARY CATALOG
// Keep the generated PDF in this directory so relative library-file links work.

#let catalog-title = "Paper Library"
#let citation-style = sys.inputs.at("style", default: "apa")
#let bibliography-file = "library.bib"
#let korean-font = sys.inputs.at("korean-font", default: "NanumGothicCoding")
#let catalog-fonts = ("New Computer Modern Sans", korean-font)

#set document(title: catalog-title)
#set page(paper: "a4", margin: (x: 25mm, y: 23mm), numbering: "1")
#set text(font: catalog-fonts, size: 11pt, lang: "en")
#set par(leading: 0.62em)
#set heading(numbering: "1.1.1")
#set cite(style: auto)

#align(center)[
  #text(size: 21pt, weight: "bold")[#catalog-title]
]

// The intake engine inserts topic headings and catalog citations here.

#bibliography(
  bibliography-file,
  title: [References],
  style: citation-style,
)
