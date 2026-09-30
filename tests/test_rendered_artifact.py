from __future__ import annotations

import hashlib
import importlib.resources
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.executor import BrowserExecutor
from browser_plane.models import JobSpec, TaskType


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


class RenderedArtifactTests(unittest.TestCase):
    def test_capability_manifest_advertises_rendered_dom_and_wechat_consumer(self) -> None:
        resource = importlib.resources.files("browser_plane").joinpath("capabilities.json")
        manifest = json.loads(resource.read_text(encoding="utf-8"))
        self.assertTrue(manifest["capabilities"]["c1_rendered_dom_artifact"])
        self.assertEqual(manifest["capabilities"]["c1_rendered_dom_artifact_max_bytes"], 10_000_000)
        consumer = manifest["discovery"]["specialized_consumers"]["wechat_mp_archive"]
        self.assertEqual(consumer["trigger_host"], "mp.weixin.qq.com")
        self.assertEqual(consumer["repo"], "stanleyrprose/wechat-mp-archive")

    def test_c1_rendered_html_artifact_is_private_and_integrity_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            executor = BrowserExecutor(paths, db)
            html = "<!doctype html><html><body><h1>rendered</h1></body></html>"
            payload = html.encode("utf-8")

            result = executor._persist_rendered_html("job-c1-artifact", html)

            artifact = Path(str(result["artifact_path"]))
            self.assertEqual(artifact.name, "rendered.html")
            self.assertEqual(artifact.read_bytes(), payload)
            self.assertEqual(result["body_bytes"], len(payload))
            self.assertEqual(result["content_type"], "text/html; charset=utf-8")
            self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(artifact.parent.stat().st_mode), 0o700)

    def test_lightpanda_c1_persists_full_rendered_html_for_provider_reuse(self) -> None:
        class FakeProc:
            pid = 43210
            returncode = 0

            def communicate(self, timeout=None):
                payload = {
                    "http_status": 200,
                    "url": "https://example.com",
                    "content": "<!doctype html><html><head><title>x</title></head><body><h1>full rendered tender</h1></body></html>",
                    "headers": [{"name": "content-type", "value": "text/html; charset=utf-8"}],
                }
                return json.dumps(payload), ""

            def poll(self):
                return 0

            def terminate(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            executor = BrowserExecutor(paths, db)
            executor.processes.register = Mock(return_value="proc-1")
            executor.processes.mark_closed = Mock(return_value=True)
            executor.leases.acquire_control = Mock(return_value=1)
            executor.leases.release_control = Mock(return_value=True)
            executor.jobs.get = Mock(return_value={"state": "RUNNING"})
            spec = JobSpec(task_type=TaskType.AUTOMATE, url="https://example.com", max_run_sec=30)

            with (
                patch.object(BrowserExecutor, "_lightpanda_binary", return_value=Path("/fake/lightpanda")),
                patch("browser_plane.executor.subprocess.Popen", return_value=FakeProc()),
            ):
                result = executor._run_lightpanda_fetch("job-lightpanda-artifact", spec)

            artifact = Path(str(result["artifact_path"]))
            self.assertTrue(artifact.is_file())
            self.assertIn(b"full rendered tender", artifact.read_bytes())
            self.assertEqual(result["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(result["body_bytes"], len(artifact.read_bytes()))
            self.assertEqual(result["content_type"], "text/html; charset=utf-8")

    def test_c1_oversized_rendered_html_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            executor = BrowserExecutor(paths, db)
            with patch("browser_plane.executor.MAX_RENDERED_ARTIFACT_BYTES", 8):
                result = executor._persist_rendered_html("job-c1-oversized", "123456789")

            self.assertNotIn("artifact_path", result)
            self.assertEqual(result["body_bytes"], 9)
            self.assertEqual(result["artifact_omitted_reason"], "RENDERED_HTML_EXCEEDS_10MB_LIMIT")
            self.assertFalse((paths.evidence_dir / "job-c1-oversized" / "rendered.html").exists())


if __name__ == "__main__":
    unittest.main()
