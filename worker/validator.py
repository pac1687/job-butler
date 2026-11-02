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

# Leading topic/project header prefix before a colon, e.g. "Feeds 2.0 Modernization & Data Workflows: ..."
LEADING_HEADER_REGEX = re.compile(r"^([A-Z][^:;\n]{2,65}):\s+")

# Words that must never appear as the final word of a resume bullet
DANGLING_TERMINAL_WORDS: Set[str] = {
    "a",
    "across",
    "after",
    "against",
    "along",
    "amid",
    "among",
    "an",
    "and",
    "around",
    "as",
    "at",
    "before",
    "behind",
    "below",
    "beneath",
    "beside",
    "between",
    "beyond",
    "both",
    "but",
    "by",
    "despite",
    "down",
    "during",
    "either",
    "except",
    "for",
    "from",
    "if",
    "in",
    "including",
    "inside",
    "into",
    "its",
    "like",
    "near",
    "neither",
    "nor",
    "of",
    "off",
    "on",
    "onto",
    "or",
    "our",
    "over",
    "per",
    "plus",
    "since",
    "so",
    "such",
    "than",
    "that",
    "the",
    "their",
    "through",
    "throughout",
    "to",
    "toward",
    "towards",
    "under",
    "underneath",
    "unless",
    "unlike",
    "until",
    "up",
    "upon",
    "using",
    "via",
    "when",
    "where",
    "whereas",
    "whether",
    "which",
    "while",
    "who",
    "whom",
    "whose",
    "with",
    "within",
    "without",
    "yet",
}


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
    2. No numeric token from `source_bullet` (including version numbers like '2.0' or counts like '5') is dropped.
    3. Any `protected_metrics` present in `source_bullet` are preserved intact in `generated_bullet`.
    """
    for metric in protected_metrics:
        if metric and metric in source_bullet and metric not in generated_bullet:
            return (
                False,
                f"Protected metric '{metric}' was dropped or altered",
            )

    source_tokens = extract_numeric_tokens(source_bullet)
    generated_tokens = extract_numeric_tokens(generated_bullet)

    fabricated = generated_tokens - source_tokens
    if fabricated:
        return (
            False,
            f"Fabricated or mutated numeric metric(s): {sorted(fabricated)}",
        )

    dropped = source_tokens - generated_tokens
    if dropped:
        return (
            False,
            f"Dropped numeric token(s) from source bullet: {sorted(dropped)}",
        )

    return True, None


def extract_named_entities_and_terms(bullet: str) -> List[str]:
    """
    Extracts technical identifiers, acronyms, and mid-sentence proper nouns from `bullet`
    (e.g., 'Claude', 'Kiro', 'AWS', 'NestJS', 'PostgreSQL', 'TypeScript', 'React', 'JSON', 'XML', 'TTL').
    """
    body = LEADING_HEADER_REGEX.sub("", (bullet or "").strip())
    tokens: List[str] = []
    seen: Set[str] = set()

    # Split into clauses on sentence/clause boundaries so we can distinguish clause-initial words
    clauses = re.split(r"(?:^|[.;!?]\s+)", body)
    for clause in clauses:
        words = re.findall(r"\b[A-Za-z][A-Za-z0-9.+/-]*\b", clause.strip())
        for idx, raw_word in enumerate(words):
            word = raw_word.rstrip(".,;:!?/+-")
            if len(word) < 2:
                continue
            is_acronym = word.isupper() and len(word) >= 2
            is_mixed_case = any(c.isupper() for c in word[1:]) and any(c.islower() for c in word)
            is_mid_clause_proper = idx > 0 and word[0].isupper() and word[1:].islower()

            if is_acronym or is_mixed_case or is_mid_clause_proper:
                low = word.lower()
                if low not in seen:
                    seen.add(low)
                    tokens.append(word)
    return tokens


def verify_context_and_entities_preserved(
    source_bullet: str,
    generated_bullet: str,
) -> Tuple[bool, Optional[str]]:
    """
    Ensures that:
    1. If `source_bullet` starts with a `<Topic / Project Header>:` prefix (e.g.,
       'Feeds 2.0 Modernization & Data Workflows:'), that prefix context is preserved.
    2. Named tools, platforms, acronyms, and proper nouns in `source_bullet`
       (e.g., Claude, AWS, Kiro, NestJS, PostgreSQL, React, JSON, XML, TTL) are not dropped.
    """
    src = (source_bullet or "").strip()
    gen = (generated_bullet or "").strip()

    header_match = LEADING_HEADER_REGEX.match(src)
    if header_match:
        expected_header = header_match.group(1).strip()
        if not gen.lower().startswith(expected_header.lower() + ":"):
            return (
                False,
                f"Dropped leading topic/project context header '{expected_header}:'",
            )

    required_entities = extract_named_entities_and_terms(src)
    for entity in required_entities:
        pattern = re.compile(r"(?i)(?<!\w)" + re.escape(entity) + r"(?!\w)")
        if not pattern.search(gen):
            return (
                False,
                f"Dropped named tool/entity '{entity}' from source bullet",
            )

    return True, None


def merge_two_bullets(b1: str, b2: str) -> str:
    """
    Deterministically combines two bullet points into a single coherent sentence,
    preserving the primary duty (first bullet) while integrating the secondary project (second bullet).
    Safely strips any leading topic header from the second bullet so it doesn't get embedded mid-sentence.
    """
    clean1 = (b1 or "").strip().rstrip(".")
    clean2 = (b2 or "").strip().rstrip(".")
    if not clean1:
        return f"{clean2}." if clean2 else ""
    if not clean2:
        return f"{clean1}."

    # Strip any leading topic header from b2 so it doesn't get embedded mid-sentence
    # (e.g. 'Tooling & Automation: Implemented...' -> 'Implemented...')
    header_match2 = LEADING_HEADER_REGEX.match(clean2)
    if header_match2:
        clean2 = clean2[header_match2.end():].strip()

    words2 = clean2.split()
    if not words2:
        return f"{clean1}."

    first_word = words2[0]
    first_lower = first_word.lower()

    if first_lower.endswith("ing"):
        participle = first_lower
    else:
        verb_map = {
            "executed": "executing",
            "delivered": "delivering",
            "managed": "managing",
            "supported": "supporting",
            "trained": "training",
            "built": "building",
            "led": "leading",
            "designed": "designing",
            "implemented": "implementing",
            "configured": "configuring",
            "maintained": "maintaining",
            "developed": "developing",
            "created": "creating",
            "engineered": "engineering",
            "automated": "automating",
            "provided": "providing",
            "resolved": "resolving",
            "performed": "performing",
            "deployed": "deploying",
            "established": "establishing",
            "integrated": "integrating",
            "authored": "authoring",
        }
        if first_lower in verb_map:
            participle = verb_map[first_lower]
        elif first_lower.endswith("ed"):
            participle = first_lower[:-2] + "ing"
        else:
            participle = first_lower

    merged_second = " ".join([participle] + words2[1:])
    return f"{clean1}, while {merged_second}."


def verify_complete_bullet(
    source_bullet: str,
    generated_bullet: str,
) -> Tuple[bool, Optional[str]]:
    """
    Ensures `generated_bullet` is a complete, grammatically terminated bullet and not
    cut off mid-sentence (e.g., ending with 'using', trailing punctuation, or unclosed parens).
    """
    candidate = (generated_bullet or "").strip()
    if not candidate:
        return False, "Empty bullet"

    if candidate.count("(") != candidate.count(")") or candidate.count("[") != candidate.count("]"):
        return False, "Unbalanced parentheses or brackets"

    if candidate.endswith((",", ";", ":", "-", "–", "—", "/", "(", "[")) or candidate.endswith("..."):
        return False, f"Incomplete trailing punctuation in '{candidate[-10:]}'"

    if source_bullet.strip().endswith(".") and not candidate.endswith("."):
        return False, "Missing terminal period (truncated sentence)"

    words = re.findall(r"[A-Za-z]+", candidate)
    if not words:
        return False, "Bullet contains no alphabetic words"

    last_word = words[-1].lower()
    if last_word in DANGLING_TERMINAL_WORDS:
        return False, f"Bullet ends on dangling word '{words[-1]}'"

    return True, None


class GuardrailValidator:
    """
    Audits LLM-tailored bullets before Typst compilation:
    0. Completeness check rejecting cut-off/truncated sentences or dangling terminal words.
    1. Denylist scanner rejecting bullets containing forbidden_terms.
    2. Numerical entity verification ensuring no new/mutated/dropped metric tokens exist.
    3. Context & named-entity preservation (topic headers like 'Feeds 2.0...:' and tools like 'Claude').
    4. Semantic drift check ensuring cosine similarity to source bullet >= 0.82.
    5. Automatic fallback to original verbatim source text if any check fails.
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

        # 0. Completeness / anti-truncation check
        complete_ok, incomplete_reason = verify_complete_bullet(source_bullet, candidate)
        if not complete_ok:
            logger.warning(
                "Guardrail rejected incomplete/cutoff bullet (%s); reverting to verbatim source.",
                incomplete_reason,
            )
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason=incomplete_reason,
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

        # 3. Context header & named-entity preservation check
        context_ok, context_error = verify_context_and_entities_preserved(
            source_bullet=source_bullet,
            generated_bullet=candidate,
        )
        if not context_ok:
            logger.warning(
                "Guardrail rejected bullet due to lost context/entity (%s); reverting to source.",
                context_error,
            )
            return BulletValidationOutcome(
                final_bullet=source_bullet,
                passed=False,
                used_fallback=True,
                failure_reason=context_error,
                similarity_score=0.0,
            )

        # 4. Semantic cosine similarity drift check (>= 0.82)
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

    def validate_combined_bullet(
        self,
        b1: str,
        b2: str,
        generated_bullet: str,
        forbidden_terms: Sequence[str] = (),
        protected_metrics: Sequence[str] = (),
        max_chars: int = 260,
    ) -> BulletValidationOutcome:
        """
        Validates an LLM-synthesized combined bullet from two source accomplishments.
        Checks completeness, forbidden terms, metric tokens, and named entities from both source bullets.
        Falls back to deterministic merge_two_bullets(b1, b2) if validation fails.
        """
        candidate = (generated_bullet or "").strip()
        fallback = merge_two_bullets(b1, b2)

        if not candidate:
            return BulletValidationOutcome(
                final_bullet=fallback,
                passed=False,
                used_fallback=True,
                failure_reason="Empty candidate bullet",
            )

        complete_ok, incomplete_reason = verify_complete_bullet(b1, candidate)
        if not complete_ok:
            return BulletValidationOutcome(
                final_bullet=fallback,
                passed=False,
                used_fallback=True,
                failure_reason=incomplete_reason,
            )

        if len(candidate) > max_chars:
            return BulletValidationOutcome(
                final_bullet=fallback,
                passed=False,
                used_fallback=True,
                failure_reason=f"Combined bullet length {len(candidate)} exceeds {max_chars}",
            )

        violated_term = contains_forbidden_term(candidate, forbidden_terms)
        if violated_term is not None:
            return BulletValidationOutcome(
                final_bullet=fallback,
                passed=False,
                used_fallback=True,
                failure_reason=f"Forbidden term detected: '{violated_term}'",
            )

        combined_src = f"{b1} {b2}"
        num_ok, num_reason = verify_numeric_tokens_unchanged(
            combined_src, candidate, protected_metrics
        )
        if not num_ok:
            return BulletValidationOutcome(
                final_bullet=fallback,
                passed=False,
                used_fallback=True,
                failure_reason=num_reason,
            )

        return BulletValidationOutcome(
            final_bullet=candidate,
            passed=True,
            used_fallback=False,
            failure_reason=None,
            similarity_score=1.0,
        )
