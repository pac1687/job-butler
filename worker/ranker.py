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
        embeddings = self._model.encode(texts, normalize_embeddings=True)
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
    ) -> List[Tuple[ScrapedJob, float]]:
        """
        Prunes negative titles, computes semantic scores, filters by `min_semantic_score`,
        and sorts descending.
        """
        candidates = prune_negative_titles(jobs, negative_keywords)
        scored: List[Tuple[ScrapedJob, float]] = []

        for job in candidates:
            score = self.score_job(job, positive_titles, profile_summary_text)
            if score >= min_semantic_score:
                scored.append((job, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

