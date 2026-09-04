from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass

from .db import RuntimeDB, iso


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_token: str
    command: str


def inspect_process(pid: int) -> ProcessIdentity | None:
    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = proc.stdout.strip()
    if proc.returncode != 0 or not line:
        return None
    # macOS ps lstart is five tokens: Day Mon DD HH:MM:SS YYYY.
    parts = line.split(None, 5)
    if len(parts) < 6:
        return None
    start_token = " ".join(parts[:5])
    command = parts[5]
    return ProcessIdentity(pid=pid, start_token=start_token, command=command)


class BrowserProcessRegistry:
    def __init__(self, db: RuntimeDB):
        self.db = db

    def register(
        self,
        *,
        pid: int,
        job_id: str,
        runtime_kind: str,
        profile_id: str | None,
        user_data_dir: str | None,
        cdp_endpoint: str | None = None,
    ) -> str:
        identity = inspect_process(pid)
        if identity is None:
            raise RuntimeError(f"cannot establish process identity for pid={pid}")
        browser_process_id = str(uuid.uuid4())
        now = iso()
        with self.db.immediate() as conn:
            conn.execute(
                """
                INSERT INTO browser_processes(
                    browser_process_id,pid,process_start_token,job_id,runtime_kind,profile_id,
                    user_data_dir,cdp_endpoint,spawned_by_runtime,spawned_at,last_seen_at,shutdown_state
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    browser_process_id,
                    pid,
                    identity.start_token,
                    job_id,
                    runtime_kind,
                    profile_id,
                    user_data_dir,
                    cdp_endpoint,
                    1,
                    now,
                    now,
                    "RUNNING",
                ),
            )
        return browser_process_id

    def get(self, browser_process_id: str) -> dict[str, object] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_processes WHERE browser_process_id=?",
                (browser_process_id,),
            ).fetchone()
        return dict(row) if row else None

    def verify_owned(self, browser_process_id: str) -> bool:
        row = self.get(browser_process_id)
        if not row or not row.get("spawned_by_runtime"):
            return False
        identity = inspect_process(int(row["pid"]))
        if identity is None:
            return False
        return identity.start_token == row["process_start_token"]

    def mark_seen(self, browser_process_id: str) -> bool:
        if not self.verify_owned(browser_process_id):
            return False
        with self.db.immediate() as conn:
            cur = conn.execute(
                "UPDATE browser_processes SET last_seen_at=? WHERE browser_process_id=?",
                (iso(), browser_process_id),
            )
            return cur.rowcount == 1

    def mark_closed(self, browser_process_id: str, state: str = "CLOSED") -> None:
        with self.db.immediate() as conn:
            conn.execute(
                "UPDATE browser_processes SET shutdown_state=?,last_seen_at=? WHERE browser_process_id=?",
                (state, iso(), browser_process_id),
            )

    def terminate_owned(self, browser_process_id: str, grace_sec: float = 3.0) -> bool:
        row = self.get(browser_process_id)
        if not row:
            return False
        pid = int(row["pid"])
        if not self.verify_owned(browser_process_id):
            self.mark_closed(browser_process_id, "OWNERSHIP_UNCERTAIN")
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self.mark_closed(browser_process_id)
            return True
        deadline = time.monotonic() + max(0.1, grace_sec)
        while time.monotonic() < deadline:
            if inspect_process(pid) is None:
                self.mark_closed(browser_process_id)
                return True
            time.sleep(0.1)
        if not self.verify_owned(browser_process_id):
            self.mark_closed(browser_process_id, "OWNERSHIP_UNCERTAIN")
            return False
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.mark_closed(browser_process_id, "FORCE_KILLED")
        return True

    def owned_running(self) -> list[dict[str, object]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browser_processes WHERE shutdown_state='RUNNING' ORDER BY spawned_at"
            ).fetchall()
        return [dict(row) for row in rows]
