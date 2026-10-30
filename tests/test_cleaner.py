"""Unit tests for worker/cleaner.py (Task 6.1)."""

from __future__ import annotations

from worker.cleaner import clean_job_description, compute_content_hash, strip_html_tags


def test_strip_eeo_statement_truncates_trailing_boilerplate() -> None:
    raw = (
        "We are seeking a Senior Backend Engineer to build distributed systems in Python.\n"
        "Requirements:\n"
        "- 5+ years of Python and PostgreSQL\n\n"
        "Equal Opportunity Employer: Acme Corp is proud to be an equal opportunity workplace "
        "and does not discriminate on the basis of race, religion, or gender."
    )
    cleaned = clean_job_description(raw)
    assert "Senior Backend Engineer" in cleaned
    assert "5+ years of Python and PostgreSQL" in cleaned
    assert "Equal Opportunity Employer" not in cleaned
    assert "discriminate" not in cleaned


def test_strip_benefits_and_we_offer_sections() -> None:
    raw = (
        "Build Next.js and TypeScript web applications at scale.\n"
        "Benefits: Comprehensive medical, dental, vision, 401k matching, and unlimited PTO."
    )
    cleaned = clean_job_description(raw)
    assert "Build Next.js and TypeScript" in cleaned
    assert "Benefits:" not in cleaned
    assert "401k" not in cleaned


def test_strip_diversity_and_salary_disclosures() -> None:
    raw = (
        "Core Role: Architect multi-region data pipelines.\n"
        "Diversity Statement: We celebrate diversity and are committed to creating an inclusive environment."
    )
    cleaned = clean_job_description(raw)
    assert "Architect multi-region data pipelines." in cleaned
    assert "Diversity Statement" not in cleaned


def test_strip_html_tags_and_normalize_whitespace() -> None:
    raw_html = (
        "<div><h1>Full Stack Engineer</h1><p>Work with   <strong>TypeScript</strong> and Node.js.</p>"
        "<p>We Offer: Free lunch and gym stipends.</p></div>"
    )
    cleaned = clean_job_description(raw_html)
    assert "Full Stack Engineer" in cleaned
    assert "Work with TypeScript and Node.js." in cleaned
    assert "<h1>" not in cleaned
    assert "We Offer:" not in cleaned


def test_compute_content_hash_is_deterministic_and_case_insensitive() -> None:
    h1 = compute_content_hash("Senior Software Engineer", "Acme Corp", "Build APIs in Python.")
    h2 = compute_content_hash("  senior software   engineer ", "ACME CORP", "Build APIs in   Python.")
    h3 = compute_content_hash("Staff Engineer", "Acme Corp", "Build APIs in Python.")
    assert len(h1) == 64
    assert h1 == h2
    assert h1 != h3


def test_empty_and_max_chars_handling() -> None:
    assert clean_job_description("") == ""
    assert strip_html_tags("") == ""
    long_text = "word " * 500
    truncated = clean_job_description(long_text, max_chars=200)
    assert len(truncated) <= 200

