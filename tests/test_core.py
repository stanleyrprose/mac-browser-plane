from __future__ import annotations

import hashlib
import importlib.resources
import json
import shutil
import stat
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from browser_plane.cli import _try_worker_lock
from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.doctor import Doctor
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


class CapabilityManifestTests(unittest.TestCase):
    def test_manifest_matches_authorized_r1_boundary(self) -> None:
        resource = importlib.resources.files("browser_plane").joinpath("capabilities.json")
        manifest = json.loads(resource.read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 1)
        self.assertEqual(manifest["provider_id"], "mac-mm-01")
        self.assertFalse(manifest["production_enabled"])
        self.assertEqual(manifest["invocation_mode"], "local_cli_only")
        self.assertTrue(manifest["network"]["direct"])
        self.assertFalse(manifest["network"]["southeast_asia"])
        self.assertFalse(manifest["network"]["china"])
        self.assertTrue(manifest["capabilities"]["c0_fetch"])
        self.assertTrue(manifest["capabilities"]["c1_render"])
        self.assertFalse(manifest["capabilities"]["c1_generic_interaction"])
        self.assertTrue(manifest["capabilities"]["c2_readonly_inspect"])
        self.assertTrue(manifest["capabilities"]["c3_browser_use"])
        self.assertFalse(manifest["capabilities"]["c3_browser_agent"])
        self.assertFalse(manifest["capabilities"]["remote_invocation"])
        self.assertTrue(manifest["security"]["tls_verification_required"])
        self.assertTrue(manifest["security"]["cdp_loopback_only"])
        self.assertTrue(manifest["local_agent_adapter"]["enabled"])
        self.assertEqual(manifest["local_agent_adapter"]["transport"], "stdio")
        self.assertFalse(manifest["local_agent_adapter"]["network_listener"])
        self.assertTrue(manifest["local_agent_adapter"]["generic_interaction"])
        self.assertFalse(manifest["local_agent_adapter"]["arbitrary_javascript"])
        self.assertFalse(manifest["local_agent_adapter"]["raw_cdp"])


class DBTests(unittest.TestCase):
    def test_wal_full_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, db, _ = make_runtime(tmp)
            with db.connection() as conn:
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

    def test_sqlite_backup_is_consistent_and_restorable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,backup"))
            backup_path = paths.root / "backups" / "runtime-test.db"
            report = db.backup_to(backup_path)
            self.assertEqual(report["integrity"], "ok")
            self.assertTrue(backup_path.exists())
            self.assertEqual(stat.S_IMODE(paths.db_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup_path.stat().st_mode), 0o600)

            restored_path = Path(tmp) / "restored" / "state" / "runtime.db"
            restored_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, restored_path)
            restored_db = RuntimeDB(restored_path)
            restored_jobs = JobStore(restored_db)
            restored = restored_jobs.get(job_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored["state"], JobState.QUEUED.value)
            with restored_db.connection() as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_doctor_report_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            target = Doctor(paths, db).write_report({"status": "READY", "checks": []})
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


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


class RecoveryTests(unittest.TestCase):
    def test_worker_lock_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, _, _ = make_runtime(tmp)
            first = _try_worker_lock(paths)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(_try_worker_lock(paths))
            finally:
                assert first is not None
                first.close()
            second = _try_worker_lock(paths)
            self.assertIsNotNone(second)
            assert second is not None
            second.close()

    def test_startup_recovery_reaps_owned_process_and_releases_leases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,recovery"))
            self.assertTrue(jobs.transition(job_id, {JobState.QUEUED}, JobState.RUNNING))

            leases = LeaseManager(db)
            profile_epoch = leases.acquire_profile("development", job_id)
            self.assertIsNotNone(profile_epoch)
            control_epoch = leases.acquire_control("session-recovery", job_id, "PLAYWRIGHT")
            self.assertIsNotNone(control_epoch)

            proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            registry = BrowserProcessRegistry(db)
            try:
                process_id = registry.register(
                    pid=proc.pid,
                    job_id=job_id,
                    runtime_kind="TEST",
                    profile_id=None,
                    user_data_dir=None,
                )
                report = Worker(paths, db).recover_startup()
                self.assertIn(job_id, report["recovered"])
                row = jobs.get(job_id)
                self.assertEqual(row["state"], JobState.RECOVERY_REQUIRED.value)
                self.assertEqual(row["failure_class"], "STATE_RECOVERY_REQUIRED")
                proc.wait(timeout=3)
                process_row = registry.get(process_id)
                self.assertNotEqual(process_row["shutdown_state"], "RUNNING")
                with db.connection() as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM profile_leases WHERE owner_job_id=?", (job_id,)).fetchone()[0], 0)
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM control_leases WHERE owner_job_id=?", (job_id,)).fetchone()[0], 0)
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
            evidence_path = paths.evidence_dir / job_id / "result.json"
            self.assertTrue(evidence_path.exists())
            self.assertEqual(stat.S_IMODE(evidence_path.stat().st_mode), 0o600)

    def test_c0_http_uses_system_curl_path(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b"curl-path-ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths, db, jobs = make_runtime(tmp)
                url = f"http://127.0.0.1:{server.server_port}/"
                job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url=url))
                self.assertTrue(Worker(paths, db).once())
                row = jobs.get(job_id)
                self.assertEqual(row["state"], JobState.SUCCEEDED.value)
                result = json.loads(row["result_json"])
                self.assertEqual(result["status"], 200)
                self.assertEqual(result["url"], url)
                self.assertIn("curl-path-ok", result["text_excerpt"])
                artifact = Path(result["artifact_path"])
                self.assertEqual(artifact.name, "response.txt")
                self.assertEqual(artifact.read_bytes(), b"curl-path-ok")
                self.assertEqual(result["sha256"], hashlib.sha256(b"curl-path-ok").hexdigest())
                self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_c0_binary_response_is_saved_as_private_artifact(self) -> None:
        payload = b"%PDF-1.7\nminimal-binary-evidence\n"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths, db, jobs = make_runtime(tmp)
                url = f"http://127.0.0.1:{server.server_port}/tender.pdf"
                job_id = jobs.submit(JobSpec(task_type=TaskType.FETCH, url=url))
                self.assertTrue(Worker(paths, db).once())
                row = jobs.get(job_id)
                self.assertEqual(row["state"], JobState.SUCCEEDED.value)
                result = json.loads(row["result_json"])
                self.assertNotIn("text_excerpt", result)
                artifact = Path(result["artifact_path"])
                self.assertEqual(artifact.name, "response.pdf")
                self.assertEqual(artifact.read_bytes(), payload)
                self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_r1_rejects_regional_egress_and_autonomous_agent_but_allows_inspect_and_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            executor = BrowserExecutor(paths, db)
            with self.assertRaises(CapabilityError):
                executor.preflight(JobSpec(task_type=TaskType.FETCH, url="data:text/plain,x", egress=Egress.SOUTHEAST_ASIA))
            with self.assertRaises(CapabilityError):
                executor.preflight(JobSpec(task_type=TaskType.AGENT, url="data:text/plain,x"))
            with patch.object(BrowserExecutor, "_playwright_available", return_value=True):
                executor.preflight(JobSpec(task_type=TaskType.INSPECT, url="data:text/plain,x"))
                executor.preflight(
                    JobSpec(task_type=TaskType.USE, url="data:text/plain,x", actions=({"action": "snapshot"},))
                )

    def test_c3_browser_use_executes_action_sequence_and_preserves_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            executor = BrowserExecutor(paths, db)
            page = Mock()
            page.url = "https://example.com/start"
            page.title.return_value = "Example"

            locators: dict[str, Mock] = {}

            def locator(selector: str) -> Mock:
                current = locators.setdefault(selector, Mock())
                if selector == "body":
                    current.inner_text.return_value = "body text"
                if selector == "#select":
                    current.select_option.return_value = ["b"]
                return current

            page.locator.side_effect = locator
            response = Mock(status=204)

            def goto(url: str, **_: object) -> Mock:
                page.url = url
                return response

            page.goto.side_effect = goto
            page.screenshot.side_effect = lambda path, **_: Path(path).write_bytes(b"png")

            download = Mock()
            download.suggested_filename = "report.pdf"
            download.save_as.side_effect = lambda path: Path(path).write_bytes(b"pdf")

            class DownloadContext:
                value = download

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            page.expect_download.side_effect = lambda **_: DownloadContext()
            actions = (
                {"action": "navigate", "url": "https://example.com/next"},
                {"action": "click", "selector": "#button", "force": True},
                {"action": "type", "selector": "#input", "text": "hello"},
                {"action": "select", "selector": "#select", "value": "b"},
                {"action": "press", "key": "Escape"},
                {"action": "wait", "ms": 5},
                {"action": "snapshot"},
                {"action": "screenshot"},
                {"action": "download", "selector": "#download"},
            )

            results = executor._run_browser_actions(page, "job-c3", actions)

            self.assertEqual(len(results), 9)
            self.assertEqual(results[0]["status"], 204)
            locators["#button"].click.assert_called_once_with(timeout=10_000, force=True)
            locators["#input"].fill.assert_called_once_with("hello", timeout=10_000)
            locators["#select"].select_option.assert_called_once_with(value="b", timeout=10_000)
            page.keyboard.press.assert_called_once_with("Escape")
            page.wait_for_timeout.assert_called_once_with(5)
            self.assertEqual(results[6]["text_excerpt"], "body text")

            screenshot = Path(str(results[7]["path"]))
            downloaded = Path(str(results[8]["path"]))
            self.assertEqual(screenshot.read_bytes(), b"png")
            self.assertEqual(downloaded.read_bytes(), b"pdf")
            self.assertEqual(stat.S_IMODE(screenshot.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(downloaded.stat().st_mode), 0o600)
            self.assertEqual(results[8]["sha256"], hashlib.sha256(b"pdf").hexdigest())

    def test_c2_readonly_cdp_allowlist_blocks_mutation(self) -> None:
        session = Mock()
        session.send.return_value = {"currentIndex": 0, "entries": []}
        result = BrowserExecutor._readonly_cdp_send(session, "Page.getNavigationHistory")
        self.assertEqual(result["currentIndex"], 0)
        session.send.assert_called_once_with("Page.getNavigationHistory")
        with self.assertRaises(CapabilityError):
            BrowserExecutor._readonly_cdp_send(session, "Runtime.evaluate")

    def test_inspect_failure_uses_inspect_failure_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            job_id = jobs.submit(JobSpec(task_type=TaskType.INSPECT, url="data:text/plain,x"))
            with (
                patch.object(BrowserExecutor, "_playwright_available", return_value=True),
                patch.object(BrowserExecutor, "_run_playwright", side_effect=RuntimeError("inspect boom")),
            ):
                self.assertTrue(Worker(paths, db).once())
            row = jobs.get(job_id)
            self.assertEqual(row["state"], JobState.FAILED.value)
            self.assertEqual(row["failure_class"], "INSPECT_FAILED")

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

            def slow_fetch(_: str, __: JobSpec) -> dict[str, object]:
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
