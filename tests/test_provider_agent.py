from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from browser_plane.provider_agent import (
    CAPABILITY_TOOL_MAP,
    ProviderAgentError,
    SshProviderTransport,
    _poll_delay,
    _provider_document_fetch,
    canonical_json,
    mcp_arguments,
    package_document_ocr_success,
    package_success,
    request_sha256,
    run_once,
    validate_request,
)

URL = "https://www.industrymsme.gov.mm/announcements"
NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)


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
        "claim_token": "[REDACTED_SECRET]",
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


def public_read_payload(result: dict, *, selected_capability: str = "C0_FETCH", job_id: str = "browser-job-1") -> dict:
    payload = job_payload(result, job_id=job_id)
    payload["structured_content"].update(
        {
            "acquisition_policy": "public_read_auto_v1",
            "acquisition_outcome": "CONTENT_RETURNED",
            "selected_capability": selected_capability,
            "attempts": (
                [
                    {
                        "capability": "C0_FETCH",
                        "job_id": f"{job_id}-c0",
                        "state": "SUCCEEDED",
                        "http_status": 200,
                        "engine": "c0-fetch",
                        "browser_engine": None,
                        "transport": "system_curl",
                    },
                    {
                        "capability": "C1_RENDER",
                        "job_id": job_id,
                        "state": "SUCCEEDED",
                        "http_status": result.get("status"),
                        "engine": result.get("engine"),
                        "browser_engine": result.get("browser_engine"),
                        "transport": result.get("transport"),
                    },
                ]
                if selected_capability == "C1_RENDER"
                else [
                    {
                        "capability": "C0_FETCH",
                        "job_id": job_id,
                        "state": "SUCCEEDED",
                        "http_status": result.get("status"),
                        "engine": result.get("engine"),
                        "browser_engine": result.get("browser_engine"),
                        "transport": result.get("transport"),
                    }
                ]
            ),
            "acquisition_route": {
                "policy": "public_read_auto_v1",
                "authorization": "explicit_browser_acquire_call",
                "c0_first": True,
                "render_fallback_authorized": True,
                "render_trigger": None if selected_capability == "C0_FETCH" else "spa_shell_low_text",
                "render_fallback_attempted": selected_capability == "C1_RENDER",
                "render_skipped_reason": None,
                "c2_authorized": False,
                "c3_authorized": False,
            },
        }
    )
    return payload


class ProviderAgentPollingTests(unittest.TestCase):
    def test_idle_poll_uses_configured_interval(self) -> None:
        self.assertEqual(_poll_delay({"status": "NO_WORK"}, 10.0), 10.0)
        self.assertEqual(_poll_delay({"status": "NO_WORK"}, 0.1), 1.0)

    def test_completed_work_drains_next_request_without_idle_sleep(self) -> None:
        self.assertEqual(_poll_delay({"status": "COMPLETED"}, 10.0), 0.0)
        self.assertEqual(_poll_delay({"status": "FAILED"}, 10.0), 0.0)


class ProviderAgentValidationTests(unittest.TestCase):
    def test_public_read_c0_c1_c2_validate_and_map_to_actual_mcp_tools(self):
        for capability in ("PUBLIC_READ_ACQUIRE", "C0_FETCH", "C1_RENDER", "C2_INSPECT"):
            req = request(capability)
            self.assertIs(validate_request(req, contract()), req)
            args = mcp_arguments(req)
            self.assertEqual(args["url"], URL)
            self.assertEqual(req["mcp_tool"], CAPABILITY_TOOL_MAP[capability])

    def test_public_read_arguments_preserve_total_remote_budget(self):
        req = request("PUBLIC_READ_ACQUIRE")
        args = mcp_arguments(req)
        self.assertEqual(args["url"], URL)
        self.assertEqual(args["queue_timeout_sec"], 20)
        self.assertEqual(args["fetch_max_run_sec"], 40)
        self.assertEqual(args["render_max_run_sec"], 60)
        self.assertEqual(args["client_timeout_sec"], 60)
        self.assertNotIn("max_run_sec", args)

    def test_document_ocr_validates_but_uses_composed_execution_path(self):
        req = request("DOCUMENT_OCR")
        self.assertIs(validate_request(req, contract()), req)
        self.assertEqual(req["mcp_tool"], "document_ocr")
        with self.assertRaisesRegex(ProviderAgentError, "composed fetch"):
            mcp_arguments(req)

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


class ProviderDocumentFetchTests(unittest.TestCase):
    def test_document_fetch_uses_pic_request_budget_above_public_c0_limit(self) -> None:
        pdf = b"%PDF-1.4\n" + (b"x" * 1_100_000)
        req = request("DOCUMENT_OCR")
        req["max_bytes"] = 2_000_000
        req["request_sha256"] = request_sha256(req)
        local = contract()
        local["source_policies"]["S38"]["targets"]["LISTING"]["max_bytes"] = 2_000_000

        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(argv, **_kwargs):
                output = Path(argv[argv.index("--output") + 1])
                output.write_bytes(pdf)
                self.assertEqual(argv[argv.index("--max-filesize") + 1], "2000000")
                return type(
                    "Done",
                    (),
                    {
                        "returncode": 0,
                        "stdout": f"200\n{URL}\napplication/pdf\n",
                        "stderr": "",
                    },
                )()

            with patch("browser_plane.provider_agent.RuntimePaths.discover") as discover, patch(
                "browser_plane.provider_agent.subprocess.run", side_effect=fake_run
            ):
                root = Path(tmp)
                from browser_plane.config import RuntimePaths

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
                discover.return_value = paths
                payload = _provider_document_fetch(req, local)

        result = payload["structured_content"]["result"]
        self.assertEqual(result["body_bytes"], len(pdf))
        self.assertGreater(result["body_bytes"], 1_000_000)
        self.assertEqual(result["provider_byte_budget"], 2_000_000)
        self.assertEqual(result["transport"], "system_curl")
        self.assertEqual(Path(result["artifact_path"]).name, "response.pdf")

    def test_document_fetch_rejects_redirect_outside_local_pic(self) -> None:
        pdf = b"%PDF-1.4\nfixture"
        req = request("DOCUMENT_OCR")
        local = contract()

        with tempfile.TemporaryDirectory() as tmp:
            def fake_run(argv, **_kwargs):
                output = Path(argv[argv.index("--output") + 1])
                output.write_bytes(pdf)
                return type(
                    "Done",
                    (),
                    {
                        "returncode": 0,
                        "stdout": "200\nhttps://example.com/escape.pdf\napplication/pdf\n",
                        "stderr": "",
                    },
                )()

            root = Path(tmp)
            from browser_plane.config import RuntimePaths

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
            with patch("browser_plane.provider_agent.subprocess.run", side_effect=fake_run):
                with self.assertRaisesRegex(ProviderAgentError, "not an approved exact target"):
                    _provider_document_fetch(req, local, paths=paths)


class ProviderAgentPackagingTests(unittest.TestCase):
    manifest_keys = {
        "contract_version",
        "provider_request_id",
        "provider_attempt_id",
        "claim_token",
        "browser_job_id",
        "request_sha256",
        "state",
        "mcp_tool",
        "final_url",
        "http_status",
        "media_type",
        "artifact_bytes",
        "artifact_sha256",
    }

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
            self.assertEqual(set(manifest), self.manifest_keys)

    def test_public_read_packages_selected_c0_or_c1_as_raw_html(self):
        for selected, engine in (("C0_FETCH", "c0-fetch"), ("C1_RENDER", "c1-lightpanda")):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as tmp:
                raw = f"<html>{selected}</html>".encode()
                path = Path(tmp) / "rendered.html"
                path.write_bytes(raw)
                req = request("PUBLIC_READ_ACQUIRE")
                c = claim(req)
                result = {
                    "engine": engine,
                    "browser_engine": "lightpanda" if selected == "C1_RENDER" else None,
                    "transport": "system_curl" if selected == "C0_FETCH" else None,
                    "transport_route": {"selected": "system_curl"} if selected == "C0_FETCH" else None,
                    "url": URL,
                    "status": 200,
                    "content_type": "text/html; charset=utf-8",
                    "body_bytes": len(raw),
                    "artifact_path": str(path),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                wire = package_success(c, public_read_payload(result, selected_capability=selected))
                line, artifact = wire.split(b"\n", 1)
                manifest = json.loads(line)
                self.assertEqual(artifact, raw)
                self.assertEqual(manifest["media_type"], "text/html")
                self.assertEqual(manifest["mcp_tool"], "browser_acquire")
                summary = manifest["route_summary"]
                self.assertEqual(set(manifest), self.manifest_keys | {"route_summary"})
                self.assertEqual(summary["schema_version"], 1)
                self.assertEqual(summary["policy"], "public_read_auto_v1")
                self.assertEqual(summary["selected_capability"], selected)
                self.assertEqual(summary["selected_engine"], engine)
                self.assertEqual(summary["attempt_count"], 2 if selected == "C1_RENDER" else 1)
                self.assertFalse(summary["c2_authorized"])
                self.assertFalse(summary["c3_authorized"])
                if selected == "C0_FETCH":
                    self.assertEqual(summary["selected_transport"], "system_curl")
                    self.assertFalse(summary["render_fallback_attempted"])
                else:
                    self.assertEqual(summary["selected_browser_engine"], "lightpanda")
                    self.assertEqual(summary["render_trigger"], "spa_shell_low_text")
                    self.assertTrue(summary["render_fallback_attempted"])

                serialized_summary = json.dumps(summary, sort_keys=True).lower()
                for forbidden in ("artifact_path", "url", "body", "headers", "cookies", "profile", "text"):
                    self.assertNotIn(f'"{forbidden}"', serialized_summary)

    def test_public_read_fails_closed_if_router_authorizes_outside_c0_c1(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = b"<html>unsafe</html>"
            path = Path(tmp) / "rendered.html"
            path.write_bytes(raw)
            req = request("PUBLIC_READ_ACQUIRE")
            c = claim(req)
            result = {
                "engine": "c1-lightpanda",
                "url": URL,
                "status": 200,
                "content_type": "text/html",
                "body_bytes": len(raw),
                "artifact_path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            payload = public_read_payload(result, selected_capability="C1_RENDER")
            payload["structured_content"]["acquisition_route"]["c2_authorized"] = True
            with self.assertRaisesRegex(ProviderAgentError, "authorization boundary"):
                package_success(c, payload)
            payload = public_read_payload(result, selected_capability="C1_RENDER")
            payload["structured_content"]["selected_capability"] = "C2_INSPECT"
            with self.assertRaisesRegex(ProviderAgentError, "outside C0/C1"):
                package_success(c, payload)

    def test_public_read_fails_closed_on_impossible_route_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = b"<html>route</html>"
            path = Path(tmp) / "rendered.html"
            path.write_bytes(raw)
            req = request("PUBLIC_READ_ACQUIRE")
            c = claim(req)
            result = {
                "engine": "c1-lightpanda",
                "browser_engine": "lightpanda",
                "url": URL,
                "status": 200,
                "content_type": "text/html",
                "body_bytes": len(raw),
                "artifact_path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            payload = public_read_payload(result, selected_capability="C1_RENDER")
            payload["structured_content"]["attempts"] = payload["structured_content"]["attempts"][1:]
            with self.assertRaisesRegex(ProviderAgentError, "C1 sequence"):
                package_success(c, payload)

    def test_public_read_fails_closed_on_malformed_route_summary_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = b"<html>route</html>"
            path = Path(tmp) / "rendered.html"
            path.write_bytes(raw)
            req = request("PUBLIC_READ_ACQUIRE")
            result = {
                "engine": "c0-fetch",
                "url": URL,
                "status": 200,
                "content_type": "text/html",
                "body_bytes": len(raw),
                "artifact_path": str(path),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            payload = public_read_payload(result)
            payload["structured_content"]["acquisition_route"]["render_fallback_attempted"] = "false"
            with self.assertRaisesRegex(ProviderAgentError, "render_fallback_attempted"):
                package_success(claim(req), payload)

    def test_document_ocr_packages_fetch_and_networkless_ocr_with_matching_pdf_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = b"%PDF-1.4\nfixture"
            path = Path(tmp) / "document.pdf"
            path.write_bytes(pdf)
            digest = hashlib.sha256(pdf).hexdigest()
            req = request("DOCUMENT_OCR")
            c = claim(req)
            fetch = job_payload(
                {
                    "engine": "c0-fetch",
                    "url": URL,
                    "status": 200,
                    "content_type": "application/pdf",
                    "body_bytes": len(pdf),
                    "artifact_path": str(path),
                    "sha256": digest,
                },
                job_id="fetch-job",
            )
            ocr = {
                "ok": True,
                "is_error": False,
                "structured_content": {
                    "input_sha256": digest,
                    "input_bytes": len(pdf),
                    "network_access": False,
                    "engine": "tesseract",
                    "text": "official tender",
                    "mean_confidence": 80.0,
                },
            }
            wire = package_document_ocr_success(c, fetch, ocr)
            line, artifact = wire.split(b"\n", 1)
            manifest = json.loads(line)
            parsed = json.loads(artifact)
            self.assertEqual(manifest["media_type"], "application/json")
            self.assertEqual(manifest["browser_job_id"], "fetch-job")
            self.assertEqual(set(manifest), self.manifest_keys)
            self.assertEqual(parsed["document_ocr"]["input_sha256"], digest)
            self.assertNotIn("artifact_path", parsed["fetch"])

            bad_ocr = {
                **ocr,
                "structured_content": {**ocr["structured_content"], "input_sha256": "0" * 64},
            }
            with self.assertRaisesRegex(ProviderAgentError, "OCR input SHA"):
                package_document_ocr_success(c, fetch, bad_ocr)

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
            self.assertEqual(set(manifest), self.manifest_keys)
            parsed = json.loads(artifact)
            self.assertEqual(parsed["result"]["engine"], engine)


class ProviderAgentRunTests(unittest.TestCase):
    def test_no_work_does_not_invoke_mcp(self):
        transport = FakeTransport({"status": "NO_WORK"})
        invoker = FakeInvoker({})
        result = run_once(transport=transport, invoker=invoker, contract=contract(), now=NOW)
        self.assertEqual(result["status"], "NO_WORK")
        self.assertEqual(invoker.calls, [])

    def test_all_capabilities_route_to_expected_tool(self):
        for capability in (value for value in CAPABILITY_TOOL_MAP if value != "DOCUMENT_OCR"):
            plan = None
            if capability == "C3_BROWSER_USE":
                plan = {"side_effect_class": "READ_ONLY_NAVIGATION", "retry_safe": False, "steps": [{"action": "snapshot"}]}
            req = request(capability, plan)
            transport = FakeTransport(claim(req))
            if capability in {"C0_FETCH", "PUBLIC_READ_ACQUIRE"}:
                with tempfile.TemporaryDirectory() as tmp:
                    raw = b"x"
                    p = Path(tmp) / "x.bin"; p.write_bytes(raw)
                    browser_result = {"engine": "c0-fetch", "url": URL, "status": 200, "content_type": "text/html", "body_bytes": 1, "artifact_path": str(p), "sha256": hashlib.sha256(raw).hexdigest()}
                    payload = (
                        public_read_payload(browser_result)
                        if capability == "PUBLIC_READ_ACQUIRE"
                        else job_payload(browser_result)
                    )
                    invoker = FakeInvoker(payload)
                    result = run_once(transport=transport, invoker=invoker, contract=contract(), now=NOW)
            else:
                invoker = FakeInvoker(job_payload({"engine": "x", "url": URL, "status": 200}))
                result = run_once(transport=transport, invoker=invoker, contract=contract(), now=NOW)
            self.assertEqual(result["status"], "ACCEPTED")
            self.assertEqual(invoker.calls[0][0], CAPABILITY_TOOL_MAP[capability])
            self.assertEqual(len(transport.submitted), 1)

    def test_document_ocr_run_composes_fetch_then_local_document_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = b"%PDF-1.4\nfixture"
            path = Path(tmp) / "document.pdf"
            path.write_bytes(pdf)
            digest = hashlib.sha256(pdf).hexdigest()
            req = request("DOCUMENT_OCR")
            transport = FakeTransport(claim(req))

            class SequenceInvoker:
                def __init__(self):
                    self.calls = []

                def call(self, tool, arguments):
                    self.calls.append((tool, arguments))
                    if tool == "document_ocr":
                        self.assertEqual(arguments["artifact_path"], str(path))
                        self.assertEqual(arguments["psm"], 6)
                        self.assertEqual(arguments["max_pages"], 12)
                        return {
                            "ok": True,
                            "is_error": False,
                            "structured_content": {
                                "input_sha256": digest,
                                "network_access": False,
                                "engine": "tesseract",
                                "text": "official tender",
                            },
                        }
                    raise AssertionError(tool)

                assertEqual = unittest.TestCase().assertEqual

            fetch_payload = job_payload(
                {
                    "engine": "provider-document-fetch",
                    "transport": "system_curl",
                    "url": URL,
                    "status": 200,
                    "content_type": "application/pdf",
                    "body_bytes": len(pdf),
                    "artifact_path": str(path),
                    "sha256": digest,
                    "provider_byte_budget": 1_000_000,
                },
                job_id="provider-fetch-job",
            )
            invoker = SequenceInvoker()
            with patch(
                "browser_plane.provider_agent._provider_document_fetch",
                return_value=fetch_payload,
            ) as provider_fetch:
                result = run_once(transport=transport, invoker=invoker, contract=contract(), now=NOW)
            self.assertEqual(result["status"], "ACCEPTED")
            provider_fetch.assert_called_once()
            self.assertEqual([tool for tool, _ in invoker.calls], ["document_ocr"])
            self.assertEqual(len(transport.submitted), 1)

    def test_invalid_claim_fails_before_mcp_and_reports_contract_failure(self):
        req = request("C0_FETCH")
        req["requested_url"] = "https://example.com/"
        req["request_sha256"] = request_sha256(req)
        transport = FakeTransport(claim(req))
        invoker = FakeInvoker({})
        with self.assertRaises(ProviderAgentError):
            run_once(transport=transport, invoker=invoker, contract=contract(), now=NOW)
        self.assertEqual(invoker.calls, [])
        self.assertEqual(transport.failed[0]["failure_class"], "PROVIDER_CONTRACT_MISMATCH")

    def test_expired_claim_fails_before_mcp(self):
        req = request("C0_FETCH")
        transport = FakeTransport(claim(req))
        invoker = FakeInvoker({})
        with self.assertRaisesRegex(ProviderAgentError, "expired"):
            run_once(transport=transport, invoker=invoker, contract=contract(), now=datetime(2026, 9, 8, 6, 3, tzinfo=UTC))
        self.assertEqual(invoker.calls, [])
        self.assertEqual(transport.failed[0]["failure_class"], "PROVIDER_CONTRACT_MISMATCH")

    def test_mcp_failure_reports_provider_not_ready(self):
        req = request("C1_RENDER")
        transport = FakeTransport(claim(req))

        class BrokenInvoker:
            def call(self, tool, arguments):
                raise RuntimeError("mcp unavailable")

        with self.assertRaises(RuntimeError):
            run_once(transport=transport, invoker=BrokenInvoker(), contract=contract(), now=NOW)
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
