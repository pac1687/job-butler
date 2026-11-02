"""Multi-node distributed lease coordinator and 30-day retention runner (SPEC.md Section 4)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ACQUIRE_LEASE_SQL = """
INSERT INTO pipeline_leases (lock_name, locked_by, expires_at)
VALUES (%s, %s, NOW() + (%s || ' minutes')::INTERVAL)
ON CONFLICT (lock_name) DO UPDATE
SET acquired_at = NOW(),
    locked_by = EXCLUDED.locked_by,
    expires_at = EXCLUDED.expires_at
WHERE pipeline_leases.expires_at < NOW()
   OR pipeline_leases.locked_by = EXCLUDED.locked_by;
"""

RENEW_LEASE_SQL = """
UPDATE pipeline_leases
SET expires_at = NOW() + (%s || ' minutes')::INTERVAL
WHERE lock_name = %s AND locked_by = %s;
"""

RELEASE_LEASE_SQL = """
UPDATE pipeline_leases
SET expires_at = NOW() - INTERVAL '1 second'
WHERE lock_name = %s AND locked_by = %s;
"""

PURGE_STALE_JOBS_SQL = "SELECT purge_stale_job_records();"

SELECT_EXPIRED_UNAPPLIED_MATCHES_SQL = """
SELECT m.id, m.job_id, m.resume_storage_key, m.cover_letter_storage_key
FROM evaluated_matches m
JOIN jobs j ON j.id = m.job_id
WHERE m.status IN ('NEW_MATCH', 'SAVED', 'ARCHIVED')
  AND (
    m.created_at < NOW() - INTERVAL '7 days'
    OR j.created_at < NOW() - INTERVAL '7 days'
    OR (
      j.location ~ 'Posted [0-9]{4}-[0-9]{2}-[0-9]{2}'
      AND to_date(substring(j.location from 'Posted ([0-9]{4}-[0-9]{2}-[0-9]{2})'), 'YYYY-MM-DD') < (CURRENT_DATE - 7)
    )
  );
"""


class LeaseCoordinator:
    """Manages distributed PostgreSQL leases across multiple workstations."""

    def __init__(self, conn: Any, worker_id: str) -> None:
        self.conn = conn
        self.worker_id = worker_id

    def acquire_lease(
        self,
        lock_name: str = "nightly_batch",
        ttl_minutes: int = 120,
    ) -> bool:
        """
        Attempts to acquire or re-enter `lock_name` for `worker_id`.
        Returns True if acquired, False if another active node holds the lease.
        """
        with self.conn.cursor() as cur:
            cur.execute(ACQUIRE_LEASE_SQL, (lock_name, self.worker_id, str(ttl_minutes)))
            affected = cur.rowcount
        self.conn.commit()

        if affected and affected > 0:
            logger.info(
                "Acquired lease '%s' for node '%s' (TTL=%dm).",
                lock_name,
                self.worker_id,
                ttl_minutes,
            )
            return True

        logger.info(
            "Lease '%s' is currently held by another workstation; skipping execution.",
            lock_name,
        )
        return False

    def renew_lease(
        self,
        lock_name: str = "nightly_batch",
        ttl_minutes: int = 120,
    ) -> bool:
        """Renews an existing lease held by this worker node."""
        with self.conn.cursor() as cur:
            cur.execute(RENEW_LEASE_SQL, (str(ttl_minutes), lock_name, self.worker_id))
            affected = cur.rowcount
        self.conn.commit()
        return bool(affected and affected > 0)

    def release_lease(self, lock_name: str = "nightly_batch") -> bool:
        """Immediately expires a lease held by this worker node."""
        with self.conn.cursor() as cur:
            cur.execute(RELEASE_LEASE_SQL, (lock_name, self.worker_id))
            affected = cur.rowcount
        self.conn.commit()
        return bool(affected and affected > 0)

    def run_retention_purge(self) -> None:
        """
        Purges unapplied ('NEW_MATCH' or 'SAVED') job listings over 7 days old (including any
        Neon Object Storage PDFs/snapshots while keeping content_hash in `jobs`), and invokes
        the PostgreSQL 30-day retention cascade function.
        """
        expired_rows: list[Any] = []
        with self.conn.cursor() as cur:
            if hasattr(cur, "fetchall"):
                cur.execute(SELECT_EXPIRED_UNAPPLIED_MATCHES_SQL)
                expired_rows = list(cur.fetchall() or [])
                if expired_rows:
                    storage_keys: list[str] = []
                    match_ids: list[str] = []
                    job_ids: list[str] = []
                    for row in expired_rows:
                        match_ids.append(str(row[0]))
                        job_ids.append(str(row[1]))
                        if row[2]:
                            storage_keys.append(str(row[2]))
                        if row[3]:
                            storage_keys.append(str(row[3]))
                    if storage_keys:
                        try:
                            from worker.publisher import ArtifactPublisher

                            ArtifactPublisher().delete_artifacts_from_r2(storage_keys)
                        except Exception as s3_exc:
                            logger.warning(
                                "Failed to purge S3 artifacts for expired matches: %s",
                                s3_exc,
                            )
                    for j_id in job_ids:
                        cur.execute(
                            "DELETE FROM job_task_queue WHERE job_id = %s;",
                            (j_id,),
                        )
                        cur.execute(
                            "UPDATE jobs SET description_text = '' WHERE id = %s;",
                            (j_id,),
                        )
                    for m_id in match_ids:
                        cur.execute(
                            "DELETE FROM evaluated_matches WHERE id = %s;",
                            (m_id,),
                        )
                    logger.info(
                        "Auto-purged %d expired (>7 days old) NEW_MATCH/SAVED job card(s).",
                        len(match_ids),
                    )
            cur.execute(PURGE_STALE_JOBS_SQL)
        self.conn.commit()
        logger.info("Completed 7-day unapplied & 30-day stale job retention purge.")

