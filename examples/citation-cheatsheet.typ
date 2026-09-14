// Compile from the project root:
// typst compile --root . examples/citation-cheatsheet.typ citation-cheatsheet.pdf
// Change styles with: --input style=ieee
#set page(paper: "a4", margin: 22mm, numbering: "1")
#set text(size: 10.5pt, lang: "en")
#set par(leading: 0.6em)
#set heading(numbering: none)
#let selected-style = sys.inputs.at("style", default: "apa")

#text(size: 22pt, weight: "bold")[Citation cheatsheet]

Style used for this document: #raw(selected-style).
The examples below render real citations from the included database.

= Normal citation
```typ
A statement with a source @shannon1948communication.
```
A statement with a source @shannon1948communication.

= Narrative citation
```typ
#cite(<shannon1948communication>, form: "prose") is the source.
```
#cite(<shannon1948communication>, form: "prose") is the source.

= Grouped citations
```typ
Two sources @shannon1948communication @vaswani2017attention.
```
Two sources @shannon1948communication @vaswani2017attention.

= Page or section locator
```typ
A pinpoint reference @shannon1948communication[p.~379].
// Equivalent explicit form:
#cite(<shannon1948communication>, supplement: [p.~379])
```
A pinpoint reference @shannon1948communication[p.~379].

= Author only and year only
```typ
#cite(<knuth1984texbook>, form: "author")
#cite(<knuth1984texbook>, form: "year")
```
Author: #cite(<knuth1984texbook>, form: "author").
Year: #cite(<knuth1984texbook>, form: "year").

= Full citation and selective inclusion
```typ
#cite(<knuth1984texbook>, form: "full")
#cite(<typst-bibliography>, form: none) // no visible citation
```
#cite(<knuth1984texbook>, form: "full")
#cite(<typst-bibliography>, form: none)

= Unusual citation keys
For keys containing a slash or other characters unsupported by the shorthand,
construct the label explicitly. The actual key below also works with shorthand.
```typ
#cite(label("typst-cite"))
// For a key such as DBLP:books/lib/Knuth86a, use:
// #cite(label("DBLP:books/lib/Knuth86a"))
```
#cite(label("typst-cite"))

#bibliography("references.bib", title: [References], style: selected-style)
