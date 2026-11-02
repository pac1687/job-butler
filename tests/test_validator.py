"""Unit tests for deterministic guardrail engine in worker/validator.py (Task 6.2)."""

from __future__ import annotations

from typing import List
from worker.validator import (
    GuardrailValidator,
    contains_forbidden_term,
    extract_named_entities_and_terms,
    extract_numeric_tokens,
    verify_complete_bullet,
    verify_context_and_entities_preserved,
    verify_numeric_tokens_unchanged,
)


def _high_sim_embed(texts: List[str]) -> List[List[float]]:
    return [[0.9, 0.4, 0.1] for _ in texts]


def _low_sim_embed(texts: List[str]) -> List[List[float]]:
    # Orthogonal vectors -> cosine similarity = 0.0 (< 0.82 threshold)
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_forbidden_term_denylist_word_boundary_detection() -> None:
    forbidden = ["Java", "gRPC", "Go"]
    # Should match standalone "Java" (case-insensitive), NOT "JavaScript"
    assert contains_forbidden_term("Built microservices in JavaScript and Node.js.", forbidden) is None
    assert contains_forbidden_term("Migrated backend services to java and Kafka.", forbidden) == "Java"
    assert contains_forbidden_term("Implemented high-throughput gRPC endpoints.", forbidden) == "gRPC"


def test_numerical_entity_mutation_rejection() -> None:
    source = "Reduced p95 API latency by 20% across 3 regional clusters."
    # Mutated 20% -> 35%
    mutated = "Reduced p95 API latency by 35% across 3 regional clusters."
    ok, reason = verify_numeric_tokens_unchanged(source, mutated)
    assert ok is False
    assert reason is not None
    assert "35%" in reason

    # Dropped number ('3')
    dropped_num = "Reduced p95 API latency by 20% across regional clusters."
    ok_drop, reason_drop = verify_numeric_tokens_unchanged(source, dropped_num)
    assert ok_drop is False
    assert "3" in (reason_drop or "")

    # Preserved metrics
    valid = "Cut p95 API latency by 20% across 3 regional clusters."
    ok2, reason2 = verify_numeric_tokens_unchanged(source, valid)
    assert ok2 is True
    assert reason2 is None


def test_protected_metric_dropped_rejection() -> None:
    source = "Maintained 99.99% uptime across distributed PostgreSQL nodes."
    dropped = "Maintained high uptime across distributed PostgreSQL nodes."
    ok, reason = verify_numeric_tokens_unchanged(
        source, dropped, protected_metrics=["99.99%"]
    )
    assert ok is False
    assert reason is not None
    assert "99.99%" in reason


def test_validator_fallback_on_forbidden_term() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    source = "Built event-driven services in Python processing 10k requests/sec."
    generated = "Built event-driven services in Java processing 10k requests/sec."
    outcome = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=generated,
        forbidden_terms=["Java", "COBOL"],
    )
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source
    assert "Java" in (outcome.failure_reason or "")


def test_validator_fallback_on_metric_mutation() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    source = "Improved query throughput by 20% using Redis caching."
    generated = "Improved query throughput by 35% using Redis caching."
    outcome = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=generated,
    )
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source


def test_validator_fallback_when_cosine_similarity_below_082() -> None:
    validator = GuardrailValidator(similarity_threshold=0.82, embed_fn=_low_sim_embed)
    source = "Designed PostgreSQL schema migrations and automated backups."
    generated = "Led product marketing campaigns for enterprise customers."
    outcome = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=generated,
    )
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source
    assert outcome.similarity_score < 0.82


def test_validator_accepts_valid_rephrased_bullet_and_verbatim_mode() -> None:
    validator = GuardrailValidator(similarity_threshold=0.82, embed_fn=_high_sim_embed)
    source = "Reduced p95 latency by 42% using Redis read-through caching."
    generated = "Cut p95 API latency by 42% via Redis read-through caching."
    outcome = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=generated,
        forbidden_terms=["Java"],
        protected_metrics=["42%"],
        allow_rephrasing=True,
    )
    assert outcome.passed is True
    assert outcome.used_fallback is False
    assert outcome.final_bullet == generated

    # Verbatim-only mode bypasses LLM rephrasing and returns source directly
    verbatim_outcome = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=generated,
        allow_rephrasing=False,
    )
    assert verbatim_outcome.final_bullet == source
    assert verbatim_outcome.passed is True


def test_validator_rejects_incomplete_or_cutoff_bullets() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    source = (
        "Core Reliability & Systems Architecture: Maintained and supported 13 core repositories "
        "across microservices and React SPAs; investigated and resolved production hotfixes, "
        "authored shared TypeScript data contracts and UI component libraries, and integrated "
        "developer tooling (including AI tools and workflows - AWS Kiro using Claude models) "
        "to sustain platform reliability."
    )
    cutoff = (
        "Maintained 13 core repositories across microservices and React SPAs; authored shared "
        "TypeScript data contracts and UI component libraries; integrated AWS Kiro using"
    )
    outcome = validator.validate_bullet(source_bullet=source, generated_bullet=cutoff)
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source

    # Dangling preposition even if a period was appended
    dangling_with_period = (
        "Maintained 13 core repositories across microservices and integrated AWS Kiro using."
    )
    ok, reason = verify_complete_bullet(source, dangling_with_period)
    assert ok is False
    assert "using" in (reason or "")

    # Unbalanced parenthesis
    unbalanced = "Maintained 13 core repositories (including AI tools and AWS Kiro."
    ok2, reason2 = verify_complete_bullet(source, unbalanced)
    assert ok2 is False
    assert "parentheses" in (reason2 or "")


def test_validator_preserves_leading_topic_header_and_named_entities() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    source = (
        "Feeds 2.0 Modernization & Data Workflows: Engineered full-stack rebuild across 5+ repositories, "
        "delivering end-to-end capabilities from NestJS APIs and PostgreSQL migrations to React UIs; "
        "built multi-format ingestion (JSON/XML), deduplication, and notification lifecycle/TTL controls."
    )
    missing_header = (
        "Engineered a full-stack rebuild across 5+ repositories, delivering end-to-end capabilities "
        "from NestJS APIs and PostgreSQL migrations to React UIs, while building multi-format ingestion "
        "(JSON/XML), deduplication, and notification lifecycle/TTL controls."
    )
    outcome = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=missing_header,
    )
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source

    # Valid rewrite that preserves header, numbers, and named entities
    valid_with_header = (
        "Feeds 2.0 Modernization & Data Workflows: Engineered a full-stack rebuild across 5+ repositories, "
        "delivering end-to-end capabilities from NestJS APIs and PostgreSQL migrations to React UIs, "
        "and built multi-format ingestion (JSON/XML), deduplication, and notification lifecycle/TTL controls."
    )
    outcome_ok = validator.validate_bullet(
        source_bullet=source,
        generated_bullet=valid_with_header,
    )
    assert outcome_ok.passed is True
    assert outcome_ok.final_bullet == valid_with_header

    # Dropping a named tool like 'Claude' from source bullet is rejected
    claude_source = (
        "Core Reliability & Systems Architecture: Maintained 13 core repositories across React SPAs "
        "and integrated AWS Kiro using Claude models to sustain platform reliability."
    )
    dropped_claude = (
        "Core Reliability & Systems Architecture: Maintained 13 core repositories across React SPAs "
        "and integrated AWS Kiro using AI models to sustain platform reliability."
    )
    ok_ent, ent_reason = verify_context_and_entities_preserved(claude_source, dropped_claude)
    assert ok_ent is False
    assert "Claude" in (ent_reason or "")
    assert "Claude" in extract_named_entities_and_terms(claude_source)


def test_validator_rejects_bullet_exceeding_170_chars() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    source = "Short verified source bullet."
    too_long = ("A" * 174) + "."
    outcome = validator.validate_bullet(source_bullet=source, generated_bullet=too_long)
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source
    assert extract_numeric_tokens("25% and 42.5") == {"25%", "42.5"}


def test_merge_two_bullets_combines_primary_and_secondary_coherently() -> None:
    from worker.validator import merge_two_bullets

    b1 = "Delivered remote hardware and software technical support to field insurance agents and trained staff on proprietary rating systems."
    b2 = "Executed endpoint disk encryption (PGP, BestCrypt) across field agent machines to safeguard sensitive policyholder data."

    merged = merge_two_bullets(b1, b2)
    assert "Delivered remote hardware" in merged
    assert "; executed endpoint disk encryption (PGP, BestCrypt)" in merged
    assert "while" not in merged
    assert merged.endswith(".")


def test_merge_two_bullets_strips_leading_header_from_second_bullet() -> None:
    from worker.validator import merge_two_bullets

    b1 = "Webhooks & Third-Party API Integration: Developed real-time webhooks for email event streams (CoffeeScript, Node)."
    b2 = "Tooling & Automation: Implemented template cloning and automated HTML-to-PDF/PNG export tools (Angular 1.x, Node, Bootstrap)."

    merged = merge_two_bullets(b1, b2)
    assert "Tooling & Automation:" not in merged
    assert "while tooling" not in merged
    assert "; implemented template cloning" in merged
    assert "while" not in merged


def test_replace_while_conjunction_converts_to_semicolon_past_tense() -> None:
    from worker.validator import replace_while_conjunction

    sentence = (
        "Engineered scalable REST APIs and data access layers using Node.js, Express, and Knex, "
        "while migrating codebases to ES6 and configuring Webpack build tooling."
    )
    res = replace_while_conjunction(sentence)
    assert "while" not in res
    assert "; migrated codebases to ES6 and configuring Webpack build tooling." in res


def test_validator_validate_combined_bullet_accepts_valid_and_catches_forbidden() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    b1 = "Delivered remote hardware and software technical support to field insurance agents and trained staff on proprietary rating systems."
    b2 = "Executed endpoint disk encryption (PGP, BestCrypt) across field agent machines to safeguard sensitive policyholder data."

    candidate = (
        "Delivered remote hardware/software support to field agents on proprietary rating systems, "
        "while executing endpoint disk encryption (PGP, BestCrypt) to safeguard policyholder data."
    )
    outcome = validator.validate_combined_bullet(b1, b2, candidate)
    assert outcome.passed is True
    assert outcome.final_bullet == candidate

    # Rejects forbidden terms in combined bullet
    outcome_forbidden = validator.validate_combined_bullet(
        b1, b2, candidate, forbidden_terms=["PGP"]
    )
    assert outcome_forbidden.passed is False
    assert outcome_forbidden.used_fallback is True
    assert "Delivered remote hardware" in outcome_forbidden.final_bullet
