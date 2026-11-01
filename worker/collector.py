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

# Mega-cap giants and staffing/spam aggregators excluded from Tier-2 JobSpy discovery
EXCLUDED_TIER2_COMPANIES = {
    "amazon",
    "amazon web services",
    "aws",
    "google",
    "meta",
    "apple",
    "microsoft",
    "netflix",
    "stripe",
    "openai",
    "cloudflare",
    "uber",
    "airbnb",
    "coinbase",
    "palantir",
    "datadog",
    "deloitte",
    "accenture",
    "cognizant",
    "infosys",
    "tata consultancy services",
    "tcs",
    "wipro",
    "capgemini",
    "revature",
    "synergisticit",
    "dataannotation",
    "data annotation",
    "outlier",
    "mercor",
    "turing",
    "bairesdev",
    "crossover",
    "canonical",
    "cybercoders",
    "jobot",
    "dice",
    "lensa",
    "tie talent",
}


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
        location: str = "United States",
        is_remote: bool = True,
        results_wanted: int = 25,
        distance: int = 50,
        max_retries: int = 2,
    ) -> List[ScrapedJob]:
        """
        Tier-2 Aggregator Discovery using JobSpy (Indeed batch GraphQL with 50-mile metro radius)
        with exponential backoff and jittered delays (1.5-3.5s).
        Avoids LinkedIn unproxied scraping which ignores `is_remote` and triggers HTTP 429 blocks.
        """
        try:
            from jobspy import scrape_jobs  # type: ignore
        except ImportError:
            logger.warning("python-jobspy is not installed; skipping Tier-2 aggregator discovery.")
            return []

        collected: List[ScrapedJob] = []
        for term in search_terms:
            jitter = random.uniform(1.5, 3.5)
            self.sleep_fn(jitter)

            for attempt in range(max_retries):
                try:
                    df = scrape_jobs(
                        site_name=["indeed"],
                        search_term=term,
                        location=location,
                        distance=distance,
                        country_indeed="USA",
                        results_wanted=results_wanted,
                        is_remote=is_remote,
                    )
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            title = str(row.get("title") or "").strip()
                            company = str(row.get("company") or "Unknown").strip()
                            if (
                                not company
                                or company.lower() == "nan"
                                or company.lower() in EXCLUDED_TIER2_COMPANIES
                            ):
                                continue
                            raw_desc = str(row.get("description") or "").strip()
                            url = str(row.get("job_url") or "").strip()
                            if not raw_desc or raw_desc.lower() == "nan":
                                raw_desc = f"{title} at {company}"
                            cleaned = clean_job_description(raw_desc)
                            if not title or not cleaned or not url:
                                continue
                            loc_str = str(row.get("location") or "").strip()
                            if not loc_str or loc_str.lower() == "nan":
                                loc_str = "Remote" if is_remote else location
                            row_remote = bool(
                                row.get("is_remote")
                                or is_remote
                                or "remote" in loc_str.lower()
                                or "remote" in title.lower()
                            )
                            content_hash = compute_content_hash(title, company, cleaned)
                            collected.append(
                                ScrapedJob(
                                    source=str(row.get("site") or "indeed"),
                                    source_id=str(row.get("id") or content_hash[:16]),
                                    title=title,
                                    company=company,
                                    location=loc_str,
                                    is_remote=row_remote,
                                    url=url,
                                    content_hash=content_hash,
                                    description_text=cleaned,
                                )
                            )
                    break
                except Exception as exc:
                    backoff = (2 ** attempt) + random.uniform(2.0, 4.0)
                    logger.warning(
                        "Tier-2 JobSpy attempt %d failed for '%s': %s (backoff=%.1fs)",
                        attempt + 1,
                        term,
                        exc,
                        backoff,
                    )
                    self.sleep_fn(backoff)

        return collected

    def fetch_remotive_remote_jobs(self, limit: int = 50) -> List[ScrapedJob]:
        """Fetches remote startup/mid-sized software roles from the Remotive public API."""
        url = f"https://remotive.com/api/remote-jobs?category=software-dev&limit={limit}"
        jobs: List[ScrapedJob] = []
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("jobs", []):
                title = str(item.get("title") or "").strip()
                company = str(item.get("company_name") or "Unknown").strip()
                if not title or company.lower() in EXCLUDED_TIER2_COMPANIES:
                    continue
                location = str(item.get("candidate_required_location") or "Remote").strip()
                raw_desc = str(item.get("description") or "")
                cleaned = clean_job_description(raw_desc)
                if not cleaned:
                    continue
                salary = str(item.get("salary") or "").strip() or None
                content_hash = compute_content_hash(title, company, cleaned)
                jobs.append(
                    ScrapedJob(
                        source="remotive",
                        source_id=str(item.get("id") or content_hash[:16]),
                        title=title,
                        company=company,
                        location=location,
                        is_remote=True,
                        url=str(item.get("url") or url),
                        content_hash=content_hash,
                        description_text=cleaned,
                        salary_range=salary,
                    )
                )
        except Exception as exc:
            logger.warning("Remotive remote jobs fetch failed: %s", exc)
        return jobs

    def fetch_single_url(self, target_url: str) -> Optional[ScrapedJob]:
        """Scrapes an arbitrary job posting URL submitted via the on-demand task queue."""
        try:
            resp = self.client.get(target_url)
            resp.raise_for_status()
            cleaned = clean_job_description(resp.text)
            if not cleaned:
                return None
            # Extract title and company from page <title> or ATS URL structure
            title = "Submitted Opportunity"
            if "<title>" in resp.text.lower():
                start = resp.text.lower().find("<title>") + 7
                end = resp.text.lower().find("</title>", start)
                if end > start:
                    title = resp.text[start:end].strip()[:120]

            url_parts = [p for p in target_url.split("/") if p]
            host = url_parts[1].replace("www.", "") if len(url_parts) > 1 else "Company"
            company = host

            if " @ " in title:
                role_part, comp_part = title.rsplit(" @ ", 1)
                title = role_part.strip()
                company = comp_part.split("|")[0].split("-")[0].strip()
            elif " at " in title:
                role_part, comp_part = title.rsplit(" at ", 1)
                title = role_part.strip()
                company = comp_part.split("|")[0].split("-")[0].strip()
            elif any(
                ats in host
                for ats in ("ashbyhq.com", "greenhouse.io", "lever.co")
            ) and len(url_parts) > 2:
                company = url_parts[2].replace("-", " ").title()
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
        enable_tier1: bool = False,
        enable_tier2: bool = True,
        preferred_locations: Optional[List[str]] = None,
        allow_remote: bool = True,
    ) -> List[ScrapedJob]:
        """Executes Tier-2 JobSpy discovery (and optional Tier-1 ATS scraping), returning deduplicated jobs."""
        raw_jobs: List[ScrapedJob] = []

        if enable_tier1:
            for board in ats_boards.get("greenhouse", []):
                raw_jobs.extend(self.fetch_greenhouse_board(board))
            for board in ats_boards.get("lever", []):
                raw_jobs.extend(self.fetch_lever_board(board))
            for board in ats_boards.get("ashby", []):
                raw_jobs.extend(self.fetch_ashby_board(board))

        if enable_tier2 and positive_titles:
            titles_to_query = positive_titles[:4]
            if allow_remote:
                logger.info(
                    "Running Tier-2 Indeed + Remotive remote discovery for titles=%s (location='United States', is_remote=True)...",
                    titles_to_query,
                )
                raw_jobs.extend(
                    self.fetch_tier2_jobspy(
                        titles_to_query,
                        location="United States",
                        is_remote=True,
                        results_wanted=25,
                    )
                )
                raw_jobs.extend(self.fetch_remotive_remote_jobs(limit=50))
            if preferred_locations:
                for local_area in preferred_locations[:2]:
                    logger.info(
                        "Running Tier-2 Indeed 50-mile metro discovery for titles=%s around '%s'...",
                        titles_to_query,
                        local_area,
                    )
                    raw_jobs.extend(
                        self.fetch_tier2_jobspy(
                            titles_to_query,
                            location=local_area,
                            is_remote=False,
                            results_wanted=20,
                            distance=50,
                        )
                    )

        return self.deduplicate_jobs(raw_jobs, existing_hashes)

