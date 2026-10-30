"""Multi-tier job ingestion: Tier-1 Direct ATS APIs, Tier-2 JobSpy fallback, and SHA-256 deduplication."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
import httpx

from worker.cleaner import clean_job_description, compute_content_hash
from worker.schemas import ScrapedJob

logger = logging.getLogger(__name__)


class JobCollector:
    """Fetches, cleans, and deduplicates job listings across Tier-1 ATS APIs and Tier-2 JobSpy."""

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = http_client or httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "JobButlerWorker/1.0"},
        )
        self.sleep_fn = sleep_fn

    def fetch_greenhouse_board(self, board_token: str) -> List[ScrapedJob]:
        """Fetches open postings from Greenhouse API: /v1/boards/{board}/jobs?content=true."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        jobs: List[ScrapedJob] = []
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("jobs", []):
                title = item.get("title", "").strip()
                location = (item.get("location") or {}).get("name", "Remote")
                raw_desc = item.get("content", "")
                cleaned = clean_job_description(raw_desc)
                if not title or not cleaned:
                    continue
                content_hash = compute_content_hash(title, board_token, cleaned)
                jobs.append(
                    ScrapedJob(
                        source="greenhouse",
                        source_id=str(item.get("id", "")),
                        title=title,
                        company=board_token.capitalize(),
                        location=location,
                        is_remote="remote" in location.lower(),
                        url=item.get("absolute_url", url),
                        content_hash=content_hash,
                        description_text=cleaned,
                    )
                )
        except Exception as exc:
            logger.warning("Greenhouse scrape failed for board '%s': %s", board_token, exc)
        return jobs

    def fetch_lever_board(self, board_token: str) -> List[ScrapedJob]:
        """Fetches open postings from Lever API: https://api.lever.co/v0/postings/{board}?mode=json."""
        url = f"https://api.lever.co/v0/postings/{board_token}?mode=json"
        jobs: List[ScrapedJob] = []
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            postings = resp.json()
            if not isinstance(postings, list):
                return []
            for item in postings:
                title = item.get("text", "").strip()
                categories = item.get("categories") or {}
                location = categories.get("location") or "Remote"
                raw_desc = f"{item.get('descriptionPlain', '')}\n{item.get('additionalPlain', '')}"
                cleaned = clean_job_description(raw_desc)
                if not title or not cleaned:
                    continue
                content_hash = compute_content_hash(title, board_token, cleaned)
                jobs.append(
                    ScrapedJob(
                        source="lever",
                        source_id=str(item.get("id", "")),
                        title=title,
                        company=board_token.capitalize(),
                        location=location,
                        is_remote="remote" in location.lower()
                        or item.get("workplaceType") == "remote",
                        url=item.get("hostedUrl", url),
                        content_hash=content_hash,
                        description_text=cleaned,
                    )
                )
        except Exception as exc:
            logger.warning("Lever scrape failed for board '%s': %s", board_token, exc)
        return jobs

    def fetch_ashby_board(self, board_token: str) -> List[ScrapedJob]:
        """Fetches open postings from Ashby Open Posting API."""
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board_token}?includeCompensation=true"
        jobs: List[ScrapedJob] = []
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("jobs", []):
                title = item.get("title", "").strip()
                location = item.get("location", "Remote")
                raw_desc = item.get("descriptionHtml") or item.get("descriptionPlain", "")
                cleaned = clean_job_description(raw_desc)
                if not title or not cleaned:
                    continue
                comp = (item.get("compensation") or {}).get("compensationTierSummary")
                content_hash = compute_content_hash(title, board_token, cleaned)
                jobs.append(
                    ScrapedJob(
                        source="ashby",
                        source_id=str(item.get("id", title)),
                        title=title,
                        company=board_token.capitalize(),
                        location=location,
                        is_remote=bool(item.get("isRemote", "remote" in location.lower())),
                        url=item.get("jobUrl", url),
                        content_hash=content_hash,
                        description_text=cleaned,
                        salary_range=comp,
                    )
                )
        except Exception as exc:
            logger.warning("Ashby scrape failed for board '%s': %s", board_token, exc)
        return jobs

    def fetch_tier2_jobspy(
        self,
        search_terms: List[str],
        results_wanted: int = 15,
        max_retries: int = 2,
    ) -> List[ScrapedJob]:
        """
        Tier-2 Aggregator Fallback using JobSpy with exponential backoff and jittered delays (2-5s).
        """
        try:
            from jobspy import scrape_jobs  # type: ignore
        except ImportError:
            logger.warning("python-jobspy is not installed; skipping Tier-2 fallback.")
            return []

        collected: List[ScrapedJob] = []
        for term in search_terms:
            # Jittered delay between 2 and 5 seconds per FR-2.2
            jitter = random.uniform(2.0, 5.0)
            self.sleep_fn(jitter)

            for attempt in range(max_retries):
                try:
                    df = scrape_jobs(
                        site_name=["indeed", "linkedin"],
                        search_term=term,
                        results_wanted=results_wanted,
                        is_remote=True,
                    )
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            title = str(row.get("title") or "").strip()
                            company = str(row.get("company") or "Unknown").strip()
                            raw_desc = str(row.get("description") or "").strip()
                            url = str(row.get("job_url") or "").strip()
                            cleaned = clean_job_description(raw_desc)
                            if not title or not cleaned or not url:
                                continue
                            content_hash = compute_content_hash(title, company, cleaned)
                            collected.append(
                                ScrapedJob(
                                    source=str(row.get("site") or "jobspy"),
                                    source_id=str(row.get("id") or content_hash[:16]),
                                    title=title,
                                    company=company,
                                    location=str(row.get("location") or "Remote"),
                                    is_remote=True,
                                    url=url,
                                    content_hash=content_hash,
                                    description_text=cleaned,
                                )
                            )
                    break
                except Exception as exc:
                    backoff = (2 ** attempt) + random.uniform(2.0, 5.0)
                    logger.warning(
                        "Tier-2 JobSpy attempt %d failed for '%s': %s (backoff=%.1fs)",
                        attempt + 1,
                        term,
                        exc,
                        backoff,
                    )
                    self.sleep_fn(backoff)

        return collected

    def fetch_single_url(self, target_url: str) -> Optional[ScrapedJob]:
        """Scrapes an arbitrary job posting URL submitted via the on-demand task queue."""
        try:
            resp = self.client.get(target_url)
            resp.raise_for_status()
            cleaned = clean_job_description(resp.text)
            if not cleaned:
                return None
            # Attempt basic title extraction
            title = "Submitted Opportunity"
            if "<title>" in resp.text.lower():
                start = resp.text.lower().find("<title>") + 7
                end = resp.text.lower().find("</title>", start)
                if end > start:
                    title = resp.text[start:end].strip()[:120]
            company = target_url.split("/")[2].replace("www.", "")
            content_hash = compute_content_hash(title, company, cleaned)
            return ScrapedJob(
                source="on_demand_url",
                source_id=content_hash[:16],
                title=title,
                company=company,
                location="Remote",
                is_remote=True,
                url=target_url,
                content_hash=content_hash,
                description_text=cleaned,
            )
        except Exception as exc:
            logger.error("Failed to fetch on-demand URL %s: %s", target_url, exc)
            return None

    @staticmethod
    def deduplicate_jobs(
        incoming: Iterable[ScrapedJob],
        existing_hashes: Set[str],
    ) -> List[ScrapedJob]:
        """Filters out duplicate jobs by SHA-256 content_hash and URL within batch and against DB."""
        seen_hashes = set(existing_hashes)
        seen_urls: Set[str] = set()
        unique: List[ScrapedJob] = []

        for job in incoming:
            if job.content_hash in seen_hashes or job.url in seen_urls:
                continue
            seen_hashes.add(job.content_hash)
            seen_urls.add(job.url)
            unique.append(job)

        return unique

    def collect_all(
        self,
        ats_boards: Dict[str, List[str]],
        positive_titles: List[str],
        existing_hashes: Set[str],
        enable_tier2: bool = True,
    ) -> List[ScrapedJob]:
        """Executes Tier-1 ATS scraping and optional Tier-2 fallback, returning deduplicated jobs."""
        raw_jobs: List[ScrapedJob] = []

        for board in ats_boards.get("greenhouse", []):
            raw_jobs.extend(self.fetch_greenhouse_board(board))
        for board in ats_boards.get("lever", []):
            raw_jobs.extend(self.fetch_lever_board(board))
        for board in ats_boards.get("ashby", []):
            raw_jobs.extend(self.fetch_ashby_board(board))

        if enable_tier2 and not raw_jobs and positive_titles:
            raw_jobs.extend(self.fetch_tier2_jobspy(positive_titles[:3]))

        return self.deduplicate_jobs(raw_jobs, existing_hashes)

