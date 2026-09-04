from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .doctor import Doctor
from .models import JobSpec, JobState, TERMINAL_STATES
from .worker import Worker


def _runtime() -> tuple[RuntimePaths, RuntimeDB, JobStore]:
    paths = RuntimePaths.discover()
    paths.ensure()
    db = RuntimeDB(paths.db_path)
    db.initialize()
    return paths, db, JobStore(db)


def _load_json(path: str | None, use_stdin: bool) -> dict[str, Any]:
    if path and use_stdin:
        raise SystemExit("use either --file or --stdin")
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if use_stdin:
        return json.load(sys.stdin)
    raise SystemExit("one of --file/--stdin is required")


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def cmd_init(_: argparse.Namespace) -> int:
    paths, db, _ = _runtime()
    _print({"status": "INITIALIZED", "home": str(paths.root), "db": str(db.path)})
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    _, _, jobs = _runtime()
    spec = JobSpec.from_mapping(_load_json(args.file, args.stdin))
    job_id = jobs.submit(spec)
    _print({"job_id": job_id, "status": jobs.get(job_id)["state"]})
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    paths, db, jobs = _runtime()
    spec = JobSpec.from_mapping(_load_json(args.file, args.stdin))
    job_id = jobs.submit(spec)
    worker = Worker(paths, db)
    deadline = time.monotonic() + args.client_timeout
    while time.monotonic() < deadline:
        row = jobs.get(job_id)
        if row and JobState(row["state"]) in TERMINAL_STATES:
            _print(_public_job(row))
            return 0 if row["state"] == JobState.SUCCEEDED.value else 2
        worker.once()
        time.sleep(0.05)
    row = jobs.get(job_id)
    _print({"job_id": job_id, "status": "JOB_STILL_PENDING", "job_state": row["state"] if row else None})
    return 3


def cmd_status(args: argparse.Namespace) -> int:
    _, _, jobs = _runtime()
    row = jobs.get(args.job_id)
    if row is None:
        _print({"error": "JOB_NOT_FOUND", "job_id": args.job_id})
        return 4
    _print(_public_job(row))
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    _, _, jobs = _runtime()
    row = jobs.get(args.job_id)
    if row is None:
        _print({"error": "JOB_NOT_FOUND", "job_id": args.job_id})
        return 4
    result = json.loads(row["result_json"]) if row.get("result_json") else None
    _print({"job_id": args.job_id, "state": row["state"], "result": result, "failure_class": row["failure_class"]})
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    _, _, jobs = _runtime()
    row = jobs.wait(args.job_id, args.timeout, poll_sec=args.poll)
    if row is None:
        _print({"error": "JOB_NOT_FOUND", "job_id": args.job_id})
        return 4
    if JobState(row["state"]) not in TERMINAL_STATES:
        _print({"job_id": args.job_id, "status": "JOB_STILL_PENDING", "job_state": row["state"]})
        return 3
    _print(_public_job(row))
    return 0 if row["state"] == JobState.SUCCEEDED.value else 2


def cmd_cancel(args: argparse.Namespace) -> int:
    _, _, jobs = _runtime()
    changed = jobs.request_cancel(args.job_id)
    row = jobs.get(args.job_id)
    if row is None:
        _print({"error": "JOB_NOT_FOUND", "job_id": args.job_id})
        return 4
    _print({"job_id": args.job_id, "cancel_accepted": changed, "state": row["state"]})
    return 0 if changed else 2


def cmd_worker(args: argparse.Namespace) -> int:
    paths, db, _ = _runtime()
    worker = Worker(paths, db)
    if args.once:
        _print({"did_work": worker.once()})
        return 0
    completed = 0
    try:
        while args.max_jobs <= 0 or completed < args.max_jobs:
            did_work = worker.once()
            if did_work:
                completed += 1
            else:
                time.sleep(args.idle_sleep)
    except KeyboardInterrupt:
        pass
    _print({"status": "WORKER_STOPPED", "completed": completed})
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    paths, db, _ = _runtime()
    doctor = Doctor(paths, db)
    report = doctor.run()
    report["report_path"] = str(doctor.write_report(report))
    _print(report)
    return 0 if report["status"] == "READY" else 2


def _public_job(row: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(row["result_json"]) if row.get("result_json") else None
    return {
        "job_id": row["job_id"],
        "state": row["state"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "failure_class": row["failure_class"],
        "partial_effect_possible": bool(row["partial_effect_possible"]),
        "result": result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browserctl")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.set_defaults(func=cmd_init)

    for name, func in (("submit", cmd_submit), ("run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--file")
        p.add_argument("--stdin", action="store_true")
        if name == "run":
            p.add_argument("--client-timeout", type=float, default=300.0)
        p.set_defaults(func=func)

    p = sub.add_parser("status")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("result")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_result)

    p = sub.add_parser("wait")
    p.add_argument("job_id")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--poll", type=float, default=0.2)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("cancel")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("worker")
    p.add_argument("--once", action="store_true")
    p.add_argument("--idle-sleep", type=float, default=0.25)
    p.add_argument("--max-jobs", type=int, default=0, help="0 means run until interrupted")
    p.set_defaults(func=cmd_worker)

    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
