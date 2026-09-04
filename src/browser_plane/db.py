from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .models import JobSpec, JobState


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    spec_json TEXT NOT NULL,
    state TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    queue_deadline_at TEXT NOT NULL,
    execution_deadline_at TEXT,
    human_hold_deadline_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    cancel_requested_at TEXT,
    failure_class TEXT,
    result_json TEXT,
    partial_effect_possible INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created_at);

CREATE TABLE IF NOT EXISTS profile_leases (
    profile_id TEXT PRIMARY KEY,
    owner_job_id TEXT NOT NULL,
    owner_browser_process_id TEXT,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS control_leases (
    browser_session_id TEXT PRIMARY KEY,
    owner_job_id TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS browser_processes (
    browser_process_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    process_start_token TEXT NOT NULL,
    job_id TEXT NOT NULL,
    runtime_kind TEXT NOT NULL,
    profile_id TEXT,
    user_data_dir TEXT,
    cdp_endpoint TEXT,
    spawned_by_runtime INTEGER NOT NULL DEFAULT 1,
    spawned_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    shutdown_state TEXT NOT NULL DEFAULT 'RUNNING'
);
CREATE INDEX IF NOT EXISTS idx_browser_processes_job ON browser_processes(job_id);

CREATE TABLE IF NOT EXISTS runtime_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    job_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
"""


class RuntimeDB:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


class JobStore:
    def __init__(self, db: RuntimeDB):
        self.db = db

    def submit(self, spec: JobSpec) -> str:
        now = utcnow()
        queue_deadline = now + timedelta(seconds=max(1, spec.queue_timeout_sec))
        spec_json = json.dumps(spec.__dict__, default=str, sort_keys=True)
        if spec.idempotency_key:
            with self.db.connect() as conn:
                existing = conn.execute(
                    "SELECT job_id FROM jobs WHERE idempotency_key=?",
                    (spec.idempotency_key,),
                ).fetchone()
                if existing:
                    return str(existing["job_id"])
        job_id = str(uuid.uuid4())
        with self.db.immediate() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id,idempotency_key,spec_json,state,created_at,updated_at,queue_deadline_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    spec.idempotency_key,
                    spec_json,
                    JobState.QUEUED.value,
                    iso(now),
                    iso(now),
                    iso(queue_deadline),
                ),
            )
            self._event(conn, "JOB_SUBMITTED", job_id, {"task_type": spec.task_type.value})
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def next_runnable(self) -> dict[str, Any] | None:
        now = iso()
        with self.db.immediate() as conn:
            expired = conn.execute(
                "SELECT job_id,state_version FROM jobs WHERE state IN (?,?) AND queue_deadline_at <= ? ORDER BY created_at",
                (JobState.QUEUED.value, JobState.WAITING_RESOURCE.value, now),
            ).fetchall()
            for row in expired:
                conn.execute(
                    "UPDATE jobs SET state=?,state_version=state_version+1,updated_at=?,finished_at=?,failure_class=? WHERE job_id=? AND state_version=?",
                    (
                        JobState.QUEUE_TIMEOUT.value,
                        now,
                        now,
                        "QUEUE_TIMEOUT",
                        row["job_id"],
                        row["state_version"],
                    ),
                )
            row = conn.execute(
                "SELECT * FROM jobs WHERE state IN (?,?) ORDER BY created_at LIMIT 1",
                (JobState.QUEUED.value, JobState.WAITING_RESOURCE.value),
            ).fetchone()
            return dict(row) if row else None

    def transition(
        self,
        job_id: str,
        from_states: set[JobState],
        to_state: JobState,
        *,
        failure_class: str | None = None,
        result: dict[str, Any] | None = None,
        partial_effect_possible: bool | None = None,
    ) -> bool:
        now = utcnow()
        with self.db.immediate() as conn:
            row = conn.execute("SELECT state,state_version,spec_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or JobState(row["state"]) not in from_states:
                return False
            fields = ["state=?", "state_version=state_version+1", "updated_at=?"]
            values: list[Any] = [to_state.value, iso(now)]
            if to_state == JobState.RUNNING:
                spec = json.loads(row["spec_json"])
                fields.extend(["started_at=COALESCE(started_at,?)", "execution_deadline_at=?"])
                values.extend([iso(now), iso(now + timedelta(seconds=max(1, int(spec.get("max_run_sec", 120)))) )])
            if to_state in {
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.QUEUE_TIMEOUT,
                JobState.EXECUTION_TIMEOUT,
                JobState.STALLED_HUMAN_TIMEOUT,
            }:
                fields.append("finished_at=?")
                values.append(iso(now))
            if failure_class is not None:
                fields.append("failure_class=?")
                values.append(failure_class)
            if result is not None:
                fields.append("result_json=?")
                values.append(json.dumps(result, sort_keys=True))
            if partial_effect_possible is not None:
                fields.append("partial_effect_possible=?")
                values.append(1 if partial_effect_possible else 0)
            values.extend([job_id, row["state_version"]])
            cur = conn.execute(
                f"UPDATE jobs SET {','.join(fields)} WHERE job_id=? AND state_version=?",
                values,
            )
            if cur.rowcount == 1:
                self._event(conn, "JOB_STATE", job_id, {"to": to_state.value})
                return True
            return False

    def request_cancel(self, job_id: str) -> bool:
        now = iso()
        with self.db.immediate() as conn:
            row = conn.execute("SELECT state,state_version FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return False
            state = JobState(row["state"])
            if state in {JobState.QUEUED, JobState.WAITING_RESOURCE}:
                target = JobState.CANCELLED
                finished = now
            elif state in {JobState.RUNNING, JobState.PAUSED_FOR_INSPECTION, JobState.WAITING_HUMAN}:
                target = JobState.CANCEL_REQUESTED
                finished = None
            else:
                return False
            cur = conn.execute(
                """
                UPDATE jobs SET state=?,state_version=state_version+1,updated_at=?,cancel_requested_at=?,finished_at=?
                WHERE job_id=? AND state_version=?
                """,
                (target.value, now, now, finished, job_id, row["state_version"]),
            )
            if cur.rowcount == 1:
                self._event(conn, "JOB_CANCEL_REQUESTED", job_id, {"state": target.value})
                return True
            return False

    def wait(self, job_id: str, timeout_sec: float, poll_sec: float = 0.2) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            row = self.get(job_id)
            if row is None:
                return None
            if JobState(row["state"]) in {
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.QUEUE_TIMEOUT,
                JobState.EXECUTION_TIMEOUT,
                JobState.STALLED_HUMAN_TIMEOUT,
            }:
                return row
            time.sleep(poll_sec)
        return self.get(job_id)

    @staticmethod
    def _event(conn: sqlite3.Connection, event_type: str, job_id: str | None, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO runtime_events(created_at,event_type,job_id,payload_json) VALUES(?,?,?,?)",
            (iso(), event_type, job_id, json.dumps(payload, sort_keys=True)),
        )
