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
        """Invokes the PostgreSQL 30-day retention cascade function."""
        with self.conn.cursor() as cur:
            cur.execute(PURGE_STALE_JOBS_SQL)
        self.conn.commit()
        logger.info("Completed 30-day stale job retention purge.")

