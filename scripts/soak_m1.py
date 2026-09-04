from __future__ import annotations

import argparse
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.models import JobSpec, JobState, TaskType
from browser_plane.worker import Worker


def make_paths(root: Path) -> RuntimePaths:
    return RuntimePaths(
        root=root,
        state_dir=root / "state",
        evidence_dir=root / "evidence",
        profiles_dir=root / "profiles",
        auth_state_dir=root / "auth-state",
        logs_dir=root / "logs",
        run_dir=root / "run",
        db_path=root / "state" / "runtime.db",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--browser-jobs", type=int, default=5)
    parser.add_argument("--submitters", type=int, default=8)
    args = parser.parse_args()
    if args.jobs < 1 or args.browser_jobs < 0 or args.browser_jobs > args.jobs:
        raise SystemExit("invalid job counts")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="browser-plane-m1-soak-") as tmp:
        paths = make_paths(Path(tmp))
        paths.ensure()
        db = RuntimeDB(paths.db_path)
        db.initialize()
        jobs = JobStore(db)

        c1_start = args.jobs - args.browser_jobs

        def submit(index: int) -> str:
            if index >= c1_start:
                return jobs.submit(
                    JobSpec(
                        task_type=TaskType.AUTOMATE,
                        url=(
                            "data:text/html,<html><head><title>C1-Soak-"
                            f"{index}</title></head><body>browser-{index}</body></html>"
                        ),
                        queue_timeout_sec=600,
                        max_run_sec=30,
                    )
                )
            return jobs.submit(
                JobSpec(
                    task_type=TaskType.FETCH,
                    url=f"data:text/plain,c0-soak-{index}",
                    queue_timeout_sec=600,
                    max_run_sec=10,
                )
            )

        with ThreadPoolExecutor(max_workers=args.submitters) as pool:
            job_ids = list(pool.map(submit, range(args.jobs)))

        worker = Worker(paths, db)
        processed = 0
        while processed < args.jobs:
            if worker.once():
                processed += 1
            else:
                time.sleep(0.01)

        rows = [jobs.get(job_id) for job_id in job_ids]
        states: dict[str, int] = {}
        for row in rows:
            state = str(row["state"])
            states[state] = states.get(state, 0) + 1

        with db.connect() as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            profile_leases = conn.execute("SELECT COUNT(*) FROM profile_leases").fetchone()[0]
            control_leases = conn.execute("SELECT COUNT(*) FROM control_leases").fetchone()[0]
            running_processes = conn.execute(
                "SELECT COUNT(*) FROM browser_processes WHERE shutdown_state='RUNNING'"
            ).fetchone()[0]

        report = {
            "jobs": args.jobs,
            "browser_jobs": args.browser_jobs,
            "submitters": args.submitters,
            "states": states,
            "sqlite_integrity": integrity,
            "profile_leases_remaining": profile_leases,
            "control_leases_remaining": control_leases,
            "browser_processes_running": running_processes,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
        print(json.dumps(report, indent=2, sort_keys=True))

        ok = (
            states == {JobState.SUCCEEDED.value: args.jobs}
            and integrity == "ok"
            and profile_leases == 0
            and control_leases == 0
            and running_processes == 0
        )
        return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
