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
#let compact = payload.at("compact_level", default: 0)

#let page_margin = if compact >= 2 {
  (top: 0.32in, bottom: 0.32in, left: 0.4in, right: 0.4in)
} else if compact == 1 {
  (top: 0.38in, bottom: 0.38in, left: 0.45in, right: 0.45in)
} else {
  (top: 0.45in, bottom: 0.45in, left: 0.5in, right: 0.5in)
}

#let body_size = if compact >= 2 { 8.4pt } else if compact == 1 { 8.9pt } else { 9.5pt }
#let line_leading = if compact >= 2 { 0.42em } else if compact == 1 { 0.46em } else { 0.52em }

#set page(
  paper: "us-letter",
  margin: page_margin,
)

#set text(
  font: ("Liberation Sans", "DejaVu Sans", "Helvetica", "Arial"),
  size: body_size,
  fill: rgb("#111827"),
)

#set par(justify: true, leading: line_leading)

// Header
#align(center)[
  #text(size: if compact >= 2 { 15pt } else { 17pt }, weight: "bold", fill: rgb("#0f172a"))[#basics.at("name", default: "Candidate Name")] \
  #v(1pt)
  #text(size: if compact >= 2 { 9.5pt } else { 10.5pt }, weight: "medium", fill: rgb("#334155"))[#basics.at("title", default: "Software Engineer")] \
  #v(2pt)
  #let contact_parts = (
    basics.at("email", default: ""),
    basics.at("phone", default: ""),
    basics.at("location", default: ""),
    ..basics.at("links", default: ()),
  ).filter(p => p != "")
  #text(size: 8pt, fill: rgb("#475569"))[#contact_parts.join("  |  ")]
]

#v(3pt)
#line(length: 100%, stroke: 0.75pt + rgb("#cbd5e1"))

// Summary
#if basics.at("summary", default: "") != "" [
  #v(2pt)
  #text(size: body_size, fill: rgb("#1e293b"))[#basics.at("summary")]
  #v(2pt)
]

// Helper for section headers
#let section_header(title) = {
  v(if compact >= 1 { 2pt } else { 4pt })
  text(size: body_size + 0.5pt, weight: "bold", tracking: 0.06em, fill: rgb("#0f172a"))[#upper(title)]
  v(-4pt)
  line(length: 100%, stroke: 0.5pt + rgb("#94a3b8"))
  v(1pt)
}

// Technical Skills
#let format_category(cat) = {
  let lower_cat = lower(cat)
  if lower_cat == "ai_developer_tooling" or lower_cat == "ai_tooling" or lower_cat == "ai" [AI & Developer Tooling]
  else if lower_cat == "developer_tools" or lower_cat == "tools" [Developer Tools]
  else {
    let clean = cat.replace("_", " ")
    [#upper(clean.first())#clean.slice(1)]
  }
}

#if skills.len() > 0 [
  #section_header("Technical Skills")
  #for (category, items) in skills [
    #if type(items) == array and items.len() > 0 [
      *#format_category(category):* #items.join(", ") \
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
      [#text(size: 8pt, fill: rgb("#475569"))[#role.at("location", default: "") | #role.at("dates", default: "")]],
    )
    #v(1pt)
    #for bullet in role.at("bullets", default: ()) [
      - #bullet
    ]
    #v(if compact >= 1 { 1.5pt } else { 3pt })
  ]
]

// Education
#if education.len() > 0 [
  #section_header("Education")
  #for edu in education [
    #grid(
      columns: (1fr, auto),
      [*#edu.at("institution", default: "")* — #edu.at("degree", default: "")],
      [#text(size: 8pt, fill: rgb("#475569"))[#edu.at("dates", default: "")]],
    )
    #v(1pt)
  ]
]
