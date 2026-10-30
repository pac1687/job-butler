"""Unit tests for worker/collector.py, worker/ranker.py, and worker/preflight.py."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

from worker.cleaner import compute_content_hash
from worker.collector import JobCollector
from worker.preflight import check_lm_studio_health
from worker.ranker import SemanticRanker, prune_negative_titles
from worker.schemas import ScrapedJob


def _make_job(title: str, company: str = "Acme", url_suffix: str = "1") -> ScrapedJob:
    desc = f"Role for {title} building TypeScript and Python backend systems."
    return ScrapedJob(
        source="greenhouse",
        source_id=url_suffix,
        title=title,
        company=company,
        location="Remote",
        is_remote=True,
        url=f"https://example.com/jobs/{url_suffix}",
        content_hash=compute_content_hash(title, company, desc),
        description_text=desc,
    )


def test_prune_negative_titles_filters_blacklisted_keywords() -> None:
    jobs = [
        _make_job("Senior Software Engineer", url_suffix="1"),
        _make_job("Engineering Manager, Platform", url_suffix="2"),
        _make_job("Staff Backend Engineer", url_suffix="3"),
        _make_job("Full Stack Engineer", url_suffix="4"),
    ]
    kept = prune_negative_titles(jobs, ["Manager", "Staff", "Director"])
    titles = [j.title for j in kept]
    assert titles == ["Senior Software Engineer", "Full Stack Engineer"]


def test_semantic_ranker_filters_and_orders_descending() -> None:
    jobs = [
        _make_job("Full Stack Engineer", url_suffix="1"),
        _make_job("Engineering Director", url_suffix="2"),
    ]

    def fake_embed(texts: List[str]) -> List[List[float]]:
        return [[0.8, 0.6, 0.0] for _ in texts]

    ranker = SemanticRanker(embed_fn=fake_embed)
    ranked = ranker.filter_and_rank(
        jobs=jobs,
        positive_titles=["Full Stack Engineer"],
        negative_keywords=["Director"],
        profile_summary_text="Full stack TypeScript and Python engineer",
        min_semantic_score=0.70,
    )
    assert len(ranked) == 1
    assert ranked[0][0].title == "Full Stack Engineer"
    assert ranked[0][1] >= 0.70


def test_collector_deduplicate_jobs() -> None:
    j1 = _make_job("Senior Engineer", url_suffix="1")
    j1_dup = _make_job("Senior Engineer", url_suffix="2")  # identical content_hash
    j2 = _make_job("Backend Engineer", url_suffix="3")

    unique = JobCollector.deduplicate_jobs([j1, j1_dup, j2], existing_hashes=set())
    assert len(unique) == 2

    unique_with_existing = JobCollector.deduplicate_jobs(
        [j1, j2], existing_hashes={j1.content_hash}
    )
    assert len(unique_with_existing) == 1
    assert unique_with_existing[0].title == "Backend Engineer"


def test_preflight_health_check_success_and_offline() -> None:
    mock_ok = MagicMock()
    mock_ok.status_code = 200
    mock_ok.json.return_value = {"data": [{"id": "qwen2.5-7b-instruct"}]}

    with patch("worker.preflight.httpx.get", return_value=mock_ok):
        assert check_lm_studio_health("http://host.docker.internal:1234/v1") is True

    mock_empty = MagicMock()
    mock_empty.status_code = 200
    mock_empty.json.return_value = {"data": []}

    with patch("worker.preflight.httpx.get", return_value=mock_empty):
        assert check_lm_studio_health("http://host.docker.internal:1234/v1") is False

