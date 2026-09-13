from __future__ import annotations

import json

from browser_plane.provider_agent import package_success


def test_non_c0_evidence_removes_local_paths() -> None:
    claim = {
        "provider_request_id": "request-1",
        "provider_attempt_id": "attempt-1",
        "claim_token": "x",
        "request": {
            "capability": "C2_INSPECT",
            "mcp_tool": "browser_inspect",
            "max_bytes": 1_000_000,
            "request_sha256": "0" * 64,
        },
    }
    payload = {
        "ok": True,
        "structured_content": {
            "job_id": "browser-job-1",
            "state": "SUCCEEDED",
            "result": {
                "engine": "c2-readonly-inspect",
                "url": "https://example.invalid/",
                "status": 200,
                "screenshot": "/var/tmp/local-screenshot.png",
                "actions": [
                    {"action": "screenshot", "path": "/var/tmp/local-shot.png"},
                    {"action": "snapshot", "aria_snapshot": "heading"},
                ],
            },
        },
    }

    wire = package_success(claim, payload)
    _manifest, artifact = wire.split(b"\n", 1)
    result = json.loads(artifact)["result"]

    assert "screenshot" not in result
    assert "path" not in result["actions"][0]
    assert result["actions"][1]["aria_snapshot"] == "heading"
