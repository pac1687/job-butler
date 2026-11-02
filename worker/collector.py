"""Multi-tier job ingestion: Tier-1 Direct ATS APIs, Tier-2 JobSpy fallback, and SHA-256 deduplication."""

from __future__ import annotations

from datetime import date, datetime, timezone
import logging
import random
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from bs4 import BeautifulSoup
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


def consolidate_search_queries(titles: List[str], max_queries: int = 8) -> List[str]:
    """
    Deduplicates overlapping search titles into distinct root search queries so HTTP scrapers
    (especially LinkedIn) don't fire redundant requests for substring variations
    (e.g. 'Solutions Engineer' already covers 'Product Solutions Engineer' and 'AI Solutions Engineer'),
    while the semantic ranker still scores against all full user titles.
    """
    cleaned = [re.sub(r"\s*\([^)]*\)", "", t).strip() for t in titles if t and t.strip()]
    if len(cleaned) <= max_queries:
        return cleaned

    # Sort shortest (broadest) first so broad root queries subsume narrower prefixes
    by_length = sorted(cleaned, key=len)
    roots: List[str] = []
    for candidate in by_length:
        cand_lower = candidate.lower()
        cand_tokens = set(re.findall(r"[a-z0-9]{3,}", cand_lower))
        if any(
            root.lower() in cand_lower
            or len(cand_tokens & set(re.findall(r"[a-z0-9]{3,}", root.lower()))) >= 2
            for root in roots
        ):
            continue
        roots.append(candidate)

    # Preserve original user ordering for the selected root queries, then top up to max_queries
    selected = [t for t in cleaned if t in roots]
    for t in cleaned:
        if len(selected) >= max_queries:
            break
        if t not in selected:
            selected.append(t)
    return selected[:max_queries]


def parse_and_check_recency(
    raw_date: Any,
    max_age_days: int = 7,
    reference_date: Optional[date] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Parses a posting date (`datetime`, `date`, or ISO string like '2026-10-29T14:20:00')
    and checks whether it was posted within `max_age_days` (default 7 days).
    Returns `(is_within_window, 'YYYY-MM-DD' or None)`.
    """
    if raw_date is None:
        return True, None

    today = reference_date or datetime.now(timezone.utc).date()
    parsed_date: Optional[date] = None

    if isinstance(raw_date, datetime):
        parsed_date = raw_date.date()
    elif isinstance(raw_date, date):
        parsed_date = raw_date
    else:
        raw_str = str(raw_date).strip()
        if not raw_str or raw_str.lower() in ("nan", "nat", "none", "null"):
            return True, None
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_str)
        if iso_match:
            try:
                parsed_date = date.fromisoformat(iso_match.group(1))
            except ValueError:
                parsed_date = None

    if parsed_date is None:
        return True, None

    age_days = (today - parsed_date).days
    return age_days <= max_age_days, parsed_date.isoformat()


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
        max_age_days: int = 7,
        max_retries: int = 2,
    ) -> List[ScrapedJob]:
        """
        Tier-2 Aggregator Discovery using JobSpy (Indeed batch GraphQL with 50-mile metro radius
        and `hours_old` recency filter) with exponential backoff and jittered delays.
        """
        try:
            from jobspy import scrape_jobs  # type: ignore
        except ImportError:
            logger.warning("python-jobspy is not installed; skipping Tier-2 aggregator discovery.")
            return []

        hours_old = max(24, int(max_age_days) * 24)
        collected: List[ScrapedJob] = []
        for term in search_terms:
            jitter = random.uniform(0.8, 1.8)
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
                        hours_old=hours_old,
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
                            is_recent, posted_iso = parse_and_check_recency(
                                row.get("date_posted"),
                                max_age_days=max_age_days,
                            )
                            if not is_recent:
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
                            if posted_iso:
                                loc_str = f"{loc_str} • Posted {posted_iso}"
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

    def fetch_remotive_remote_jobs(
        self,
        limit: int = 50,
        max_age_days: int = 7,
    ) -> List[ScrapedJob]:
        """Fetches remote startup/mid-sized software roles posted within `max_age_days` from Remotive API."""
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
                is_recent, posted_iso = parse_and_check_recency(
                    item.get("publication_date"),
                    max_age_days=max_age_days,
                )
                if not is_recent:
                    continue
                location = str(item.get("candidate_required_location") or "Remote").strip()
                if posted_iso:
                    location = f"{location} • Posted {posted_iso}"
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

    def fetch_linkedin_guest_jobs(
        self,
        search_terms: List[str],
        location: str = "United States",
        is_remote: bool = True,
        distance: int = 50,
        max_age_days: int = 7,
        max_retries: int = 2,
    ) -> List[ScrapedJob]:
        """
        Two-stage rate-limit-safe LinkedIn Guest Search scraper (Stage 1: Search Cards).
        Makes 1 lightweight search request per title using LinkedIn's native `f_WT=2` (Remote)
        and `f_TPR=r{seconds}` (default past 7 days) filters, plus verifies card `<time datetime>`.
        Full descriptions are lazily hydrated via `hydrate_linkedin_description` only for top matches.
        """
        search_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        browser_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        tpr_seconds = max(86400, int(max_age_days) * 86400)
        collected: List[ScrapedJob] = []

        for term in search_terms:
            self.sleep_fn(random.uniform(2.5, 4.2))
            params: Dict[str, str] = {
                "keywords": term,
                "location": location,
                "f_TPR": f"r{tpr_seconds}",
                "start": "0",
            }
            if is_remote:
                params["f_WT"] = "2"  # LinkedIn native Remote workplace filter
            else:
                params["distance"] = str(distance)

            for attempt in range(max_retries):
                try:
                    resp = self.client.get(search_url, params=params, headers=browser_headers)
                    if resp.status_code == 429:
                        cooldown = (3 ** attempt) + random.uniform(4.0, 7.0)
                        logger.warning(
                            "LinkedIn search rate-limited (429) for '%s'; cooling down %.1fs...",
                            term,
                            cooldown,
                        )
                        self.sleep_fn(cooldown)
                        continue
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.find_all("div", class_=re.compile(r"base-search-card|base-card"))
                    for card in cards:
                        title_el = card.find("h3", class_=re.compile(r"base-search-card__title"))
                        comp_el = card.find("h4", class_=re.compile(r"base-search-card__subtitle"))
                        loc_el = card.find("span", class_=re.compile(r"job-search-card__location"))
                        time_el = card.find("time", class_=re.compile(r"job-search-card__listdate"))
                        link_el = card.find("a", class_=re.compile(r"base-card__full-link"))

                        title = title_el.get_text(strip=True) if title_el else ""
                        company = comp_el.get_text(strip=True) if comp_el else ""
                        if (
                            not title
                            or not company
                            or company.lower() in EXCLUDED_TIER2_COMPANIES
                        ):
                            continue

                        raw_datetime = time_el.get("datetime") if time_el else None
                        is_recent, posted_iso = parse_and_check_recency(
                            raw_datetime,
                            max_age_days=max_age_days,
                        )
                        if not is_recent:
                            continue

                        loc_str = (
                            loc_el.get_text(strip=True)
                            if loc_el
                            else ("Remote" if is_remote else location)
                        )
                        if is_remote and "remote" not in loc_str.lower():
                            loc_str = f"{loc_str} (Remote)"
                        if posted_iso:
                            loc_str = f"{loc_str} • Posted {posted_iso}"
                        raw_href = str(link_el.get("href") or "").split("?")[0].strip() if link_el else ""
                        urn = str(card.get("data-entity-urn") or "")
                        job_id_match = re.search(r"(\d{7,12})", urn or raw_href)
                        job_id = job_id_match.group(1) if job_id_match else ""
                        if not raw_href and job_id:
                            raw_href = f"https://www.linkedin.com/jobs/view/{job_id}"
                        if not raw_href:
                            continue

                        placeholder_desc = (
                            f"{title} at {company} ({loc_str}). "
                            f"Matched search query: {term}."
                        )
                        # Stable content_hash keyed on LinkedIn job ID + title + company
                        content_hash = compute_content_hash(
                            title, company, job_id or raw_href
                        )
                        collected.append(
                            ScrapedJob(
                                source="linkedin",
                                source_id=job_id or content_hash[:16],
                                title=title,
                                company=company,
                                location=loc_str,
                                is_remote=bool(
                                    is_remote
                                    or "remote" in loc_str.lower()
                                    or "remote" in title.lower()
                                ),
                                url=raw_href,
                                content_hash=content_hash,
                                description_text=placeholder_desc,
                            )
                        )
                    break
                except Exception as exc:
                    backoff = (2 ** attempt) + random.uniform(2.0, 4.0)
                    logger.warning(
                        "LinkedIn guest search attempt %d failed for '%s': %s",
                        attempt + 1,
                        term,
                        exc,
                    )
                    self.sleep_fn(backoff)

        return collected

    def hydrate_linkedin_description(self, job: ScrapedJob) -> ScrapedJob:
        """
        Stage 2 of LinkedIn scraping: Fetches the full job posting description from LinkedIn's
        guest detail endpoint (`https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}`)
        only for candidate jobs that passed filtering and are about to be evaluated.
        """
        if job.source != "linkedin" or len(job.description_text) > 350:
            return job

        job_id_match = re.search(r"(\d{7,12})", f"{job.source_id} {job.url}")
        if not job_id_match:
            return job

        job_id = job_id_match.group(1)
        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        browser_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        for attempt in range(2):
            try:
                self.sleep_fn(random.uniform(1.2, 2.2))
                resp = self.client.get(detail_url, headers=browser_headers)
                if resp.status_code == 429:
                    self.sleep_fn(4.0 + attempt * 3.0)
                    continue
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                desc_div = soup.find(
                    "div",
                    class_=re.compile(r"show-more-less-html__markup|description__text"),
                )
                raw_html = str(desc_div) if desc_div else resp.text
                cleaned = clean_job_description(raw_html)
                if cleaned and len(cleaned) > 100:
                    return job.model_copy(update={"description_text": cleaned})
                break
            except Exception as exc:
                logger.warning(
                    "Could not hydrate full LinkedIn description for job %s (%s): %s",
                    job_id,
                    job.company,
                    exc,
                )
        return job

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
            all_titles = [t.strip() for t in positive_titles if t and t.strip()]
            linkedin_queries = consolidate_search_queries(all_titles, max_queries=7)
            indeed_queries = consolidate_search_queries(all_titles, max_queries=10)
            per_title_limit = 15 if len(indeed_queries) > 6 else 25
            if allow_remote:
                logger.info(
                    "Running Tier-2 Indeed (%d queries) + LinkedIn (%d root queries, f_WT=2 Remote) + Remotive discovery (covering all %d target titles)...",
                    len(indeed_queries),
                    len(linkedin_queries),
                    len(all_titles),
                )
                raw_jobs.extend(
                    self.fetch_tier2_jobspy(
                        indeed_queries,
                        location="United States",
                        is_remote=True,
                        results_wanted=per_title_limit,
                    )
                )
                raw_jobs.extend(
                    self.fetch_linkedin_guest_jobs(
                        linkedin_queries,
                        location="United States",
                        is_remote=True,
                    )
                )
                raw_jobs.extend(self.fetch_remotive_remote_jobs(limit=50))
            if preferred_locations:
                for local_area in preferred_locations[:3]:
                    logger.info(
                        "Running Tier-2 Indeed + LinkedIn 50-mile metro discovery around '%s' (%d root queries)...",
                        local_area,
                        len(linkedin_queries),
                    )
                    raw_jobs.extend(
                        self.fetch_tier2_jobspy(
                            indeed_queries,
                            location=local_area,
                            is_remote=False,
                            results_wanted=per_title_limit,
                            distance=50,
                        )
                    )
                    raw_jobs.extend(
                        self.fetch_linkedin_guest_jobs(
                            linkedin_queries,
                            location=local_area,
                            is_remote=False,
                            distance=50,
                        )
                    )

        return self.deduplicate_jobs(raw_jobs, existing_hashes)

