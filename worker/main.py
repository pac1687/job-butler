"""Main worker entrypoint supporting --nightly batch execution and --listen-queue daemon (Task 3.10)."""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import psycopg
from pypdf import PdfReader

from worker.collector import JobCollector
from worker.config import WorkerConfig
from worker.lease import LeaseCoordinator
from worker.preflight import check_lm_studio_health, enforce_preflight_or_exit
from worker.publisher import ArtifactPublisher
from worker.ranker import SemanticRanker, is_eligible_remote_or_local
from worker.schemas import JobEvaluationResult, ScrapedJob
from worker.synthesizer import JobSynthesizer
from worker.typesetter import TypstTypesetter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker.main")

DEFAULT_ATS_BOARDS: Dict[str, List[str]] = {
    "greenhouse": [
        "vercel",
        "cloudflare",
        "stripe",
        "datadog",
        "discord",
        "figma",
        "coinbase",
        "airbnb",
        "brex",
        "gusto",
        "retool",
        "cockroachlabs",
        "temporal",
        "planetscale",
        "netlify",
        "gitlab",
        "twilio",
    ],
    "lever": [
        "palantir",
        "spotify",
        "zoox",
        "plaid",
    ],
    "ashby": [
        "ramp",
        "linear",
        "supabase",
        "openai",
        "anthropic",
        "notion",
        "perplexity",
        "posthog",
        "resend",
        "cal",
        "railway",
        "clerk",
        "langfuse",
    ],
}

CLAIM_NEXT_TASK_SQL = """
SELECT id, job_id, task_type, payload
FROM job_task_queue
WHERE status = 'PENDING'
ORDER BY created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
"""


def _load_pipeline_state(conn: Any) -> Dict[str, Any]:
    """Loads active master profile, tailoring rules, job preferences, and existing job hashes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT basics, skills, experience, education FROM master_profiles WHERE is_active = TRUE ORDER BY uploaded_at DESC LIMIT 1;"
        )
        prof_row = cur.fetchone()
        master_profile = (
            {
                "basics": prof_row[0],
                "skills": prof_row[1],
                "experience": prof_row[2],
                "education": prof_row[3],
            }
            if prof_row
            else {"basics": {}, "skills": {}, "experience": [], "education": []}
        )

        cur.execute(
            "SELECT forbidden_terms, protected_metrics, max_bullets_per_role, allow_rephrasing FROM tailoring_rules ORDER BY id DESC LIMIT 1;"
        )
        rule_row = cur.fetchone()
        tailoring_rules = (
            {
                "forbidden_terms": rule_row[0],
                "protected_metrics": rule_row[1],
                "max_bullets_per_role": rule_row[2],
                "allow_rephrasing": rule_row[3],
            }
            if rule_row
            else {
                "forbidden_terms": [],
                "protected_metrics": [],
                "max_bullets_per_role": 4,
                "allow_rephrasing": True,
            }
        )

        cur.execute(
            "SELECT positive_titles, negative_title_keywords, natural_language_notes, min_semantic_score, ats_boards FROM job_preferences ORDER BY id DESC LIMIT 1;"
        )
        pref_row = cur.fetchone()
        raw_boards = (pref_row[4] if pref_row and len(pref_row) > 4 else None) or {}
        if not isinstance(raw_boards, dict):
            raw_boards = {}

        # Upgrade legacy 5-board seed to the expanded 34-company default board set unless customized
        is_legacy_seed = (
            raw_boards.get("greenhouse") == ["vercel", "supabase", "cloudflare"]
            and raw_boards.get("lever") == ["linear"]
        )
        ats_boards: Dict[str, List[str]] = {
            "greenhouse": (
                DEFAULT_ATS_BOARDS["greenhouse"]
                if is_legacy_seed or not raw_boards.get("greenhouse")
                else list(raw_boards.get("greenhouse", []))
            ),
            "lever": (
                DEFAULT_ATS_BOARDS["lever"]
                if is_legacy_seed or "lever" not in raw_boards
                else list(raw_boards.get("lever", []))
            ),
            "ashby": (
                DEFAULT_ATS_BOARDS["ashby"]
                if is_legacy_seed or not raw_boards.get("ashby")
                else list(raw_boards.get("ashby", []))
            ),
        }

        profile_location = str((master_profile.get("basics") or {}).get("location") or "").strip()
        configured_locs = raw_boards.get("preferred_locations")
        if isinstance(configured_locs, list):
            preferred_locations = [str(x).strip() for x in configured_locs if str(x).strip()]
        elif profile_location:
            preferred_locations = [profile_location]
        else:
            preferred_locations = []

        allow_remote = bool(raw_boards.get("allow_remote", True))
        max_per_company = int(raw_boards.get("max_per_company", 2))
        enable_tier1 = bool(raw_boards.get("enable_tier1", False))
        enable_tier2 = bool(raw_boards.get("enable_tier2", True))

        preferences = (
            {
                "positive_titles": pref_row[0],
                "negative_title_keywords": pref_row[1],
                "natural_language_notes": pref_row[2] or "",
                "min_semantic_score": float(pref_row[3] or 0.70),
                "ats_boards": ats_boards,
                "preferred_locations": preferred_locations,
                "allow_remote": allow_remote,
                "max_per_company": max_per_company,
                "enable_tier1": enable_tier1,
                "enable_tier2": enable_tier2,
            }
            if pref_row
            else {
                "positive_titles": ["Full Stack Engineer", "Senior Software Engineer"],
                "negative_title_keywords": ["Manager", "Staff", "Director"],
                "natural_language_notes": "",
                "min_semantic_score": 0.70,
                "ats_boards": DEFAULT_ATS_BOARDS,
                "preferred_locations": [profile_location] if profile_location else [],
                "allow_remote": True,
                "max_per_company": 2,
                "enable_tier1": False,
                "enable_tier2": True,
            }
        )

        cur.execute("SELECT content_hash FROM jobs;")
        existing_hashes: Set[str] = {str(r[0]).strip() for r in cur.fetchall()}

    return {
        "master_profile": master_profile,
        "tailoring_rules": tailoring_rules,
        "preferences": preferences,
        "existing_hashes": existing_hashes,
    }


def process_single_job(
    conn: Any,
    job: ScrapedJob,
    semantic_score: float,
    state: Dict[str, Any],
    synthesizer: JobSynthesizer,
    typesetter: TypstTypesetter,
    publisher: ArtifactPublisher,
) -> str:
    """Evaluates, tailors, compiles single-page PDFs, uploads to R2, and persists a single job."""
    logger.info("1/4 Evaluating job fit via LM Studio for '%s' at '%s'...", job.title, job.company)
    evaluation = synthesizer.evaluate_job_fit(
        job=job,
        master_profile=state["master_profile"],
        natural_language_notes=state["preferences"].get("natural_language_notes", ""),
    )
    if not job.salary_range and evaluation.extracted_salary:
        candidate_sal = evaluation.extracted_salary.strip()
        if candidate_sal and candidate_sal.lower() not in {"null", "none", "n/a", "unknown", "not specified", "not stated"}:
            job = job.model_copy(update={"salary_range": candidate_sal})
    logger.info("2/4 Tailoring resume bullets and cover letter (fit_score=%.1f)...", evaluation.fit_score)
    payload_snapshot = synthesizer.build_tailored_payload(
        job=job,
        master_profile=state["master_profile"],
        tailoring_rules=state["tailoring_rules"],
        evaluation=evaluation,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        logger.info("3/4 Compiling single-page Typst PDFs...")
        resume_pdf = typesetter.compile_resume_with_auto_trim(
            payload_snapshot, tmp_path / "resume.pdf"
        )
        cover_pdf = typesetter.compile_cover_letter_with_auto_trim(
            payload_snapshot, tmp_path / "cover_letter.pdf"
        )
        logger.info("4/4 Uploading artifacts to S3 and persisting match to Neon...")
        storage_keys = publisher.upload_artifacts_to_r2(
            job_content_hash=job.content_hash,
            resume_pdf_path=resume_pdf,
            cover_letter_pdf_path=cover_pdf,
            payload_snapshot=payload_snapshot,
        )

    return publisher.persist_evaluated_match(
        conn=conn,
        job=job,
        semantic_score=semantic_score,
        evaluation=evaluation,
        resume_storage_key=storage_keys.get("resume_storage_key"),
        cover_letter_storage_key=storage_keys.get("cover_letter_storage_key"),
        payload_snapshot=payload_snapshot,
    )


def discover_and_score_single_job(
    database_url: str,
    job: ScrapedJob,
    semantic_score: float,
    state: Dict[str, Any],
    synthesizer: JobSynthesizer,
    publisher: ArtifactPublisher,
) -> str:
    """
    Stage 1 (Fast Discovery): Evaluates job fit via LM Studio (with NO database connection held open)
    and then opens a short-lived connection to persist the match to Neon.
    """
    logger.info(
        "Evaluating job fit via LM Studio for '%s' at '%s' (%s)...",
        job.title,
        job.company,
        job.location,
    )
    evaluation = synthesizer.evaluate_job_fit(
        job=job,
        master_profile=state["master_profile"],
        natural_language_notes=state["preferences"].get("natural_language_notes", ""),
    )
    if not job.salary_range and evaluation.extracted_salary:
        candidate_sal = evaluation.extracted_salary.strip()
        if candidate_sal and candidate_sal.lower() not in {"null", "none", "n/a", "unknown", "not specified", "not stated"}:
            job = job.model_copy(update={"salary_range": candidate_sal})
    with psycopg.connect(database_url) as job_conn:
        match_id = publisher.persist_evaluated_match(
            conn=job_conn,
            job=job,
            semantic_score=semantic_score,
            evaluation=evaluation,
            resume_storage_key=None,
            cover_letter_storage_key=None,
            payload_snapshot={"status": "PENDING_TAILORING"},
        )
    logger.info(
        "Saved match '%s' at '%s' (fit_score=%.1f, semantic_score=%.2f) — ready for on-demand PDF tailoring.",
        job.title,
        job.company,
        evaluation.fit_score,
        semantic_score,
    )
    return match_id


def run_nightly_batch(config: WorkerConfig, max_jobs: Optional[int] = None) -> None:
    """
    Executes the batch job discovery & fit scoring pipeline with pre-flight check,
    distributed lease, retention purge, location/remote filtering, and company diversity cap.
    """
    effective_max_jobs = max(1, int(max_jobs if max_jobs is not None else config.max_jobs_per_batch))
    if not check_lm_studio_health(config.lm_studio_base_url):
        logger.warning("LM Studio is offline; skipping discovery batch.")
        return

    with psycopg.connect(config.database_url) as conn:
        lease = LeaseCoordinator(conn, worker_id=config.worker_node_id)
        if not lease.acquire_lease("nightly_batch", ttl_minutes=120):
            return
        lease.run_retention_purge()
        state = _load_pipeline_state(conn)

    try:
        collector = JobCollector()
        ranker = SemanticRanker(config.embedding_model_name)
        synthesizer = JobSynthesizer(config=config, ranker=ranker)
        publisher = ArtifactPublisher(config=config)

        ats_boards = state["preferences"].get("ats_boards") or DEFAULT_ATS_BOARDS
        preferred_locations = state["preferences"].get("preferred_locations") or []
        allow_remote = bool(state["preferences"].get("allow_remote", True))
        max_per_company = int(state["preferences"].get("max_per_company", 2))
        enable_tier1 = bool(state["preferences"].get("enable_tier1", False))
        enable_tier2 = bool(state["preferences"].get("enable_tier2", True))

        logger.info(
            "Starting discovery scrape (Tier-2 JobSpy=%s, Tier-1 Big-Tech ATS=%s)...",
            enable_tier2,
            enable_tier1,
        )
        scraped = collector.collect_all(
            ats_boards=ats_boards,
            positive_titles=state["preferences"]["positive_titles"],
            existing_hashes=state["existing_hashes"],
            enable_tier1=enable_tier1,
            enable_tier2=enable_tier2,
            preferred_locations=preferred_locations,
            allow_remote=allow_remote,
        )
        basics = state["master_profile"].get("basics") or {}
        skills_map = state["master_profile"].get("skills") or {}
        flat_skills: List[str] = []
        if isinstance(skills_map, dict):
            for vals in skills_map.values():
                if isinstance(vals, list):
                    flat_skills.extend(str(v) for v in vals if v)
        profile_summary_parts = [
            str(basics.get("title") or ""),
            str(basics.get("summary") or ""),
            ", ".join(flat_skills),
        ]
        profile_summary = "\n".join(p for p in profile_summary_parts if p.strip()) or json.dumps(basics)

        ranked = ranker.filter_and_rank(
            jobs=scraped,
            positive_titles=state["preferences"]["positive_titles"],
            negative_keywords=state["preferences"]["negative_title_keywords"],
            profile_summary_text=profile_summary,
            min_semantic_score=state["preferences"]["min_semantic_score"],
            preferred_locations=preferred_locations,
            allow_remote=allow_remote,
            max_per_company=max_per_company,
        )

        top_candidates = ranked[:effective_max_jobs]
        scraped_by_src: Dict[str, int] = {}
        for j in scraped:
            scraped_by_src[j.source] = scraped_by_src.get(j.source, 0) + 1
        top_by_src: Dict[str, int] = {}
        for j, _ in top_candidates:
            top_by_src[j.source] = top_by_src.get(j.source, 0) + 1

        logger.info(
            "Discovery batch scraped %d new jobs %s; %d passed location + semantic + diversity filter (>= %.2f, max %d/company). Scoring up to %d matches %s (max_jobs=%d)...",
            len(scraped),
            scraped_by_src,
            len(ranked),
            state["preferences"]["min_semantic_score"],
            max_per_company,
            len(top_candidates),
            top_by_src,
            effective_max_jobs,
        )
        scored_count = 0
        target_total = min(effective_max_jobs, len(ranked))
        for job, sem_score in ranked:
            if scored_count >= effective_max_jobs:
                break
            try:
                if job.source == "linkedin":
                    job = collector.hydrate_linkedin_description(job)
                    if not is_eligible_remote_or_local(
                        job,
                        preferred_locations=preferred_locations,
                        allow_remote=allow_remote,
                    ):
                        logger.info(
                            "Skipping LinkedIn job '%s' at '%s' (%s) after detail inspection: detected Hybrid/On-site outside local market.",
                            job.title,
                            job.company,
                            job.location,
                        )
                        continue
                scored_count += 1
                logger.info(
                    "[Discovery %d/%d] Scoring '%s' at '%s' (%s, source=%s, semantic_score=%.2f)...",
                    scored_count,
                    target_total,
                    job.title,
                    job.company,
                    job.location,
                    job.source,
                    sem_score,
                )
                discover_and_score_single_job(
                    database_url=config.database_url,
                    job=job,
                    semantic_score=sem_score,
                    state=state,
                    synthesizer=synthesizer,
                    publisher=publisher,
                )
            except Exception as job_exc:
                logger.error(
                    "[Discovery %d/%d] Failed scoring/saving '%s' at '%s': %s",
                    scored_count,
                    target_total,
                    job.title,
                    job.company,
                    job_exc,
                )
    finally:
        with psycopg.connect(config.database_url) as conn:
            LeaseCoordinator(conn, worker_id=config.worker_node_id).release_lease(
                "nightly_batch"
            )


def poll_task_queue_once(config: WorkerConfig) -> bool:
    """
    Claims and processes at most one pending task from `job_task_queue` using
    `SELECT ... FOR UPDATE SKIP LOCKED` for multi-node concurrency safety.
    Uses short-lived DB connections so Neon's pooler never drops an idle SSL connection
    during local LLM inference.
    """
    with psycopg.connect(config.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(CLAIM_NEXT_TASK_SQL)
            row = cur.fetchone()
            if not row:
                conn.commit()
                return False

            task_id, job_id, task_type, payload = row[0], row[1], row[2], row[3] or {}
            cur.execute(
                "UPDATE job_task_queue SET status = 'PROCESSING', updated_at = NOW() WHERE id = %s;",
                (task_id,),
            )
        conn.commit()

    logger.info("Processing task %s (type=%s)", task_id, task_type)
    try:
        if not check_lm_studio_health(config.lm_studio_base_url):
            raise RuntimeError("Host LM Studio server is offline.")

        synthesizer = JobSynthesizer(config=config)
        typesetter = TypstTypesetter()
        publisher = ArtifactPublisher(config=config)
        collector = JobCollector()

        if task_type == "PARSE_MASTER_RESUME":
            raw_text = str(payload.get("raw_text") or "").strip()
            file_b64 = payload.get("file_base64")
            if not raw_text and file_b64:
                pdf_bytes = base64.b64decode(file_b64)
                reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
                raw_text = "\n".join(
                    (page.extract_text() or "") for page in reader.pages
                ).strip()
            if not raw_text:
                raise ValueError("Uploaded resume contained no extractable text.")

            logger.info("Sending resume text (%d chars) to LM Studio (%s)...", len(raw_text), config.lm_studio_model)
            parsed = synthesizer.parse_master_resume_text(raw_text)

            with psycopg.connect(config.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE master_profiles SET is_active = FALSE WHERE is_active = TRUE;")
                    cur.execute(
                        """
                        INSERT INTO master_profiles (is_active, basics, skills, experience, education)
                        VALUES (TRUE, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb);
                        """,
                        (
                            json.dumps(parsed.basics.model_dump()),
                            json.dumps(parsed.skills.model_dump()),
                            json.dumps([r.model_dump() for r in parsed.experience]),
                            json.dumps([e.model_dump() for e in parsed.education]),
                        ),
                    )
                    cur.execute(
                        "UPDATE job_task_queue SET status = 'COMPLETED', error_message = NULL, updated_at = NOW() WHERE id = %s;",
                        (task_id,),
                    )
                conn.commit()

        elif task_type in ("EVALUATE_URL", "REGENERATE_RESUME", "REWRITE_COVER_LETTER"):
            if payload.get("mode") == "BATCH_DISCOVERY":
                max_jobs = int(payload.get("max_jobs") or config.max_jobs_per_batch)
                run_nightly_batch(config, max_jobs=max_jobs)
                with psycopg.connect(config.database_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE job_task_queue SET status = 'COMPLETED', error_message = NULL, updated_at = NOW() WHERE id = %s;",
                            (task_id,),
                        )
                    conn.commit()
            else:
                existing_eval: Optional[JobEvaluationResult] = None
                with psycopg.connect(config.database_url) as conn:
                    state = _load_pipeline_state(conn)
                    target_url = str(payload.get("url") or "")
                    job = collector.fetch_single_url(target_url) if target_url else None
                    if job is None and job_id:
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT source, source_id, title, company, location, is_remote, url, content_hash, description_text, salary_range FROM jobs WHERE id = %s;",
                                (job_id,),
                            )
                            jrow = cur.fetchone()
                            if jrow:
                                job = ScrapedJob(
                                    source=jrow[0],
                                    source_id=jrow[1],
                                    title=jrow[2],
                                    company=jrow[3],
                                    location=jrow[4],
                                    is_remote=jrow[5],
                                    url=jrow[6],
                                    content_hash=jrow[7].strip(),
                                    description_text=jrow[8],
                                    salary_range=jrow[9],
                                )
                            cur.execute(
                                "SELECT fit_score, fit_rationale, matched_skills, missing_skills FROM evaluated_matches WHERE job_id = %s ORDER BY created_at DESC LIMIT 1;",
                                (job_id,),
                            )
                            mrow = cur.fetchone()
                            if mrow:
                                existing_eval = JobEvaluationResult(
                                    fit_score=float(mrow[0]),
                                    fit_rationale=str(mrow[1]),
                                    matched_skills=list(mrow[2] or []),
                                    missing_skills=list(mrow[3] or []),
                                )
                    if job is None:
                        raise ValueError("Unable to resolve job record or scrape URL for task.")

                # Reuse existing fit evaluation when tailoring an already-scored match; otherwise evaluate now
                evaluation = existing_eval or synthesizer.evaluate_job_fit(
                    job=job,
                    master_profile=state["master_profile"],
                    natural_language_notes=state["preferences"].get("natural_language_notes", ""),
                )
                logger.info(
                    "Tailoring resume bullets and cover letter for '%s' at '%s' (fit_score=%.1f)...",
                    job.title,
                    job.company,
                    evaluation.fit_score,
                )
                payload_snapshot = synthesizer.build_tailored_payload(
                    job=job,
                    master_profile=state["master_profile"],
                    tailoring_rules=state["tailoring_rules"],
                    evaluation=evaluation,
                )
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    logger.info("Compiling single-page Typst PDFs for '%s' at '%s'...", job.title, job.company)
                    resume_pdf = typesetter.compile_resume_with_auto_trim(
                        payload_snapshot, tmp_path / "resume.pdf"
                    )
                    cover_pdf = typesetter.compile_cover_letter_with_auto_trim(
                        payload_snapshot, tmp_path / "cover_letter.pdf"
                    )
                    storage_keys = publisher.upload_artifacts_to_r2(
                        job_content_hash=job.content_hash,
                        resume_pdf_path=resume_pdf,
                        cover_letter_pdf_path=cover_pdf,
                        payload_snapshot=payload_snapshot,
                    )

                with psycopg.connect(config.database_url) as conn:
                    updated_match_id = (
                        publisher.update_match_artifacts(
                            conn=conn,
                            job_id=str(job_id),
                            resume_storage_key=storage_keys.get("resume_storage_key"),
                            cover_letter_storage_key=storage_keys.get("cover_letter_storage_key"),
                            payload_snapshot=payload_snapshot,
                        )
                        if job_id and existing_eval is not None
                        else None
                    )
                    if not updated_match_id:
                        publisher.persist_evaluated_match(
                            conn=conn,
                            job=job,
                            semantic_score=0.85,
                            evaluation=evaluation,
                            resume_storage_key=storage_keys.get("resume_storage_key"),
                            cover_letter_storage_key=storage_keys.get("cover_letter_storage_key"),
                            payload_snapshot=payload_snapshot,
                        )
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE job_task_queue SET status = 'COMPLETED', error_message = NULL, updated_at = NOW() WHERE id = %s;",
                            (task_id,),
                        )
                    conn.commit()

        logger.info("Task %s completed successfully.", task_id)

    except Exception as exc:
        logger.error("Task %s failed: %s", task_id, exc)
        with psycopg.connect(config.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_task_queue SET status = 'FAILED', error_message = %s, updated_at = NOW() WHERE id = %s;",
                    (str(exc)[:500], task_id),
                )
            conn.commit()

    return True


def run_queue_listener(config: WorkerConfig) -> None:
    """Persistent daemon loop polling `job_task_queue` with `FOR UPDATE SKIP LOCKED`."""
    logger.info(
        "Starting queue listener on node '%s' (model='%s', poll interval=%ds)...",
        config.worker_node_id,
        config.lm_studio_model,
        config.queue_poll_interval_seconds,
    )
    while True:
        try:
            while poll_task_queue_once(config):
                pass
        except Exception as exc:
            logger.warning("Queue poll cycle encountered an error: %s", exc)
        time.sleep(config.queue_poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Butler Pipeline Worker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--nightly",
        action="store_true",
        help="Execute the scheduled batch job discovery & tailoring pipeline.",
    )
    group.add_argument(
        "--listen-queue",
        action="store_true",
        help="Run persistent daemon polling job_task_queue.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Maximum number of matched jobs to evaluate and tailor per batch run (overrides MAX_JOBS_PER_BATCH).",
    )
    args = parser.parse_args()
    config = WorkerConfig()

    if args.nightly:
        run_nightly_batch(config, max_jobs=args.max_jobs)
    elif args.listen_queue:
        run_queue_listener(config)


if __name__ == "__main__":
    main()

