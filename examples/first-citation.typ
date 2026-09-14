// BEGINNER EXAMPLE: the smallest complete document in this starter.
// Compile from the project root:
// typst compile --root . examples/first-citation.typ first-citation.pdf

// A single equals sign creates a top-level heading.
= My first citation

// @ followed by a bibliography key creates a citation. The key below is the
// identifier after "@article{" in this directory's references.bib.
Information theory provides a mathematical account of communication
@shannon1948communication.

// A line beginning with # runs a Typst function. Square brackets contain the
// text passed to an option. This function prints every cited source above.
#bibliography(
  "references.bib",
  title: [References],
  style: "apa",
)
