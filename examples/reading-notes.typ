// A reading-notes template using ONLY native Typst citations.
// Compile from the project root:
// typst compile --root . examples/reading-notes.typ reading-notes.pdf
#set page(paper: "a4", margin: 25mm, numbering: "1")
#set text(size: 11pt, lang: "en")
#set heading(numbering: none)

#text(size: 22pt, weight: "bold")[Reading notes]

Use this file for notes, rather than editing a reference manager's exported
bibliography. Duplicate the section below for each source you read.

= Source 1

#cite(<shannon1948communication>, form: "full")

*Status:* To read.

*Research question:* Write the question the source addresses.

*Method and evidence:* Record the approach, assumptions, data, and evidence.

*Key takeaway:* Write your own summary; distinguish it from direct quotations.

*Useful passage:* Add an exact quotation only after checking the source, and
record its page or section. A locator example is
@shannon1948communication[p.~379].

*Limitations and relevance:* Note limitations and where you might cite this work.

= Source 2

#cite(<vaswani2017attention>, form: "full")

*Status:* To read.

*Summary:* Add your own notes.

*Relevance:* Explain how this source connects to your project.

#bibliography("references.bib", title: [Sources in these notes], style: "apa")
