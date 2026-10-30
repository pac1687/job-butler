// Job Butler — Single-Page Tailored Resume Template (Typst)
// Invoked via: typst compile --input data=payload.json templates/resume.typ output.pdf

#let raw_input = sys.inputs.at("data", default: "{}")
#let payload = if raw_input.trim().starts-with("{") {
  json.decode(raw_input)
} else {
  json(raw_input)
}

#let basics = payload.at("basics", default: (:))
#let skills = payload.at("skills", default: (:))
#let experience = payload.at("experience", default: ())
#let education = payload.at("education", default: ())

#set page(
  paper: "us-letter",
  margin: (top: 0.45in, bottom: 0.45in, left: 0.5in, right: 0.5in),
)

#set text(
  font: ("Liberation Sans", "DejaVu Sans", "Helvetica", "Arial"),
  size: 9.5pt,
  fill: rgb("#111827"),
)

#set par(justify: true, leading: 0.52em)

// Header
#align(center)[
  #text(size: 18pt, weight: "bold", fill: rgb("#0f172a"))[#basics.at("name", default: "Candidate Name")] \
  #v(2pt)
  #text(size: 10.5pt, weight: "medium", fill: rgb("#334155"))[#basics.at("title", default: "Software Engineer")] \
  #v(3pt)
  #let contact_parts = (
    basics.at("email", default: ""),
    basics.at("phone", default: ""),
    basics.at("location", default: ""),
    ..basics.at("links", default: ()),
  ).filter(p => p != "")
  #text(size: 8.5pt, fill: rgb("#475569"))[#contact_parts.join("  |  ")]
]

#v(4pt)
#line(length: 100%, stroke: 0.75pt + rgb("#cbd5e1"))

// Summary
#if basics.at("summary", default: "") != "" [
  #v(2pt)
  #text(size: 9pt, fill: rgb("#1e293b"))[#basics.at("summary")]
  #v(4pt)
]

// Helper for section headers
#let section_header(title) = {
  v(4pt)
  text(size: 10pt, weight: "bold", tracking: 0.06em, fill: rgb("#0f172a"))[#upper(title)]
  v(-4pt)
  line(length: 100%, stroke: 0.5pt + rgb("#94a3b8"))
  v(2pt)
}

// Technical Skills
#if skills.len() > 0 [
  #section_header("Technical Skills")
  #for (category, items) in skills [
    #if items.len() > 0 [
      *#upper(category.first())#category.slice(1):* #items.join(", ") \
    ]
  ]
]

// Professional Experience
#if experience.len() > 0 [
  #section_header("Professional Experience")
  #for role in experience [
    #grid(
      columns: (1fr, auto),
      [*#role.at("title", default: "")* — #text(weight: "semibold")[#role.at("company", default: "")]],
      [#text(size: 8.5pt, fill: rgb("#475569"))[#role.at("location", default: "") | #role.at("dates", default: "")]],
    )
    #v(1pt)
    #for bullet in role.at("bullets", default: ()) [
      - #bullet
    ]
    #v(3pt)
  ]
]

// Education
#if education.len() > 0 [
  #section_header("Education")
  #for edu in education [
    #grid(
      columns: (1fr, auto),
      [*#edu.at("institution", default: "")* — #edu.at("degree", default: "")],
      [#text(size: 8.5pt, fill: rgb("#475569"))[#edu.at("dates", default: "")]],
    )
    #v(2pt)
  ]
]

