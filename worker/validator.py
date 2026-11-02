"""Deterministic Guardrail Validation Gate (SPEC.md Section 3.4 & FR-2.5)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Set, Tuple

from worker.ranker import cosine_similarity

logger = logging.getLogger(__name__)

# Numerical token extractor per SPEC.md Section 3.4: captures numbers and optional trailing %
NUMERIC_TOKEN_REGEX = re.compile(r"\b\d+(?:\.\d+)?(?:%|\b)")


@dataclass(frozen=True)
class BulletValidationOutcome:
    """Result of auditing a single generated resume bullet against its verified source bullet."""

    final_bullet: str
    passed: bool
    used_fallback: bool
    failure_reason: Optional[str] = None
    similarity_score: float = 1.0


def contains_forbidden_term(text: str, forbidden_terms: Sequence[str]) -> Optional[str]:
    """
    Case-insensitive word-boundary regex scanner against `tailoring_rules.forbidden_terms`.
    Returns the matched forbidden term if found, otherwise None.
    """
    for term in forbidden_terms:
        cleaned = (term or "").strip()
        if not cleaned:
            continue
        pattern = re.compile(r"(?i)(?<!\w)" + re.escape(cleaned) + r"(?!\w)")
        if pattern.search(text):
            return cleaned
    return None


def extract_numeric_tokens(text: str) -> Set[str]:
    """Extracts all numerical/percentage tokens matching \\b\\d+(?:\\.\\d+)?%?\\b."""
    return set(NUMERIC_TOKEN_REGEX.findall(text or ""))


def verify_numeric_tokens_unchanged(
    source_bullet: str,
    generated_bullet: str,
    protected_metrics: Sequence[str] = (),
) -> Tuple[bool, Optional[str]]:
    """
    Ensures:
    1. No numeric token appears in `generated_bullet` that did not exist in `source_bullet`.
    2. Any `protected_metrics` present in `source_bullet` are preserved intact in `generated_bullet`.
    """
    source_tokens = extract_numeric_tokens(source_bullet)
    generated_tokens = extract_numeric_tokens(generated_bullet)

    fabricated = generated_tokens - source_tokens
    if fabricated:
        return (
            False,
            f"Fabricated or mutated numeric metric(s): {sorted(fabricated)}",
        )

    for metric in protected_metrics:
        if metric and metric in source_bullet and metric not in generated_bullet:
            return (
                False,
                f"Protected metric '{metric}' was dropped or altered",
            )

    return True, None


class GuardrailValidator:
    """
    Audits LLM-tailored bullets before Typst compilation:
    1. Denylist scanner rejecting bullets containing forbidden_terms.
    2. Numerical entity verification ensuring no new/mutated metric tokens exist.
    3. Semantic drift check ensuring cosine similarity to source bullet >= 0.82.
    4. Automatic fallback to original verbatim source text if any check fails.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.82,
        max_bullet_chars: int = 170,
        embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.max_bullet_chars = max_bullet_chars
        self._embed_fn = embed_fn
        self._model = None

    def _compute_similarity(self, source_bullet: str, generated_bullet: str) -> float:
        if source_bullet.strip() == generated_bullet.strip():
            return 1.0
        if self._embed_fn is not None:
            vecs = self._embed_fn([source_bullet, generated_bullet])
            return cosine_similarity(vecs[0], vecs[1])

        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        vecs = self._model.encode(
            [source_bullet, generated_bullet], normalize_embeddings=True
        )
        return cosine_similarity(vecs[0].tolist(), vecs[1].tolist())

    def validate_bullet(
        self,
        source_bullet: str,
        generated_bullet: str,
        forbidden_terms: Sequence[str] = (),
        protected_metrics: Sequence[str] = (),
        allow_rephrasing: bool = True,
    ) -> BulletValidationOutcome:
        """
        Audits `generated_bullet` against `source_bullet`.
        Reverts to `source_bullet` automatically if any guardrail check fails.
        """
        if not allow_rephrasing:
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=True,
                used_fallback=False,
                failure_reason=None,
                similarity_score=1.0,
            )

        candidate = (generated_bullet or "").strip()
        if not candidate:
            logger.warning("Empty generated bullet; reverting to verbatim source.")
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason="Empty bullet",
                similarity_score=0.0,
            )

        allowed_len = max(self.max_bullet_chars, len(source_bullet.strip()) + 25)
        if len(candidate) > allowed_len:
            logger.warning(
                "Bullet exceeded %d chars (%d); reverting to verbatim source.",
                allowed_len,
                len(candidate),
            )
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason=f"Length {len(candidate)} > {allowed_len}",
                similarity_score=1.0,
            )

        # 1. Forbidden terms check
        violated_term = contains_forbidden_term(candidate, forbidden_terms)
        if violated_term is not None:
            logger.warning(
                "Guardrail rejected bullet due to forbidden term '%s'; reverting to source.",
                violated_term,
            )
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason=f"Forbidden term detected: '{violated_term}'",
                similarity_score=0.0,
            )

        # 2. Numerical metric check
        metrics_ok, metric_error = verify_numeric_tokens_unchanged(
            source_bullet=source_bullet,
            generated_bullet=candidate,
            protected_metrics=protected_metrics,
        )
        if not metrics_ok:
            logger.warning(
                "Guardrail rejected bullet due to metric mutation (%s); reverting to source.",
                metric_error,
            )
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason=metric_error,
                similarity_score=0.0,
            )

        # 3. Semantic cosine similarity drift check (>= 0.82)
        sim = self._compute_similarity(source_bullet, candidate)
        if sim < self.similarity_threshold:
            logger.warning(
                "Guardrail rejected bullet due to semantic drift (similarity=%.3f < %.2f); reverting to source.",
                sim,
                self.similarity_threshold,
            )
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason=f"Semantic similarity {sim:.3f} below threshold {self.similarity_threshold}",
                similarity_score=sim,
            )

        return BulletValidationOutcome(
            final_bullet=candidate,
            passed=True,
            used_fallback=False,
            failure_reason=None,
            similarity_score=sim,
        )
