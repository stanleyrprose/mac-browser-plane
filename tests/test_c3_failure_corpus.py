from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from browser_plane.c3_failure_corpus import C3FailureCorpus, classify_failure
from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.executor import BrowserExecutor
from browser_plane.models import JobSpec, ProfileMode, TaskType


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


class FakeBody:
    def inner_text(self, *, timeout: int) -> str:
        return "Public page body with PRIVATE_TYPED_TEXT reflected"

    def aria_snapshot(self, *, timeout: int, depth: int, mode: str) -> str:
        return '- button "Activate"\n- text: PRIVATE_TYPED_TEXT reflected'


class FailingLocator:
    def click(self, *, timeout: int, force: bool) -> None:
        raise TimeoutError("locator click timeout")


class FakePage:
    url = "https://example.com/path?q=private-value#fragment"

    def title(self) -> str:
        return "Example Page"

    def locator(self, selector: str):
        if selector == "body":
            return FakeBody()
        return FailingLocator()


class C3FailureCorpusTests(unittest.TestCase):
    def test_failure_classification_is_observational(self) -> None:
        self.assertEqual(classify_failure(TimeoutError("waiting for locator")), "ACTION_TIMEOUT")
        self.assertEqual(
            classify_failure(RuntimeError("strict mode violation: locator resolved to 2 elements")),
            "TARGET_AMBIGUOUS",
        )
        self.assertEqual(classify_failure(RuntimeError("frame was detached")), "FRAME_DETACHED")

    def test_public_failure_capture_is_bounded_and_omits_typed_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            spec = JobSpec(
                task_type=TaskType.USE,
                url="https://example.com/path?q=job-private-value",
                actions=(
                    {
                        "action": "type",
                        "selector": "#field",
                        "text": "PRIVATE_TYPED_TEXT",
                    },
                ),
            )
            job_id = jobs.submit(spec)
            corpus = C3FailureCorpus(paths, db)
            record = corpus.record_action_failure(
                page=FakePage(),
                job_id=job_id,
                browser_engine="chrome",
                step=1,
                action=spec.actions[0],
                exc=TimeoutError("locator timeout"),
            )

            self.assertEqual(stat.S_IMODE(corpus.path.stat().st_mode), 0o600)
            raw = corpus.path.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_TYPED_TEXT", raw)
            self.assertNotIn("?q=private-value", raw)
            self.assertEqual(record["page"]["url"], "https://example.com/path")
            self.assertEqual(record["page"]["content_capture"], "bounded_public_context")
            self.assertEqual(record["action"]["typed_chars"], len("PRIVATE_TYPED_TEXT"))
            self.assertNotIn("text", record["action"])

    def test_authenticated_profile_captures_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            spec = JobSpec(
                task_type=TaskType.USE,
                url="https://example.com/private",
                profile="authenticated-work",
                profile_mode=ProfileMode.EXCLUSIVE_PERSISTENT,
                actions=({"action": "click", "role": "button", "name": "Continue"},),
            )
            job_id = jobs.submit(spec)
            corpus = C3FailureCorpus(paths, db)
            record = corpus.record_action_failure(
                page=FakePage(),
                job_id=job_id,
                browser_engine="chrome",
                step=1,
                action=spec.actions[0],
                exc=RuntimeError("boom"),
            )

            self.assertEqual(record["page"]["content_capture"], "metadata_only")
            self.assertNotIn("text_excerpt", record["page"])
            self.assertNotIn("aria_snapshot", record["page"])

    def test_c3_action_failure_is_automatically_added_to_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, jobs = make_runtime(tmp)
            spec = JobSpec(
                task_type=TaskType.USE,
                url="https://example.com",
                actions=({"action": "click", "selector": "#missing", "timeout_ms": 50},),
            )
            job_id = jobs.submit(spec)
            executor = BrowserExecutor(paths, db)

            with self.assertRaisesRegex(RuntimeError, "browser action 1 .* failed"):
                executor._run_browser_actions(FakePage(), job_id, spec.actions, browser_engine="chrome")

            summary = executor.c3_failures.summary()
            self.assertEqual(summary["total_failures"], 1)
            self.assertEqual(summary["by_failure_class"], {"ACTION_TIMEOUT": 1})
            self.assertEqual(summary["by_action"], {"click": 1})
            recent = executor.c3_failures.recent(1)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["browser_engine"], "chrome")
            self.assertEqual(recent[0]["step"], 1)

    def test_corrupt_line_does_not_break_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, db, _ = make_runtime(tmp)
            corpus = C3FailureCorpus(paths, db)
            corpus.path.write_text(
                "not-json\n"
                + json.dumps({"observed_failure_class": "ACTION_ERROR", "action": {"action": "click"}})
                + "\n",
                encoding="utf-8",
            )
            corpus.path.chmod(0o600)
            summary = corpus.summary()
            self.assertEqual(summary["total_failures"], 1)
            self.assertEqual(summary["by_failure_class"], {"ACTION_ERROR": 1})


if __name__ == "__main__":
    unittest.main()
