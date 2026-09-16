// PAPER LIBRARY CATALOG
// Keep the generated PDF in this directory so relative library-file links work.

#let catalog-title = "Catalog"
#let catalog-author = ""
#let catalog-updated = ""
#let citation-style = sys.inputs.at("style", default: "apa")
#let bibliography-file = "library.bib"
#let korean-font = sys.inputs.at("korean-font", default: "NanumGothicCoding")
#let catalog-fonts = ("New Computer Modern Sans", korean-font)

#set document(title: catalog-title, author: catalog-author)
#set page(paper: "a4", margin: (x: 25mm, y: 23mm), numbering: "1")
#set text(font: catalog-fonts, size: 11pt, lang: "en")
#set par(leading: 0.62em)
#set heading(numbering: "1.1.1")
#set cite(style: auto)

#align(center)[
  #text(size: 21pt, weight: "bold")[#catalog-title]
  #if catalog-author != "" [
    #linebreak()
    #text(size: 11pt)[#catalog-author]
  ]
  #if catalog-updated != "" [
    #linebreak()
    #text(size: 9pt, fill: luma(90))[#catalog-updated]
  ]
]

#align(center)[
  #block(width: 92%)[
    #set text(size: 9.5pt)
    #align(right)[
      _“En algún anaquel de algún hexágono (razonaron los hombres) debe existir un libro que sea la cifra y el compendio perfecto de todos los demás: algún bibliotecario lo ha recorrido y es análogo a un dios.”_
    ]

    #align(right)[— Jorge Luis Borges, _La biblioteca de Babel_]
  ]
]

#align(center)[
  #text(size: 8pt, fill: luma(90))[
    Titles open References. Bracketed format links open local attachments; if a viewer reports File not found, return here, select the title or citation, and follow the bibliography URL.
  ]
]

// The intake engine inserts topic headings and catalog citations here.

#bibliography(
  bibliography-file,
  title: [References],
  style: citation-style,
) <references>
