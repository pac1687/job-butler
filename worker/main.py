"""Main worker entrypoint supporting --nightly batch execution and --listen-queue daemon (Task 3.10)."""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Set
import psycopg

from worker.collector import JobCollector
from worker.config import WorkerConfig
from worker.lease import LeaseCoordinator
from worker.preflight import check_lm_studio_health, enforce_preflight_or_exit
from worker.publisher import ArtifactPublisher
from worker.ranker import SemanticRanker
from worker.schemas import ScrapedJob
from worker.synthesizer import JobSynthesizer
from worker.typesetter import TypstTypesetter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker.main")

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
            "SELECT positive_titles, negative_title_keywords, natural_language_notes, min_semantic_score FROM job_preferences ORDER BY id DESC LIMIT 1;"
        )
        pref_row = cur.fetchone()
        preferences = (
            {
                "positive_titles": pref_row[0],
                "negative_title_keywords": pref_row[1],
                "natural_language_notes": pref_row[2] or "",
                "min_semantic_score": float(pref_row[3] or 0.70),
            }
            if pref_row
            else {
                "positive_titles": ["Full Stack Engineer", "Senior Software Engineer"],
                "negative_title_keywords": ["Manager", "Staff", "Director"],
                "natural_language_notes": "",
                "min_semantic_score": 0.70,
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
    evaluation = synthesizer.evaluate_job_fit(
        job=job,
        master_profile=state["master_profile"],
        natural_language_notes=state["preferences"].get("natural_language_notes", ""),
    )
    payload_snapshot = synthesizer.build_tailored_payload(
        job=job,
        master_profile=state["master_profile"],
        tailoring_rules=state["tailoring_rules"],
        evaluation=evaluation,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        resume_pdf = typesetter.compile_resume_with_auto_trim(
            payload_snapshot, tmp_path / "resume.pdf"
        )
        cover_pdf = typesetter.compile_template(
            "cover_letter.typ",
            payload_snapshot,
            tmp_path / "cover_letter.pdf",
            enforce_single_page=True,
        )
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


def run_nightly_batch(config: WorkerConfig) -> None:
    """Executes the scheduled nightly batch with pre-flight check, distributed lease, and retention purge."""
    enforce_preflight_or_exit(config.lm_studio_base_url)

    with psycopg.connect(config.database_url) as conn:
        lease = LeaseCoordinator(conn, worker_id=config.worker_node_id)
        if not lease.acquire_lease("nightly_batch", ttl_minutes=120):
            return

        try:
            lease.run_retention_purge()
            state = _load_pipeline_state(conn)

            collector = JobCollector()
            ranker = SemanticRanker(config.embedding_model_name)
            synthesizer = JobSynthesizer(config=config, ranker=ranker)
            typesetter = TypstTypesetter()
            publisher = ArtifactPublisher(config=config)

            ats_boards = {
                "greenhouse": ["vercel", "supabase", "cloudflare"],
                "lever": ["linear"],
                "ashby": ["ramp"],
            }
            scraped = collector.collect_all(
                ats_boards=ats_boards,
                positive_titles=state["preferences"]["positive_titles"],
                existing_hashes=state["existing_hashes"],
            )
            profile_summary = json.dumps(state["master_profile"].get("basics", {}))
            ranked = ranker.filter_and_rank(
                jobs=scraped,
                positive_titles=state["preferences"]["positive_titles"],
                negative_keywords=state["preferences"]["negative_title_keywords"],
                profile_summary_text=profile_summary,
                min_semantic_score=state["preferences"]["min_semantic_score"],
            )

            logger.info(
                "Nightly batch scraped %d unique jobs; %d passed semantic filter.",
                len(scraped),
                len(ranked),
            )
            for job, sem_score in ranked:
                process_single_job(
                    conn=conn,
                    job=job,
                    semantic_score=sem_score,
                    state=state,
                    synthesizer=synthesizer,
                    typesetter=typesetter,
                    publisher=publisher,
                )
        finally:
            lease.release_lease("nightly_batch")


def poll_task_queue_once(conn: Any, config: WorkerConfig) -> bool:
    """
    Claims and processes at most one pending task from `job_task_queue` using
    `SELECT ... FOR UPDATE SKIP LOCKED` for multi-node concurrency safety.
    Returns True if a task was processed, False if queue was empty.
    """
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
            raw_text = str(payload.get("raw_text") or "")
            parsed = synthesizer.parse_master_resume_text(raw_text)
            with conn.cursor() as cur:
                cur.execute("UPDATE master_profiles SET is_active = FALSE WHERE is_active = TRUE;")
                cur.execute(
                    """
                    INSERT INTO master_profiles (is_active, basics, skills, experience, education)
                    VALUES (TRUE, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb);
                    """,
                    (
                        json.dumps(parsed.basics),
                        json.dumps(parsed.skills),
                        json.dumps([r.model_dump() for r in parsed.experience]),
                        json.dumps([e.model_dump() for e in parsed.education]),
                    ),
                )

        elif task_type in ("EVALUATE_URL", "REGENERATE_RESUME", "REWRITE_COVER_LETTER"):
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
            if job is None:
                raise ValueError("Unable to resolve job record or scrape URL for task.")

            process_single_job(
                conn=conn,
                job=job,
                semantic_score=0.85,
                state=state,
                synthesizer=synthesizer,
                typesetter=typesetter,
                publisher=publisher,
            )

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE job_task_queue SET status = 'COMPLETED', error_message = NULL, updated_at = NOW() WHERE id = %s;",
                (task_id,),
            )
        conn.commit()
        logger.info("Task %s completed successfully.", task_id)

    except Exception as exc:
        conn.rollback()
        logger.error("Task %s failed: %s", task_id, exc)
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
        "Starting queue listener on node '%s' (poll interval=%ds)...",
        config.worker_node_id,
        config.queue_poll_interval_seconds,
    )
    while True:
        try:
            with psycopg.connect(config.database_url) as conn:
                while poll_task_queue_once(conn, config):
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
    args = parser.parse_args()
    config = WorkerConfig()

    if args.nightly:
        run_nightly_batch(config)
    elif args.listen_queue:
        run_queue_listener(config)


if __name__ == "__main__":
    main()

