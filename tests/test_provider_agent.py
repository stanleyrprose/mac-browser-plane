from __future__ import annotations

import hashlib
import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta

from browser_plane.provider_agent import ProviderAgentError, build_completion, run_once, validate_claim

NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
URL = "https://www.industrymsme.gov.mm/announcements"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def contract() -> dict:
    caps = ["C0_FETCH", "C1_RENDER", "C2_INSPECT", "C3_BROWSER_USE"]
    return {
        "schema_version": 1,
        "provider_id": "mac-mm-01",
        "source_policies": {
            "S38": {
                "enabled": True,
                "source_policy_version": 1,
                "allowed_capabilities": caps,
                "targets": {"LISTING": {"capabilities": caps, "exact_urls": [URL]}},
            }
        },
    }


def claim(capability: str = "C0_FETCH", *, interaction_plan=None) -> dict:
    request_id = str(uuid.uuid4())
    tool = {
        "C0_FETCH": "browser_fetch",
        "C1_RENDER": "browser_render",
        "C2_INSPECT": "browser_inspect",
        "C3_BROWSER_USE": "browser_use",
    }[capability]
    request = {
        "contract_version": 1,
        "provider_request_id": request_id,
        "provider_id": "mac-mm-01",
        "signalforge_job_id": str(uuid.uuid4()),
        "acquisition_request_id": str(uuid.uuid4()),
        "acquisition_attempt_id": str(uuid.uuid4()),
        "source_id": "S38",
        "source_policy_version": 1,
        "capability": capability,
        "mcp_tool": tool,
        "target_role": "LISTING",
        "requested_url": URL,
        "max_bytes": 1_000_000,
        "max_run_seconds": 45,
        "requested_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
        "idempotency_key": f"sf-provider:{request_id}",
        "interaction_plan": interaction_plan,
    }
    request["request_sha256"] = hashlib.sha256(canonical(request)).hexdigest()
    return {
        "status": "CLAIMED",
        "provider_id": "mac-mm-01",
        "provider_request_id": request_id,
        "provider_attempt_id": str(uuid.uuid4()),
        "claim_token": "x",
        "claim_expires_at": (NOW + timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
        "request": request,
    }


class FakeDispatcher:
    def __init__(self, claimed: dict) -> None:
        self.claimed = claimed
        self.calls: list[tuple[str, dict | None]] = []

    def call(self, command: str, payload=None):
        self.calls.append((command, payload))
        if command == "provider-claim-v1":
            return self.claimed
        if command == "provider-complete-v1":
            return {"status": "ACCEPTED"}
        if command == "provider-fail-v1":
            return {"status": "FAILED_ACCEPTED"}
        raise AssertionError(command)


class ProviderAgentTests(unittest.TestCase):
    def test_maps_c0_c1_c2_to_local_mcp(self) -> None:
        for capability, expected_tool in (
            ("C0_FETCH", "browser_fetch"),
            ("C1_RENDER", "browser_render"),
            ("C2_INSPECT", "browser_inspect"),
        ):
            validated = validate_claim(claim(capability), contract(), now=NOW)
            self.assertEqual(validated["tool"], expected_tool)
            self.assertEqual(validated["arguments"]["url"], URL)

    def test_maps_bounded_c3_plan_to_browser_use(self) -> None:
        plan = {
            "side_effect_class": "READ_ONLY_NAVIGATION",
            "retry_safe": False,
            "steps": [
                {"action": "snapshot"},
                {"action": "click", "selector": "a.next"},
                {"action": "wait", "selector": "body"},
                {"action": "screenshot"},
            ],
        }
        validated = validate_claim(claim("C3_BROWSER_USE", interaction_plan=plan), contract(), now=NOW)
        self.assertEqual(validated["tool"], "browser_use")
        self.assertEqual(validated["arguments"]["actions"], plan["steps"])
        self.assertEqual(validated["arguments"]["profile"], "public-research")
        self.assertEqual(validated["arguments"]["profile_mode"], "ephemeral")

    def test_rejects_tampering_and_unsupported_scroll(self) -> None:
        tampered = claim()
        tampered["request"]["requested_url"] = "https://example.com/"
        with self.assertRaisesRegex(ProviderAgentError, "SHA-256"):
            validate_claim(tampered, contract(), now=NOW)

        c3 = claim(
            "C3_BROWSER_USE",
            interaction_plan={
                "side_effect_class": "READ_ONLY_NAVIGATION",
                "retry_safe": True,
                "steps": [{"action": "scroll"}],
            },
        )
        with self.assertRaisesRegex(ProviderAgentError, "not supported"):
            validate_claim(c3, contract(), now=NOW)

    def test_completion_hashes_exact_mcp_result(self) -> None:
        current = claim()
        result = {
            "ok": True,
            "tool": "browser_fetch",
            "is_error": False,
            "structured_content": {"job_id": "browser-job-1", "state": "SUCCEEDED", "result": {"status": 200}},
        }
        payload = build_completion(current, result)
        self.assertEqual(payload["browser_job_id"], "browser-job-1")
        self.assertEqual(payload["result_sha256"], hashlib.sha256(canonical(result)).hexdigest())

    def test_run_once_claims_executes_and_completes(self) -> None:
        current = claim("C2_INSPECT")
        dispatcher = FakeDispatcher(current)
        observed: list[tuple[str, dict]] = []

        def caller(tool: str, arguments: dict):
            observed.append((tool, arguments))
            return {
                "ok": True,
                "tool": tool,
                "is_error": False,
                "structured_content": {"job_id": "browser-job-2", "state": "SUCCEEDED", "result": {"status": 200}},
            }

        output = run_once(contract(), dispatcher, mcp_caller=caller, now=NOW)
        self.assertEqual(output["status"], "COMPLETED")
        self.assertEqual(observed[0][0], "browser_inspect")
        self.assertEqual([item[0] for item in dispatcher.calls], ["provider-claim-v1", "provider-complete-v1"])


if __name__ == "__main__":
    unittest.main()
