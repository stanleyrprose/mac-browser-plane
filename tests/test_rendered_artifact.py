from __future__ import annotations

import hashlib
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.executor import BrowserExecutor


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
