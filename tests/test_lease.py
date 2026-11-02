"""Unit tests for distributed PostgreSQL lease coordinator in worker/lease.py (Task 6.4)."""

from __future__ import annotations

from typing import Any, List, Tuple
from worker.config import WorkerConfig
from worker.lease import LeaseCoordinator


class FakeCursor:
    def __init__(self, rowcount_sequence: List[int]) -> None:
        self._seq = rowcount_sequence
        self.executed: List[Tuple[str, Any]] = []
        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        self.rowcount = self._seq.pop(0) if self._seq else 0


class FakeConnection:
    def __init__(self, rowcount_sequence: List[int]) -> None:
        self.cursor_instance = FakeCursor(rowcount_sequence)
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def test_lease_acquisition_success() -> None:
    conn = FakeConnection([1])
    coordinator = LeaseCoordinator(conn, worker_id="macbook-pro-m1")
    acquired = coordinator.acquire_lease("nightly_batch", ttl_minutes=120)
    assert acquired is True
    assert conn.commits == 1
    sql, params = conn.cursor_instance.executed[0]
    assert "INSERT INTO pipeline_leases" in sql
    assert params == ("nightly_batch", "macbook-pro-m1", "120")


def test_lease_collision_rejection_when_held_by_another_node() -> None:
    # 0 rows affected means another machine holds an unexpired lease
    conn = FakeConnection([0])
    coordinator = LeaseCoordinator(conn, worker_id="windows-workstation")
    acquired = coordinator.acquire_lease("nightly_batch", ttl_minutes=120)
    assert acquired is False
    assert conn.commits == 1


def test_lease_force_takeover_and_heartbeat() -> None:
    conn = FakeConnection([1, 1])
    coordinator = LeaseCoordinator(conn, worker_id="windows-pc")
    coordinator.heartbeat(ttl_seconds=60)
    acquired = coordinator.acquire_lease("nightly_batch", ttl_minutes=15, force=True)
    assert acquired is True
    assert conn.commits == 2
    hb_sql, hb_params = conn.cursor_instance.executed[0]
    assert "INSERT INTO pipeline_leases" in hb_sql
    assert hb_params == ("worker_heartbeat:windows-pc", "windows-pc", "60")
    force_sql, force_params = conn.cursor_instance.executed[1]
    assert "WHERE pipeline_leases.expires_at" not in force_sql
    assert force_params == ("nightly_batch", "windows-pc", "15")


def test_worker_config_priority_defaults(monkeypatch: Any) -> None:
    monkeypatch.setenv("WORKER_NODE_ID", "windows-pc")
    monkeypatch.setenv("WORKER_PRIORITY", "1")
    monkeypatch.setenv("FALLBACK_CLAIM_DELAY_SECONDS", "30")
    cfg = WorkerConfig.from_env()
    assert cfg.worker_node_id == "windows-pc"
    assert cfg.worker_priority == 1
    assert cfg.fallback_claim_delay_seconds == 30


def test_lease_renewal_and_release() -> None:
    conn = FakeConnection([1, 1, 0])
    coordinator = LeaseCoordinator(conn, worker_id="macbook-pro-m1")

    assert coordinator.renew_lease("nightly_batch", ttl_minutes=60) is True
    assert coordinator.release_lease("nightly_batch") is True
    coordinator.run_retention_purge()
    assert conn.commits == 3
    assert "purge_stale_job_records" in conn.cursor_instance.executed[-1][0]
