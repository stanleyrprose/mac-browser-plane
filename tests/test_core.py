from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.executor import BrowserExecutor, CapabilityError
from browser_plane.leases import LeaseManager
from browser_plane.models import Egress, JobSpec, JobState, ProfileMode, TaskType
from browser_plane.processes import BrowserProcessRegistry
from browser_plane.worker import Worker


def make_runtime(tmp: str) -> tuple[RuntimePaths, RuntimeDB, JobStore]:
    root = Path(tmp) / "runtime"
    paths = RuntimePaths(
        root=root,
        state_dir=root / "state",
        evidence_dir=root / "evidence",
        profiles_dir=root / "profiles",
        auth_state_dir=root / "auth-state",
        logs_dir=root / "logs",
        run_dir=root / "run",
        db_path=root / "state" / "runtime.db",
    )
    paths.ensure()
    db = RuntimeDB(paths.db_path)
    db.initialize()
    return paths, db, JobStore(db)


class DBTests(unittest.TestCase):
    def test_wal_full_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, db, _ = make_runtime(tmp)
            with db.connect() as conn:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 2)
                self.assertGreaterEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_idempotent_submit_and_queued_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, jobs = make_runtime(tmp)
            spec = JobSpec(task_type=TaskType.FETCH, url="data:text/plain,ok", idempotency_key="same")
            first = jobs.submit(spec)
            second = jobs.submit(spec)
            self.assertEqual(first, second)
            self.assertTrue(jobs.request_cancel(first))
            self.assertEqual(jobs.get(first)["state"], JobState.CANCELLED.value)

    def test_state_cas_rejects_invalid_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, jobs = make_runtime(tmp)
            job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,ok"))
            self.assertFalse(jobs.transition(job_id, {JobState.RUNNING}, JobState.SUCCEEDED))
            self.assertEqual(jobs.get(job_id)["state"], JobState.QUEUED.value)


class LeaseTests(unittest.TestCase):
    def test_profile_lease_is_exclusive_and_fenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, db, _ = make_runtime(tmp)
            leases = LeaseManager(db)
            epoch_a = leases.acquire_profile("authenticated-work", "job-a")
            self.assertEqual(epoch_a, 1)
            self.assertIsNone(leases.acquire_profile("authenticated-work", "job-b"))
            self.assertFalse(leases.release_profile("authenticated-work", "job-a", 999))
            self.assertTrue(leases.release_profile("authenticated-work", "job-a", epoch_a))
            self.assertEqual(leases.acquire_profile("authenticated-work", "job-b"), 1)

    def test_control_lease_is_session_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, db, _ = make_runtime(tmp)
            leases = LeaseManager(db)
            epoch = leases.acquire_control("session-1", "job-a", "PLAYWRIGHT")
            self.assertEqual(epoch, 1)
            self.assertIsNone(leases.acquire_control("session-1", "job-b", "PLAYWRIGHT"))
            self.assertTrue(leases.release_control("session-1", "job-a", epoch))


class ProcessRegistryTests(unittest.TestCase):
    def test_runtime_owned_process_is_verified_and_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, db, _ = make_runtime(tmp)
            proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            registry = BrowserProcessRegistry(db)
            try:
                process_id = registry.register(
                    pid=proc.pid,
                    job_id="job-a",
                    runtime_kind="TEST",
                    profile_id=None,
                    user_data_dir=None,
                )
                self.assertTrue(registry.verify_owned(process_id))
                self.assertTrue(registry.terminate_owned(process_id, grace_sec=1.0))
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=2)


class ExecutorTests(unittest.TestCase):
    def test_c0_direct_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,hello-browser-plane"))
            self.assertTrue(Worker(paths, db).once())
            row = jobs.get(job_id)
            self.assertEqual(row["state"], JobState.SUCCEEDED.value)
            result = json.loads(row["result_json"])
            self.assertEqual(result["engine"], "c0-fetch")
            self.assertIn("hello-browser-plane", result["text_excerpt"])
            self.assertTrue((paths.evidence_dir / job_id / "result.json").exists())

    def test_m1_rejects_sea_and_c3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            executor = BrowserExecutor(paths, db)
            with self.assertRaises(CapabilityError):
                executor.preflight(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,x", egress=Egress.SOUTHEAST_ASIA))
            with self.assertRaises(CapabilityError):
                executor.preflight(JobSpec(task_type=TaskType.AGENT, url="data:text/plain,x"))

    def test_stale_cdp_discovery_file_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)
            marker = profile / "DevToolsActivePort"
            marker.write_text("12345\n/devtools/browser/old\n", encoding="utf-8")
            BrowserExecutor._clear_stale_cdp_discovery(profile)
            self.assertFalse(marker.exists())

    def test_persistent_profile_waits_instead_of_double_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            leases = LeaseManager(db)
            held = leases.acquire_profile("authenticated-work", "external-job")
            self.assertIsNotNone(held)
            job_id = jobs.submit(
                JobSpec(
                    task_type=TaskType.FETCH,
                    url="data:text/plain,x",
                    profile="authenticated-work",
                    profile_mode=ProfileMode.EXCLUSIVE_PERSISTENT,
                )
            )
            self.assertFalse(Worker(paths, db).once())
            self.assertEqual(jobs.get(job_id)["state"], JobState.WAITING_RESOURCE.value)

    def test_running_cancel_finishes_cancelled_not_succeeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,x"))

            def slow_fetch(_: JobSpec) -> dict[str, object]:
                time.sleep(0.3)
                return {"engine": "test", "ok": True}

            with patch.object(BrowserExecutor, "_run_fetch", side_effect=slow_fetch):
                thread = threading.Thread(target=Worker(paths, db).once)
                thread.start()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and jobs.get(job_id)["state"] != JobState.RUNNING.value:
                    time.sleep(0.01)
                self.assertEqual(jobs.get(job_id)["state"], JobState.RUNNING.value)
                self.assertTrue(jobs.request_cancel(job_id))
                thread.join(timeout=2)
            row = jobs.get(job_id)
            self.assertEqual(row["state"], JobState.CANCELLED.value)
            self.assertEqual(row["partial_effect_possible"], 1)


if __name__ == "__main__":
    unittest.main()
