from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from browser_plane.provider_agent import ProviderAgentError, package_success


URL = "https://example.com/"


def claim(*, capability: str, max_bytes: int) -> dict:
    tool = {
        "C0_FETCH": "browser_fetch",
        "C1_RENDER": "browser_render",
    }[capability]
    return {
        "provider_request_id": "request-1",
        "provider_attempt_id": "attempt-1",
        "claim_token": "[REDACTED_SECRET]",
        "request": {
            "capability": capability,
            "mcp_tool": tool,
            "max_bytes": max_bytes,
            "request_sha256": "request-sha-test",
        },
    }


def job_payload(result: dict) -> dict:
    return {
        "ok": True,
        "structured_content": {
            "job_id": "browser-job-1",
            "state": "SUCCEEDED",
            "result": result,
        },
    }


class ProviderResultBudgetTests(unittest.TestCase):
    def test_c0_rejects_raw_artifact_above_request_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = b"0123456789"
            path = Path(tmp) / "response.html"
            path.write_bytes(raw)
            result = {
                "url": URL,
                "status": 200,
                "content_type": "text/html",
                "body_bytes": len(raw),
                "artifact_path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            with self.assertRaisesRegex(ProviderAgentError, "request max_bytes"):
                package_success(claim(capability="C0_FETCH", max_bytes=len(raw) - 1), job_payload(result))

    def test_c1_rejects_packaged_json_above_request_budget(self) -> None:
        result = {"url": URL, "status": 200, "text_excerpt": "x" * 64}
        with self.assertRaisesRegex(ProviderAgentError, "request max_bytes"):
            package_success(claim(capability="C1_RENDER", max_bytes=8), job_payload(result))


if __name__ == "__main__":
    unittest.main()
