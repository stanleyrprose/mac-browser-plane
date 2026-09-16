from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_plane.config import RuntimePaths
from browser_plane.db import RuntimeDB
from browser_plane.network_trace import TraceController, _addon_source, build_command, validate_host


def make_runtime(tmp: str) -> tuple[RuntimePaths, RuntimeDB]:
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
    return paths, db


class NetworkTraceTests(unittest.TestCase):
    def test_host_validation_rejects_wildcards_and_urls(self) -> None:
        self.assertEqual(validate_host("Example.COM."), "example.com")
        with self.assertRaises(ValueError):
            validate_host("0.0.0.0")
        with self.assertRaises(ValueError):
            validate_host("https://example.com")
        with self.assertRaises(ValueError):
            validate_host("*.example.com")

    def test_command_is_loopback_and_host_scoped(self) -> None:
        command = build_command("/opt/homebrew/bin/mitmdump", host="api.example.com", port=18080, addon_path=Path("/tmp/addon.py"))
        self.assertIn("127.0.0.1", command)
        self.assertIn("18080", command)
        allow_value = next(value for value in command if value.startswith("allow_hosts="))
        self.assertIn("api\\.example\\.com", allow_value)

    def test_addon_only_emits_bounded_metadata(self) -> None:
        source = _addon_source("example.com", Path("/tmp/flows.jsonl"))
        self.assertIn('"path": path', source)
        self.assertIn('"response_size"', source)
        self.assertNotIn("req.text", source)
        self.assertNotIn("resp.text", source)
        self.assertNotIn("req.headers", source)
        self.assertNotIn("split.query", source)

    def test_doctor_reports_optional_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db = make_runtime(tmp)
            controller = TraceController(paths, db)
            with patch("browser_plane.network_trace.find_mitmdump", return_value=None):
                self.assertEqual(controller.doctor()["status"], "UNAVAILABLE")
            with patch("browser_plane.network_trace.find_mitmdump", return_value="/opt/homebrew/bin/mitmdump"):
                report = controller.doctor()
                self.assertEqual(report["status"], "READY")
                self.assertTrue(report["default_off"])
                self.assertTrue(report["loopback_only"])

    def test_summary_is_bounded_and_structured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db = make_runtime(tmp)
            controller = TraceController(paths, db)
            trace_dir = paths.evidence_dir / "network-trace" / "sample"
            trace_dir.mkdir(parents=True)
            summary_path = trace_dir / "flows.jsonl"
            summary_path.write_text(
                json.dumps({"timestamp": "2026-09-16T00:00:00Z", "method": "GET", "scheme": "http", "host": "example.com", "path": "/api/items", "status": 200, "content_type": "application/json", "response_size": 12, "api_like": True}) + "\n",
                encoding="utf-8",
            )
            state = {"trace_id": "sample", "host": "example.com", "browser_process_id": "missing", "summary_path": str(summary_path)}
            report = controller.summary(state=state)
            self.assertEqual(report["flow_count"], 1)
            self.assertEqual(report["api_like_count"], 1)
            self.assertEqual(report["flows"][0]["path"], "/api/items")


if __name__ == "__main__":
    unittest.main()
