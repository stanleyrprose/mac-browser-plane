from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from browser_plane.acquisition_router import (
    acquisition_outcome,
    c0_render_trigger,
)
from browser_plane.models import JobState


def _job(
    *,
    status: int = 200,
    content_type: str = "text/html",
    text_excerpt: str = "",
    transport_route: dict | None = None,
    artifact_path: str | None = None,
    state: str = JobState.SUCCEEDED.value,
) -> dict:
    result = {
        "engine": "c0-fetch",
        "status": status,
        "content_type": content_type,
        "text_excerpt": text_excerpt,
        "transport": "system_curl",
        "transport_route": transport_route or {
            "selected": "system_curl",
            "fallback_attempted": False,
        },
    }
    if artifact_path:
        result["artifact_path"] = artifact_path
    return {
        "job_id": "job-1",
        "state": state,
        "result": result,
    }


class AcquisitionRouterTests(unittest.TestCase):
    def test_static_html_stays_c0(self) -> None:
        body = "<html><body><h1>Tender Notice</h1><p>" + ("details " * 80) + "</p></body></html>"
        self.assertIsNone(c0_render_trigger(_job(text_excerpt=body)))

    def test_plain_403_and_429_do_not_authorize_render(self) -> None:
        self.assertIsNone(c0_render_trigger(_job(status=403, text_excerpt="Forbidden")))
        self.assertIsNone(c0_render_trigger(_job(status=429, content_type="text/plain", text_excerpt="rate limited")))

    def test_explicit_challenge_authorizes_render_inside_acquire(self) -> None:
        route = {
            "selected": "system_curl",
            "fallback_attempted": True,
            "trigger": "cloudflare_challenge",
        }
        self.assertEqual(
            c0_render_trigger(_job(status=403, transport_route=route)),
            "cloudflare_challenge",
        )

    def test_curl_cffi_success_after_challenge_does_not_render_again(self) -> None:
        route = {
            "selected": "curl_cffi",
            "fallback_attempted": True,
            "trigger": "cloudflare_challenge",
            "direct_status": 403,
        }
        body = "<html><body><h1>Recovered content</h1><p>" + ("details " * 50) + "</p></body></html>"
        self.assertIsNone(
            c0_render_trigger(
                _job(
                    status=200,
                    text_excerpt=body,
                    transport_route=route,
                )
            )
        )

    def test_javascript_phrase_in_normal_article_does_not_trigger_render(self) -> None:
        body = (
            "<html><body><article><h1>Guide</h1><p>"
            + ("You can enable JavaScript in your browser settings. " * 20)
            + "</p></article></body></html>"
        )
        self.assertIsNone(c0_render_trigger(_job(text_excerpt=body)))

    def test_javascript_required_and_spa_shell_authorize_render(self) -> None:
        js_required = (
            "<html><body><noscript>Please enable JavaScript to continue.</noscript>"
            '<div id="root"></div><script src="/app.js"></script></body></html>'
        )
        self.assertEqual(c0_render_trigger(_job(text_excerpt=js_required)), "javascript_required")

        spa_shell = (
            '<html><body><div id="app"></div>'
            '<script src="/assets/index.js"></script></body></html>'
        )
        self.assertEqual(c0_render_trigger(_job(text_excerpt=spa_shell)), "spa_shell_low_text")

    def test_full_artifact_prevents_head_only_false_positive(self) -> None:
        body = (
            '<html><head><script>window.webpack={}</script></head><body>'
            + "<p>" + ("substantive public content " * 40) + "</p></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "response.html"
            path.write_text(body)
            job = _job(
                text_excerpt='<html><head><script>window.webpack={}</script></head>',
                artifact_path=str(path),
            )
            self.assertIsNone(c0_render_trigger(job))

    def test_non_html_and_execution_failure_stay_c0(self) -> None:
        self.assertIsNone(
            c0_render_trigger(
                _job(content_type="application/json", text_excerpt=json.dumps({"ok": True}))
            )
        )
        self.assertIsNone(
            c0_render_trigger(_job(state=JobState.FAILED.value, text_excerpt=""))
        )

    def test_acquisition_outcome_is_transport_independent(self) -> None:
        self.assertEqual(acquisition_outcome(_job(status=200)), "CONTENT_RETURNED")
        self.assertEqual(acquisition_outcome(_job(status=403)), "HTTP_RESPONSE_NOT_SUCCESS")
        self.assertEqual(
            acquisition_outcome(_job(state=JobState.FAILED.value)),
            "EXECUTION_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
