// Job Butler — Single-Page Evidence-Based Cover Letter Template (Typst)
// Invoked via: typst compile --input data=payload.json templates/cover_letter.typ output.pdf

#let raw_input = sys.inputs.at("data", default: "{}")
#let payload = if raw_input.trim().starts-with("{") {
  json.decode(raw_input)
} else {
  json(raw_input)
}

#let basics = payload.at("basics", default: (:))
#let target = payload.at("target_job", default: (:))
#let paragraphs = payload.at("cover_letter_paragraphs", default: ())

#set page(
  paper: "us-letter",
  margin: (top: 0.75in, bottom: 0.75in, left: 0.85in, right: 0.85in),
)

#set text(
  font: ("Liberation Sans", "DejaVu Sans", "Helvetica", "Arial"),
  size: 10.5pt,
  fill: rgb("#111827"),
)

#set par(justify: true, leading: 0.65em)

// Candidate Header
#text(size: 16pt, weight: "bold", fill: rgb("#0f172a"))[#basics.at("name", default: "Candidate Name")] \
#text(size: 10pt, fill: rgb("#475569"))[
  #basics.at("email", default: "")
  #if basics.at("phone", default: "") != "" [ | #basics.at("phone") ]
  #if basics.at("location", default: "") != "" [ | #basics.at("location") ]
]

#v(6pt)
#line(length: 100%, stroke: 0.6pt + rgb("#cbd5e1"))
#v(14pt)

// Date & Recipient
#text(size: 10pt, fill: rgb("#334155"))[#payload.at("date", default: "Hiring Team")] \
#v(6pt)
*Hiring Committee — #target.at("company", default: "Target Organization")* \
Re: #target.at("title", default: "Software Engineering Role")

#v(12pt)
Dear #target.at("company", default: "") Engineering & Hiring Team,

#v(6pt)
#for para in paragraphs [
  #para
  #v(8pt)
]

#v(8pt)
Sincerely,

#v(12pt)
*#basics.at("name", default: "Candidate Name")*

