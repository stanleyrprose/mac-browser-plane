from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from .config import RuntimePaths
from .db import RuntimeDB
from .leases import LeaseManager
from .processes import BrowserProcessRegistry


class Doctor:
    def __init__(self, paths: RuntimePaths, db: RuntimeDB):
        self.paths = paths
        self.db = db

    def run(self) -> dict[str, object]:
        checks: list[dict[str, object]] = []
        status = "READY"

        def add(name: str, ok: bool, detail: object = None, degraded: bool = True) -> None:
            nonlocal status
            checks.append({"name": name, "ok": ok, "detail": detail})
            if not ok:
                status = "DEGRADED" if degraded and status == "READY" else "NOT_READY"

        try:
            self.paths.ensure()
            add("runtime_paths", True, str(self.paths.root))
        except OSError as exc:
            add("runtime_paths", False, str(exc), degraded=False)

        try:
            with self.db.connection() as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                sync = conn.execute("PRAGMA synchronous").fetchone()[0]
                busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            add("sqlite_integrity", integrity == "ok", integrity, degraded=False)
            add("sqlite_wal", str(journal).lower() == "wal", journal, degraded=False)
            add("sqlite_synchronous_full", int(sync) == 2, sync, degraded=False)
            add("sqlite_busy_timeout", int(busy) >= 5000, busy, degraded=False)
        except Exception as exc:
            add("sqlite", False, f"{type(exc).__name__}: {exc}", degraded=False)

        chrome = Path(os.environ.get("BROWSER_PLANE_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
        add("chrome", chrome.exists() and os.access(chrome, os.X_OK), str(chrome), degraded=False)
        add("playwright_python", importlib.util.find_spec("playwright") is not None, "required for C1", degraded=True)

        stale = LeaseManager(self.db).list_stale_profiles()
        add("stale_profile_leases", not stale, stale, degraded=True)

        registry = BrowserProcessRegistry(self.db)
        ambiguous: list[str] = []
        for row in registry.owned_running():
            browser_process_id = str(row["browser_process_id"])
            if not registry.verify_owned(browser_process_id):
                ambiguous.append(browser_process_id)
        add("browser_process_ownership", not ambiguous, ambiguous, degraded=True)

        free = os.statvfs(self.paths.root)
        free_bytes = free.f_bavail * free.f_frsize
        add("free_disk", free_bytes >= 2 * 1024**3, {"free_bytes": free_bytes}, degraded=True)

        return {"status": status, "checks": checks}

    def write_report(self, report: dict[str, object]) -> Path:
        target = self.paths.run_dir / "doctor.json"
        target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        target.chmod(0o600)
        return target
