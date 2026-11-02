"""Deterministic negative keyword pruning and ChromaDB vector similarity ranking (FR-2.3)."""

from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Sequence, Tuple
import numpy as np

from worker.config import WorkerConfig
from worker.schemas import ScrapedJob

logger = logging.getLogger(__name__)


def prune_negative_titles(
    jobs: Sequence[ScrapedJob],
    negative_keywords: Sequence[str],
) -> List[ScrapedJob]:
    """
    Zero-cost deterministic regex pruning against negative_title_keywords (FR-1.5 / Task 3.5).
    """
    cleaned_keywords = [kw.strip() for kw in negative_keywords if kw and kw.strip()]
    if not cleaned_keywords:
        return list(jobs)

    pattern = re.compile(
        r"(?i)\b(" + "|".join(re.escape(kw) for kw in cleaned_keywords) + r")\b"
    )
    return [job for job in jobs if not pattern.search(job.title)]


FOREIGN_ONLY_LOCATION_MARKERS = re.compile(
    r"(?i)\b("
    r"uk|u\.k\.|united kingdom|england|london|scotland|ireland|dublin|"
    r"emea|europe|germany|berlin|munich|france|paris|spain|madrid|barcelona|"
    r"poland|warsaw|krakow|netherlands|amsterdam|sweden|stockholm|switzerland|zurich|"
    r"india|bengaluru|bangalore|hyderabad|mumbai|pune|delhi|gurgaon|noida|"
    r"apac|japan|tokyo|singapore|australia|sydney|melbourne|new zealand|"
    r"korea|seoul|taiwan|taipei|china|beijing|shanghai|hong kong|philippines|manila|"
    r"israel|tel aviv|brazil|sao paulo|latam|latin america|argentina|buenos aires|"
    r"colombia|bogota|chile|santiago|mexico city|romania|bucharest|portugal|lisbon|"
    r"austria|vienna|belgium|brussels|denmark|copenhagen|finland|helsinki|norway|oslo|"
    r"czech|prague|hungary|budapest|italy|milan|rome|greece|athens|turkey|istanbul"
    r")\b"
)

US_OR_GLOBAL_REMOTE_MARKERS = re.compile(
    r"(?i)\b(us|u\.s\.|usa|united states|north america|americas|anywhere|global|worldwide)\b"
)

HYBRID_OR_ONSITE_TITLE_LOC_MARKERS = re.compile(
    r"(?i)\b(hybrid|on-site|onsite|in-office|in office)\b"
)

HYBRID_OR_ONSITE_DESC_MARKERS = re.compile(
    r"(?i)("
    r"\b(workplace\s*type|work\s*environment|work\s*arrangement|work\s*model|location\s*type)\s*[:\-]\s*(hybrid|on-site|onsite|in-office|in office)\b|"
    r"\bthis\s+(role|position|job|opportunity)\s+is\s+(a\s+|an\s+)?(hybrid|on-site|onsite|in-office|in office)\b|"
    r"\b(hybrid|on-site|onsite|in-office)\s+(role|position|schedule|work\s+environment|work\s+model)\b|"
    r"\b\d+\s*(\+|to|-|–)?\s*\d*\s*days?\s+(per\s+week|a\s+week|/week|weekly)?\s*(in[- ]office|on[- ]site|in\s+the\s+office|in\s+our\s+[a-z\s]{1,25}office)\b|"
    r"\bin[- ]office\s+\d+\s*(\+|to|-|–)?\s*\d*\s*days?\b|"
    r"\bnot\s+a\s+remote\s+(role|position|job)\b|"
    r"\bmust\s+(be\s+able\s+to\s+commute|work\s+on[- ]site|work\s+in[- ]office)\b"
    r")"
)

EXPLICIT_FULL_REMOTE_DESC_MARKERS = re.compile(
    r"(?i)\b(100%\s*remote|fully\s+remote|work\s+from\s+anywhere|remote[- ]first|remote\s+across\s+the\s+(us|u\.s\.|united\s+states))\b"
)

KC_METRO_CITIES = (
    "kansas city",
    "overland park",
    "lee's summit",
    "lees summit",
    "olathe",
    "lenexa",
    "leawood",
    "shawnee",
    "independence",
    "blue springs",
    "liberty",
    "raytown",
    "grandview",
    "belton",
    "gladstone",
    "north kansas city",
    "mission, ks",
    "prairie village",
    "merriam",
    "riverside, mo",
    "parkville, mo",
    "grain valley",
    "harrisonville",
)


def is_local_market_match(
    loc_text: str,
    preferred_locations: Sequence[str],
) -> bool:
    """
    Returns True if `loc_text` is within the user's configured local market (e.g. Lee's Summit /
    50-mile Kansas City metro radius). Does NOT match an entire state like St. Louis, MO.
    """
    loc_lower = (loc_text or "").strip().lower()
    if not loc_lower:
        return False

    cleaned_locs = [loc.strip() for loc in preferred_locations if loc and loc.strip()]
    for target_loc in cleaned_locs:
        target_lower = target_loc.lower()
        if target_lower in loc_lower:
            return True
        parts = [p.strip() for p in target_loc.split(",") if p.strip()]
        city_part = parts[0].lower() if parts else ""
        if city_part and len(city_part) >= 3 and city_part in loc_lower:
            return True
        if any(kc in target_lower for kc in ("lee's summit", "lees summit", "kansas city", "overland park")):
            if any(metro in loc_lower for metro in KC_METRO_CITIES):
                return True

    return False


def has_hybrid_or_onsite_restriction(
    title: str,
    location: str,
    description_text: str = "",
) -> bool:
    """
    Returns True if the title, location, or job description indicates the role is Hybrid or On-Site
    rather than 100% remote.
    """
    if HYBRID_OR_ONSITE_TITLE_LOC_MARKERS.search(title or ""):
        return True
    if HYBRID_OR_ONSITE_TITLE_LOC_MARKERS.search(location or ""):
        return True
    if description_text and HYBRID_OR_ONSITE_DESC_MARKERS.search(description_text):
        return True
    return False


def is_eligible_remote_or_local(
    job: ScrapedJob,
    preferred_locations: Sequence[str],
    allow_remote: bool = True,
) -> bool:
    """
    Determines whether `job` matches either the user's local area (`preferred_locations`)
    or eligible 100% Remote status (`allow_remote`), while rejecting non-local hybrid/on-site roles
    and foreign-only roles.
    """
    loc_text = (job.location or "").strip()
    loc_lower = loc_text.lower()
    title_lower = (job.title or "").lower()
    desc_text = job.description_text or ""

    cleaned_locs = [loc.strip() for loc in preferred_locations if loc and loc.strip()]

    # 1. Check explicit local market match first (on-site, hybrid, and remote in local metro are all eligible)
    if is_local_market_match(loc_text, cleaned_locs):
        return True

    # 2. Outside local market: reject any job that is explicitly Hybrid or On-site
    if has_hybrid_or_onsite_restriction(job.title, loc_text, desc_text):
        return False

    # 3. Check remote eligibility
    has_explicit_remote_label = (
        "remote" in loc_lower
        or "anywhere" in loc_lower
        or "distributed" in loc_lower
        or "work from home" in loc_lower
        or "remote" in title_lower
    )
    # Strip "• Posted YYYY-MM-DD" suffix when inspecting raw location string
    base_loc = loc_lower.split("•")[0].strip()
    is_country_wide_loc = base_loc in {
        "united states",
        "usa",
        "us",
        "united states (remote)",
        "remote",
        "anywhere",
    }

    is_marked_remote = has_explicit_remote_label or (
        job.is_remote
        and (is_country_wide_loc or bool(EXPLICIT_FULL_REMOTE_DESC_MARKERS.search(desc_text)))
    )

    if allow_remote and is_marked_remote:
        # Reject roles restricted to a foreign country/region unless US/Global is also listed
        if FOREIGN_ONLY_LOCATION_MARKERS.search(loc_text) and not US_OR_GLOBAL_REMOTE_MARKERS.search(loc_text):
            return False
        if FOREIGN_ONLY_LOCATION_MARKERS.search(job.title) and not US_OR_GLOBAL_REMOTE_MARKERS.search(job.title):
            return False
        return True

    # If neither remote nor local area matched (and user specified either allow_remote or preferred_locations)
    if not allow_remote and not cleaned_locs:
        return True
    return False


def filter_by_location(
    jobs: Sequence[ScrapedJob],
    preferred_locations: Sequence[str],
    allow_remote: bool = True,
) -> List[ScrapedJob]:
    """Filters scraped jobs to only those matching `allow_remote` or `preferred_locations`."""
    return [
        job
        for job in jobs
        if is_eligible_remote_or_local(job, preferred_locations, allow_remote=allow_remote)
    ]


def _is_unhydrated_stage1_job(job: ScrapedJob) -> bool:
    """
    Returns True if the job is a Stage-1 unhydrated card (e.g. LinkedIn search card before
    lazy detail-page hydration) that only has a short title/company placeholder rather than a full JD.
    """
    desc = (job.description_text or "").strip()
    return (
        job.source.lower() == "linkedin"
        and ("Matched search query:" in desc or len(desc) < 250)
    )


def diversify_by_company(
    scored_jobs: Sequence[Tuple[ScrapedJob, float]],
    max_per_company: int = 2,
    interleave_sources: bool = True,
) -> List[Tuple[ScrapedJob, float]]:
    """
    Round-robin interleaves ranked jobs across distinct companies (enforcing `max_per_company`)
    and across job sources (`linkedin`, `indeed`, `remotive`, etc.) so no single company or
    job board monopolizes the top `max_jobs` discovery batch.
    """
    if max_per_company <= 0:
        company_capped = list(scored_jobs)
    else:
        by_company: dict[str, List[Tuple[ScrapedJob, float]]] = {}
        for job, score in scored_jobs:
            comp_key = (job.company or "Unknown").strip().lower()
            bucket = by_company.setdefault(comp_key, [])
            if len(bucket) < max_per_company:
                bucket.append((job, score))

        # Order companies by their highest-scoring job descending
        ordered_buckets = sorted(
            by_company.values(),
            key=lambda b: b[0][1] if b else 0.0,
            reverse=True,
        )

        company_capped = []
        for round_idx in range(max_per_company):
            for bucket in ordered_buckets:
                if round_idx < len(bucket):
                    company_capped.append(bucket[round_idx])

    if not interleave_sources or len(company_capped) <= 1:
        return company_capped

    by_source: dict[str, List[Tuple[ScrapedJob, float]]] = {}
    for job, score in company_capped:
        src_key = (job.source or "unknown").strip().lower()
        by_source.setdefault(src_key, []).append((job, score))

    if len(by_source) <= 1:
        return company_capped

    # Order source buckets by their top-scoring candidate descending
    source_buckets = sorted(
        by_source.values(),
        key=lambda b: b[0][1] if b else 0.0,
        reverse=True,
    )
    max_source_len = max(len(b) for b in source_buckets)
    interleaved: List[Tuple[ScrapedJob, float]] = []
    for idx in range(max_source_len):
        for s_bucket in source_buckets:
            if idx < len(s_bucket):
                interleaved.append(s_bucket[idx])

    return interleaved


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Computes cosine similarity between two 1-D embedding vectors."""
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class SemanticRanker:
    """
    Ranks scraped jobs using BAAI/bge-small-en-v1.5 embeddings and an in-container ChromaDB collection.
    Supports injecting a custom `embed_fn` for fast deterministic unit testing.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None,
    ) -> None:
        self.model_name = model_name or WorkerConfig().embedding_model_name
        self._embed_fn = embed_fn
        self._model = None

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generates normalized vector embeddings for a list of strings."""
        if not texts:
            return []
        if self._embed_fn is not None:
            return self._embed_fn(texts)
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        embeddings = self._model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in embeddings]

    def score_job(
        self,
        job: ScrapedJob,
        positive_titles: Sequence[str],
        profile_summary_text: str,
    ) -> float:
        """
        Computes combined semantic alignment score in [0.0, 1.0] against positive title anchors
        and the master career profile vector.
        """
        anchors = [t.strip() for t in positive_titles if t and t.strip()] or [job.title]
        corpus = [
            f"{job.title}\n{job.description_text[:2500]}",
            profile_summary_text or job.title,
            *anchors,
        ]
        vectors = self.embed_texts(corpus)
        job_vec = vectors[0]
        profile_vec = vectors[1]
        anchor_vecs = vectors[2:]

        profile_sim = max(0.0, cosine_similarity(job_vec, profile_vec))
        best_title_sim = max(
            (max(0.0, cosine_similarity(job_vec, a_vec)) for a_vec in anchor_vecs),
            default=profile_sim,
        )
        # Weighted blend: 60% profile semantic similarity, 40% positive title centroid alignment
        combined = round((0.60 * profile_sim) + (0.40 * best_title_sim), 2)
        return min(1.0, max(0.0, combined))

    def filter_and_rank(
        self,
        jobs: Sequence[ScrapedJob],
        positive_titles: Sequence[str],
        negative_keywords: Sequence[str],
        profile_summary_text: str,
        min_semantic_score: float = 0.70,
        preferred_locations: Optional[Sequence[str]] = None,
        allow_remote: bool = True,
        max_per_company: int = 2,
    ) -> List[Tuple[ScrapedJob, float]]:
        """
        Prunes negative titles, filters by location/remote eligibility, computes batched semantic scores,
        filters by `min_semantic_score`, and diversifies across companies via round-robin cap.
        """
        candidates = prune_negative_titles(jobs, negative_keywords)
        if not candidates:
            return []

        if preferred_locations is not None or allow_remote is not None:
            loc_filtered = filter_by_location(
                candidates,
                preferred_locations=preferred_locations or [],
                allow_remote=allow_remote,
            )
            logger.info(
                "Location/remote filter kept %d/%d jobs (allow_remote=%s, preferred_locations=%s).",
                len(loc_filtered),
                len(candidates),
                allow_remote,
                list(preferred_locations or []),
            )
            candidates = loc_filtered
            if not candidates:
                return []

        # Fast lexical pre-filter for large multi-department company boards (e.g. 500+ Cloudflare roles)
        anchors = [t.strip() for t in positive_titles if t and t.strip()]
        if len(candidates) > 40 and anchors:
            anchor_tokens = {
                tok.lower()
                for title in anchors
                for tok in re.findall(r"[a-zA-Z0-9+#]{3,}", title)
            } | {
                "engineer",
                "engineering",
                "developer",
                "software",
                "fullstack",
                "frontend",
                "backend",
                "platform",
                "systems",
                "architect",
                "data",
                "machine",
                "learning",
                "cloud",
                "devops",
                "sre",
                "security",
                "technical",
            }
            narrowed = [
                job
                for job in candidates
                if any(
                    tok.lower() in anchor_tokens
                    for tok in re.findall(r"[a-zA-Z0-9+#]{3,}", job.title)
                )
            ]
            if narrowed:
                logger.info(
                    "Title pre-filter narrowed %d scraped jobs to %d technical/matching candidates before vector embedding.",
                    len(candidates),
                    len(narrowed),
                )
                candidates = narrowed

        effective_anchors = anchors or [candidates[0].title]
        profile_text = profile_summary_text or candidates[0].title
        job_texts = [
            job.title if _is_unhydrated_stage1_job(job) else f"{job.title}\n{job.description_text[:1200]}"
            for job in candidates
        ]

        logger.info("Computing BGE vector embeddings for %d candidate jobs...", len(candidates))
        all_vectors = self.embed_texts([profile_text, *effective_anchors, *job_texts])
        profile_vec = all_vectors[0]
        anchor_vecs = all_vectors[1 : 1 + len(effective_anchors)]
        job_vecs = all_vectors[1 + len(effective_anchors) :]

        scored: List[Tuple[ScrapedJob, float]] = []
        for job, job_vec in zip(candidates, job_vecs):
            profile_sim = max(0.0, cosine_similarity(job_vec, profile_vec))
            best_title_sim = max(
                (max(0.0, cosine_similarity(job_vec, a_vec)) for a_vec in anchor_vecs),
                default=profile_sim,
            )
            if _is_unhydrated_stage1_job(job):
                # Stage-1 LinkedIn cards do not yet have full descriptions (hydrated lazily in Stage 2
                # to prevent 429s), so weight title anchor alignment at 85% and profile summary at 15%
                combined = min(1.0, max(0.0, round((0.85 * best_title_sim) + (0.15 * profile_sim), 2)))
            else:
                combined = min(1.0, max(0.0, round((0.60 * profile_sim) + (0.40 * best_title_sim), 2)))
            if combined >= min_semantic_score:
                scored.append((job, combined))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return diversify_by_company(scored, max_per_company=max_per_company)

