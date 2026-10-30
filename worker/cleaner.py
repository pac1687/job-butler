"""Pre-processing text cleaner stripping EEO, benefits, and legal boilerplate (SPEC.md 3.1)."""

from __future__ import annotations

import hashlib
import re
from bs4 import BeautifulSoup

# Truncation markers specified in SPEC.md Section 3.1
BOILERPLATE_MARKERS_REGEX = re.compile(
    r"(?i)\b("
    r"equal\s+opportunity\s+employer|"
    r"benefits\s*:|"
    r"eeo\s+statement|"
    r"diversity\s+statement|"
    r"we\s+offer\s*:|"
    r"salary\s+range\s*:|"
    r"accommodation\s+statement|"
    r"pay\s+transparency"
    r")"
)

WHITESPACE_COLLAPSE_REGEX = re.compile(r"[ \t]{2,}")
MULTI_NEWLINE_REGEX = re.compile(r"\n{3,}")


BLOCK_TAGS = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "tr", "section", "article")


def strip_html_tags(raw_text: str) -> str:
    """Strips HTML tags while preserving line breaks for block elements and keeping inline tags inline."""
    if not raw_text:
        return ""
    if "<" in raw_text and ">" in raw_text:
        soup = BeautifulSoup(raw_text, "html.parser")
        for tag in soup.find_all(BLOCK_TAGS):
            tag.insert_before("\n")
            tag.insert_after("\n")
        return soup.get_text(separator=" ")
    return raw_text


def clean_job_description(raw_text: str, max_chars: int = 12000) -> str:
    """
    Cleans raw job description text:
    1. Strips HTML markup if present.
    2. Truncates non-functional trailing boilerplate matching EEO, benefits, or legal markers.
    3. Normalizes whitespace and enforces a character budget for local 8192-token context windows.
    """
    if not raw_text:
        return ""

    text = strip_html_tags(raw_text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    match = BOILERPLATE_MARKERS_REGEX.search(text)
    if match:
        text = text[: match.start()]

    lines = [WHITESPACE_COLLAPSE_REGEX.sub(" ", line).strip() for line in text.split("\n")]
    normalized = "\n".join(lines).strip()
    normalized = MULTI_NEWLINE_REGEX.sub("\n\n", normalized)

    if len(normalized) > max_chars:
        normalized = normalized[:max_chars].rsplit(" ", 1)[0].strip()

    return normalized


def compute_content_hash(title: str, company: str, cleaned_description: str) -> str:
    """
    Computes deterministic SHA-256 content hash over normalized title, company, and cleaned description
    per FR-2.2.
    """
    norm_title = re.sub(r"\s+", " ", (title or "").strip().lower())
    norm_company = re.sub(r"\s+", " ", (company or "").strip().lower())
    norm_desc = re.sub(r"\s+", " ", (cleaned_description or "").strip().lower())
    canonical = f"{norm_company}::{norm_title}::{norm_desc}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

