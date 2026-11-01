"""Cloudflare R2 artifact uploader and Neon PostgreSQL transactional publisher (FR-2.6 / Task 3.9)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import boto3
from botocore.config import Config as BotoConfig

from worker.config import WorkerConfig
from worker.schemas import JobEvaluationResult, ScrapedJob

logger = logging.getLogger(__name__)

UPSERT_JOB_SQL = """
INSERT INTO jobs (
    source, source_id, title, company, location, is_remote,
    url, content_hash, description_text, salary_range
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (content_hash) DO UPDATE
SET salary_range = COALESCE(EXCLUDED.salary_range, jobs.salary_range)
RETURNING id;
"""

INSERT_MATCH_SQL = """
INSERT INTO evaluated_matches (
    job_id, semantic_score, fit_score, fit_rationale,
    matched_skills, missing_skills,
    resume_storage_key, cover_letter_storage_key,
    payload_snapshot, status
)
VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, 'NEW_MATCH')
RETURNING id;
"""


class ArtifactPublisher:
    """Uploads compiled PDFs and JSON snapshots to Cloudflare R2 and commits records to Neon PostgreSQL."""

    def __init__(
        self,
        config: Optional[WorkerConfig] = None,
        s3_client: Optional[Any] = None,
    ) -> None:
        self.config = config or WorkerConfig()
        self._s3 = s3_client

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            # Neon Object Storage requires path-style S3 addressing (force_path_style = true)
            self._s3 = boto3.client(
                "s3",
                endpoint_url=self.config.r2_endpoint_url,
                aws_access_key_id=self.config.r2_access_key_id,
                aws_secret_access_key=self.config.r2_secret_access_key,
                region_name=self.config.s3_region,
                config=BotoConfig(
                    s3={"addressing_style": "path"},
                    signature_version="s3v4",
                ),
            )
        return self._s3

    def upload_artifacts_to_r2(
        self,
        job_content_hash: str,
        resume_pdf_path: Path,
        cover_letter_pdf_path: Path,
        payload_snapshot: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Uploads `resume.pdf`, `cover_letter.pdf`, and `payload_snapshot.json` to private R2 bucket.
        Returns the object storage keys.
        """
        prefix = f"matches/{job_content_hash[:16]}"
        resume_key = f"{prefix}/resume.pdf"
        cover_key = f"{prefix}/cover_letter.pdf"
        snapshot_key = f"{prefix}/payload_snapshot.json"

        endpoint = (self.config.r2_endpoint_url or "").strip()
        is_valid_endpoint = (
            endpoint.startswith("https://")
            and "<" not in endpoint
            and ">" not in endpoint
        )
        if not is_valid_endpoint or not self.config.r2_access_key_id:
            logger.warning(
                "S3/R2 endpoint '%s' is unconfigured or contains a placeholder; skipping S3 upload and recording logical keys under %s",
                endpoint,
                prefix,
            )
            return {
                "resume_storage_key": resume_key,
                "cover_letter_storage_key": cover_key,
                "snapshot_storage_key": snapshot_key,
            }

        bucket = self.config.r2_bucket_name
        self.s3.upload_file(
            str(resume_pdf_path),
            bucket,
            resume_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        self.s3.upload_file(
            str(cover_letter_pdf_path),
            bucket,
            cover_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        self.s3.put_object(
            Bucket=bucket,
            Key=snapshot_key,
            Body=json.dumps(payload_snapshot, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Uploaded PDFs and snapshot to R2 bucket '%s' under '%s'", bucket, prefix)
        return {
            "resume_storage_key": resume_key,
            "cover_letter_storage_key": cover_key,
            "snapshot_storage_key": snapshot_key,
        }

    def persist_evaluated_match(
        self,
        conn: Any,
        job: ScrapedJob,
        semantic_score: float,
        evaluation: JobEvaluationResult,
        resume_storage_key: Optional[str],
        cover_letter_storage_key: Optional[str],
        payload_snapshot: Dict[str, Any],
    ) -> str:
        """Transactionally persists the job listing and evaluated match into Neon PostgreSQL."""
        with conn.cursor() as cur:
            cur.execute(
                UPSERT_JOB_SQL,
                (
                    job.source,
                    job.source_id,
                    job.title,
                    job.company,
                    job.location,
                    job.is_remote,
                    job.url,
                    job.content_hash,
                    job.description_text,
                    job.salary_range,
                ),
            )
            job_row = cur.fetchone()
            job_id = str(job_row[0])

            cur.execute(
                INSERT_MATCH_SQL,
                (
                    job_id,
                    semantic_score,
                    evaluation.fit_score,
                    evaluation.fit_rationale,
                    json.dumps(evaluation.matched_skills),
                    json.dumps(evaluation.missing_skills),
                    resume_storage_key,
                    cover_letter_storage_key,
                    json.dumps(payload_snapshot),
                ),
            )
            match_row = cur.fetchone()
            match_id = str(match_row[0])
        conn.commit()
        return match_id

    def update_match_artifacts(
        self,
        conn: Any,
        job_id: str,
        resume_storage_key: Optional[str],
        cover_letter_storage_key: Optional[str],
        payload_snapshot: Dict[str, Any],
    ) -> Optional[str]:
        """Updates an existing evaluated_matches row with newly compiled PDF storage keys and snapshot."""
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE evaluated_matches
                SET resume_storage_key = %s,
                    cover_letter_storage_key = %s,
                    payload_snapshot = %s::jsonb
                WHERE job_id = %s
                RETURNING id;
                """,
                (
                    resume_storage_key,
                    cover_letter_storage_key,
                    json.dumps(payload_snapshot),
                    job_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return str(row[0]) if row else None


