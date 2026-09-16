from __future__ import annotations

import unittest

from browser_plane.content_quality import (
    C1ContentQualityError,
    C1_CONTENT_QUALITY_GATE,
    c1_content_quality_metadata,
    require_nonempty_c1_body,
    wait_for_sync_c1_content,
)


class _HydratingSyncPage:
    def __init__(self, bodies: list[str]) -> None:
        self.bodies = bodies
        self.index = 0
        self.waits: list[float] = []

    def content(self) -> str:
        state = min(self.index, len(self.bodies) - 1)
        return f"<html><body>{self.bodies[state]}</body></html>"

    def evaluate(self, _expression: str) -> str:
        state = min(self.index, len(self.bodies) - 1)
        value = self.bodies[state]
        self.index += 1
        return value

    def wait_for_timeout(self, milliseconds: float) -> None:
        self.waits.append(milliseconds)


class C1ContentQualityTests(unittest.TestCase):
    def test_require_nonempty_body_rejects_empty_shell(self) -> None:
        with self.assertRaisesRegex(C1ContentQualityError, "content quality gate failed"):
            require_nonempty_c1_body("   \n", engine="lightpanda")

    def test_metadata_is_consistent_for_all_c1_engines(self) -> None:
        metadata = c1_content_quality_metadata(" useful content ", wait_ms=123)
        self.assertEqual(metadata["content_ready_wait_ms"], 123)
        self.assertEqual(
            metadata["content_quality"],
            {
                "status": "PASS",
                "gate": C1_CONTENT_QUALITY_GATE,
                "text_chars": 14,
            },
        )

    def test_sync_gate_allows_bounded_hydration(self) -> None:
        page = _HydratingSyncPage(["", "ready business content"])
        html, body_text, wait_ms = wait_for_sync_c1_content(
            page,
            engine="chrome",
            max_wait_sec=1.0,
            poll_interval_sec=0.0,
        )
        self.assertIn("ready business content", html)
        self.assertEqual(body_text, "ready business content")
        self.assertGreaterEqual(wait_ms, 0)
        self.assertEqual(page.waits, [0.0])

    def test_sync_gate_fails_closed_when_body_stays_empty(self) -> None:
        with self.assertRaisesRegex(C1ContentQualityError, "rendered body remained empty"):
            wait_for_sync_c1_content(
                _HydratingSyncPage([""]),
                engine="camoufox",
                max_wait_sec=0.0,
                poll_interval_sec=0.0,
            )


if __name__ == "__main__":
    unittest.main()
