"""Unit tests for deterministic guardrail engine in worker/validator.py (Task 6.2)."""

from __future__ import annotations

from typing import List
from worker.validator import (
    GuardrailValidator,
    contains_forbidden_term,
    extract_numeric_tokens,
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


def test_validator_rejects_bullet_exceeding_170_chars() -> None:
    validator = GuardrailValidator(embed_fn=_high_sim_embed)
    source = "Short verified source bullet."
    too_long = "A" * 175
    outcome = validator.validate_bullet(source_bullet=source, generated_bullet=too_long)
    assert outcome.passed is False
    assert outcome.used_fallback is True
    assert outcome.final_bullet == source
    assert extract_numeric_tokens("25% and 42.5") == {"25%", "42.5"}

