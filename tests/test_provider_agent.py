from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from browser_plane.provider_agent import (
    CAPABILITY_TOOL_MAP,
    ProviderAgentError,
    SshProviderTransport,
    canonical_json,
    mcp_arguments,
    package_success,
    request_sha256,
    run_once,
    validate_request,
)

URL = "https://www.industrymsme.gov.mm/announcements"


def contract() -> dict:
    return {
        "schema_version": 1,
        "provider_id": "mac-mm-01",
        "transport": "pull_ssh_v1",
        "source_policies": {
            "S38": {
                "enabled": True,
                "source_policy_version": 1,
                "allowed_capabilities": list(CAPABILITY_TOOL_MAP),
                "targets": {
                    "LISTING": {
                        "capabilities": list(CAPABILITY_TOOL_MAP),
                        "exact_urls": [URL],
                        "max_bytes": 1_000_000,
                        "max_run_seconds": 180,
                    }
                },
            }
        },
    }


def request(capability: str, interaction_plan=None) -> dict:
    provider_request_id = str(uuid.uuid4())
    value = {
        "contract_version": 1,
        "provider_request_id": provider_request_id,
        "provider_id": "mac-mm-01",
        "signalforge_job_id": str(uuid.uuid4()),
        "acquisition_request_id": str(uuid.uuid4()),
        "acquisition_attempt_id": str(uuid.uuid4()),
        "source_id": "S38",
        "source_policy_version": 1,
        "capability": capability,
        "mcp_tool": CAPABILITY_TOOL_MAP[capability],
        "target_role": "LISTING",
        "requested_url": URL,
        "max_bytes": 1_000_000,
        "max_run_seconds": 60,
        "requested_at": "2026-09-08T06:00:00Z",
        "expires_at": "2026-09-08T06:02:00Z",
        "idempotency_key": f"sf-provider:{provider_request_id}",
        "interaction_plan": interaction_plan,
    }
    value["request_sha256"] = request_sha256(value)
    return value


def claim(req: dict) -> dict:
    return {
        "status": "CLAIMED",
        "provider_id": "mac-mm-01",
        "provider_request_id": req["provider_request_id"],
        "provider_attempt_id": str(uuid.uuid4()),
        "claim_token": "claim-secret",
        "claim_expires_at": "2026-09-08T06:01:00Z",
        "request": req,
    }


class FakeTransport:
    def __init__(self, claim_value: dict):
        self.claim_value = claim_value
        self.submitted: list[bytes] = []
        self.failed: list[dict] = []

    def claim(self):
        return self.claim_value

    def submit(self, payload: bytes):
        self.submitted.append(payload)
        return {"status": "ACCEPTED"}

    def fail(self, payload: dict):
        self.failed.append(payload)
        return {"status": "FAILED_ACCEPTED"}


class FakeInvoker:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, arguments: dict):
        self.calls.append((tool, arguments))
        return self.payload


def job_payload(result: dict, job_id="browser-job-1") -> dict:
    return {
        "ok": True,
        "tool": "x",
        "is_error": False,
        "structured_content": {
            "job_id": job_id,
            "state": "SUCCEEDED",
            "created_at": "x",
            "started_at": "x",
            "finished_at": "x",
            "failure_class": None,
            "partial_effect_possible": False,
            "result": result,
        },
    }


class ProviderAgentValidationTests(unittest.TestCase):
    def test_c0_c1_c2_validate_and_map_to_actual_mcp_tools(self):
        for capability in ("C0_FETCH", "C1_RENDER", "C2_INSPECT"):
            req = request(capability)
            self.assertIs(validate_request(req, contract()), req)
            args = mcp_arguments(req)
            self.assertEqual(args["url"], URL)
            self.assertEqual(req["mcp_tool"], CAPABILITY_TOOL_MAP[capability])

    def test_c3_plan_matches_pic_subset_and_real_mcp_action_names(self):
        plan = {
            "side_effect_class": "READ_ONLY_NAVIGATION",
            "retry_safe": False,
            "steps": [
                {"action": "snapshot"},
                {"action": "click", "text_target": "Next"},
                {"action": "press", "key": "Escape"},
                {"action": "screenshot"},
            ],
        }
        req = request("C3_BROWSER_USE", plan)
        validate_request(req, contract())
        self.assertEqual(mcp_arguments(req)["actions"], plan["steps"])

    def test_c3_rejects_scroll_download_and_arbitrary_execution(self):
        for step in (
            {"action": "scroll"},
            {"action": "download", "selector": "a"},
            {"action": "click", "selector": "a", "javascript": "x"},
        ):
            req = request("C3_BROWSER_USE", {"side_effect_class": "READ_ONLY_NAVIGATION", "retry_safe": False, "steps": [step]})
            with self.assertRaises(ProviderAgentError):
                validate_request(req, contract())

    def test_rejects_tamper_wrong_host_capability_and_c0_oversize(self):
        req = request("C0_FETCH")
        req["requested_url"] = "https://example.com/"
        req["request_sha256"] = request_sha256(req)
        with self.assertRaisesRegex(ProviderAgentError, "approved exact target"):
            validate_request(req, contract())

        req = request("C1_RENDER")
        req["mcp_tool"] = "browser_fetch"
        req["request_sha256"] = request_sha256(req)
        with self.assertRaisesRegex(ProviderAgentError, "capability/tool"):
            validate_request(req, contract())

        req = request("C0_FETCH")
        req["max_bytes"] = 1_000_001
        req["request_sha256"] = request_sha256(req)
        local = contract()
        local["source_policies"]["S38"]["targets"]["LISTING"]["max_bytes"] = 2_000_000
        with self.assertRaisesRegex(ProviderAgentError, "current Browser Plane C0"):
            validate_request(req, local)


class ProviderAgentPackagingTests(unittest.TestCase):
    def test_c0_packages_raw_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = b"<html>raw</html>"
            path = Path(tmp) / "response.html"
            path.write_bytes(raw)
            req = request("C0_FETCH")
            c = claim(req)
            result = {
                "engine": "c0-fetch",
                "url": URL,
                "status": 200,
                "content_type": "text/html; charset=utf-8",
                "body_bytes": len(raw),
                "artifact_path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            wire = package_success(c, job_payload(result))
            line, artifact = wire.split(b"\n", 1)
            manifest = json.loads(line)
            self.assertEqual(artifact, raw)
            self.assertEqual(manifest["media_type"], "text/html")
            self.assertEqual(manifest["artifact_sha256"], hashlib.sha256(raw).hexdigest())

    def test_c1_c2_c3_package_canonical_json_evidence(self):
        for capability, engine in (
            ("C1_RENDER", "c1-playwright"),
            ("C2_INSPECT", "c2-readonly-inspect"),
            ("C3_BROWSER_USE", "c3-browser-use"),
        ):
            plan = None
            if capability == "C3_BROWSER_USE":
                plan = {"side_effect_class": "READ_ONLY_NAVIGATION", "retry_safe": False, "steps": [{"action": "snapshot"}]}
            req = request(capability, plan)
            c = claim(req)
            result = {"engine": engine, "url": URL, "status": 200, "title": "x", "text_excerpt": "hello"}
            wire = package_success(c, job_payload(result))
            line, artifact = wire.split(b"\n", 1)
            manifest = json.loads(line)
            self.assertEqual(manifest["media_type"], "application/json")
            parsed = json.loads(artifact)
            self.assertEqual(parsed["result"]["engine"], engine)


class ProviderAgentRunTests(unittest.TestCase):
    def test_no_work_does_not_invoke_mcp(self):
        transport = FakeTransport({"status": "NO_WORK"})
        invoker = FakeInvoker({})
        result = run_once(transport=transport, invoker=invoker, contract=contract())
        self.assertEqual(result["status"], "NO_WORK")
        self.assertEqual(invoker.calls, [])

    def test_all_capabilities_route_to_expected_tool(self):
        for capability in CAPABILITY_TOOL_MAP:
            plan = None
            if capability == "C3_BROWSER_USE":
                plan = {"side_effect_class": "READ_ONLY_NAVIGATION", "retry_safe": False, "steps": [{"action": "snapshot"}]}
            req = request(capability, plan)
            transport = FakeTransport(claim(req))
            if capability == "C0_FETCH":
                with tempfile.TemporaryDirectory() as tmp:
                    raw = b"x"
                    p = Path(tmp) / "x.bin"; p.write_bytes(raw)
                    payload = job_payload({"engine": "c0-fetch", "url": URL, "status": 200, "content_type": "text/html", "body_bytes": 1, "artifact_path": str(p), "sha256": hashlib.sha256(raw).hexdigest()})
                    invoker = FakeInvoker(payload)
                    result = run_once(transport=transport, invoker=invoker, contract=contract())
            else:
                invoker = FakeInvoker(job_payload({"engine": "x", "url": URL, "status": 200}))
                result = run_once(transport=transport, invoker=invoker, contract=contract())
            self.assertEqual(result["status"], "ACCEPTED")
            self.assertEqual(invoker.calls[0][0], CAPABILITY_TOOL_MAP[capability])
            self.assertEqual(len(transport.submitted), 1)

    def test_invalid_claim_fails_before_mcp_and_reports_contract_failure(self):
        req = request("C0_FETCH")
        req["requested_url"] = "https://example.com/"
        req["request_sha256"] = request_sha256(req)
        transport = FakeTransport(claim(req))
        invoker = FakeInvoker({})
        with self.assertRaises(ProviderAgentError):
            run_once(transport=transport, invoker=invoker, contract=contract())
        self.assertEqual(invoker.calls, [])
        self.assertEqual(transport.failed[0]["failure_class"], "PROVIDER_CONTRACT_MISMATCH")

    def test_mcp_failure_reports_provider_not_ready(self):
        req = request("C1_RENDER")
        transport = FakeTransport(claim(req))

        class BrokenInvoker:
            def call(self, tool, arguments):
                raise RuntimeError("mcp unavailable")

        with self.assertRaises(RuntimeError):
            run_once(transport=transport, invoker=BrokenInvoker(), contract=contract())
        self.assertEqual(transport.failed[0]["failure_class"], "PROVIDER_NOT_READY")


class SshProviderTransportTests(unittest.TestCase):
    def test_argv_is_closed_and_never_invokes_shell(self):
        transport = SshProviderTransport("sf-provider-bangkok", "/tmp/key")
        argv = transport._argv("provider-claim-v1")
        self.assertEqual(argv[0], "/usr/bin/ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ClearAllForwardings=yes", argv)
        self.assertEqual(argv[-2:], ["sf-provider-bangkok", "provider-claim-v1"])
        self.assertNotIn("sh", argv)
        self.assertNotIn("bash", argv)

        completed = type("Done", (), {"returncode": 0, "stdout": b'{"status":"NO_WORK"}', "stderr": b""})()
        with patch("browser_plane.provider_agent.subprocess.run", return_value=completed) as run:
            self.assertEqual(transport.claim()["status"], "NO_WORK")
            self.assertFalse(run.call_args.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
