from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from .c0_transport import curl_error_supports_impersonated_retry, fetch_impersonated
from .config import RuntimePaths
from .mcp_call import _call_tool
from .translation_provider import CodexOAuthTranslator, run_translation_once

PROVIDER_ID = "mac-mm-01"
CONTRACT_VERSION = 1
CAPABILITY_TOOL_MAP = {
    "PUBLIC_READ_ACQUIRE": "browser_acquire",
    "C0_FETCH": "browser_fetch",
    "C1_RENDER": "browser_render",
    "C2_INSPECT": "browser_inspect",
    "C3_BROWSER_USE": "browser_use",
    "DOCUMENT_OCR": "document_ocr",
}
PIC_C3_ACTIONS = {"snapshot", "navigate", "click", "wait", "type", "select", "press", "screenshot"}
MAX_C0_BYTES = 1_000_000
MAX_ROUTE_SUMMARY_STRING = 128
MAX_ROUTE_SUMMARY_ATTEMPTS = 2


class ProviderAgentError(RuntimeError):
    pass


class ProviderTransport(Protocol):
    def claim(self) -> dict[str, Any]: ...
    def submit(self, payload: bytes) -> dict[str, Any]: ...
    def fail(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class McpInvoker(Protocol):
    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_sha256(request: dict[str, Any]) -> str:
    value = dict(request)
    value.pop("request_sha256", None)
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _validate_url(target: dict[str, Any], url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
        raise ProviderAgentError("provider request URL violates HTTPS authority boundary")
    if ".." in unquote(parsed.path).split("/"):
        raise ProviderAgentError("provider request URL path traversal is forbidden")
    exact = target.get("exact_urls")
    if isinstance(exact, list) and exact:
        if url not in exact:
            raise ProviderAgentError("provider request URL is not an approved exact target")
        return
    if parsed.hostname != target.get("https_host"):
        raise ProviderAgentError("provider request host is not locally authorized")
    prefix = target.get("path_prefix")
    if not isinstance(prefix, str) or not parsed.path.startswith(prefix):
        raise ProviderAgentError("provider request path is not locally authorized")
    suffix = target.get("path_suffix")
    if isinstance(suffix, str) and suffix and not parsed.path.lower().endswith(suffix.lower()):
        raise ProviderAgentError("provider request suffix is not locally authorized")
    if parsed.query and target.get("allow_query") is not True:
        raise ProviderAgentError("provider request query is not locally authorized")
    if parsed.fragment and target.get("allow_fragment") is not True:
        raise ProviderAgentError("provider request fragment is not locally authorized")


def _parse_time(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ProviderAgentError(f"{field} missing")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProviderAgentError(f"{field} invalid") from exc
    if parsed.tzinfo is None:
        raise ProviderAgentError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def validate_claim(claim: dict[str, Any], contract: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if claim.get("status") != "CLAIMED" or claim.get("provider_id") != PROVIDER_ID:
        raise ProviderAgentError("invalid provider claim envelope")
    request = claim.get("request")
    if not isinstance(request, dict):
        raise ProviderAgentError("provider claim request missing")
    if claim.get("provider_request_id") != request.get("provider_request_id"):
        raise ProviderAgentError("provider request correlation mismatch")
    for field in ("provider_attempt_id", "claim_token"):
        if not isinstance(claim.get(field), str) or not claim[field]:
            raise ProviderAgentError(f"provider claim field missing: {field}")
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if _parse_time(request.get("expires_at"), field="request expires_at") <= observed:
        raise ProviderAgentError("provider request expired")
    if _parse_time(claim.get("claim_expires_at"), field="claim_expires_at") <= observed:
        raise ProviderAgentError("provider claim expired")
    return validate_request(request, contract)


def validate_request(request: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != CONTRACT_VERSION or contract.get("provider_id") != PROVIDER_ID:
        raise ProviderAgentError("local provider contract identity mismatch")
    if contract.get("transport") != "pull_ssh_v1":
        raise ProviderAgentError("local provider transport contract mismatch")
    if request.get("contract_version") != CONTRACT_VERSION or request.get("provider_id") != PROVIDER_ID:
        raise ProviderAgentError("provider request identity/version mismatch")
    if request.get("request_sha256") != request_sha256(request):
        raise ProviderAgentError("provider request SHA-256 mismatch")

    source_id = request.get("source_id")
    policies = contract.get("source_policies")
    source = policies.get(source_id) if isinstance(policies, dict) and isinstance(source_id, str) else None
    if not isinstance(source, dict) or source.get("enabled") is not True:
        raise ProviderAgentError("provider request source is not locally authorized")
    if request.get("source_policy_version") != source.get("source_policy_version"):
        raise ProviderAgentError("provider source policy version mismatch")

    capability = request.get("capability")
    tool = CAPABILITY_TOOL_MAP.get(str(capability))
    if tool is None or request.get("mcp_tool") != tool:
        raise ProviderAgentError("provider capability/tool mismatch")
    if capability not in source.get("allowed_capabilities", []):
        raise ProviderAgentError("provider capability is not locally authorized")
    target_role = request.get("target_role")
    targets = source.get("targets")
    target = targets.get(target_role) if isinstance(targets, dict) and isinstance(target_role, str) else None
    if not isinstance(target, dict) or capability not in target.get("capabilities", []):
        raise ProviderAgentError("provider target role/capability is not locally authorized")
    url = request.get("requested_url")
    if not isinstance(url, str):
        raise ProviderAgentError("provider request URL missing")
    _validate_url(target, url)

    max_bytes = request.get("max_bytes")
    max_run = request.get("max_run_seconds")
    if not isinstance(max_bytes, int) or max_bytes < 1 or max_bytes > int(target.get("max_bytes", 0)):
        raise ProviderAgentError("provider request max_bytes exceeds local target contract")
    if capability == "C0_FETCH" and max_bytes > MAX_C0_BYTES:
        raise ProviderAgentError("C0 max_bytes exceeds current Browser Plane C0 limit")
    if not isinstance(max_run, int) or max_run < 1 or max_run > int(target.get("max_run_seconds", 0)):
        raise ProviderAgentError("provider request max_run_seconds exceeds local target contract")

    plan = request.get("interaction_plan")
    if capability == "C3_BROWSER_USE":
        if not isinstance(plan, dict) or plan.get("side_effect_class") != "READ_ONLY_NAVIGATION" or not isinstance(plan.get("retry_safe"), bool):
            raise ProviderAgentError("C3 requires explicit READ_ONLY_NAVIGATION/retry_safe contract")
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps or len(steps) > 50:
            raise ProviderAgentError("C3 interaction plan must contain 1..50 actions")
        for step in steps:
            if not isinstance(step, dict) or step.get("action") not in PIC_C3_ACTIONS:
                raise ProviderAgentError("C3 action is outside PIC read-only navigation subset")
            if any(key in step for key in ("javascript", "script", "shell", "command", "download")):
                raise ProviderAgentError("C3 arbitrary/side-effect execution field is forbidden")
    elif plan is not None:
        raise ProviderAgentError("interaction_plan is C3-only")
    return request


def mcp_arguments(request: dict[str, Any]) -> dict[str, Any]:
    capability = str(request["capability"])
    if capability == "DOCUMENT_OCR":
        raise ProviderAgentError("DOCUMENT_OCR uses the composed fetch + document_ocr path")
    max_run = int(request["max_run_seconds"])
    base = {
        "url": str(request["requested_url"]),
        "queue_timeout_sec": min(60, max_run),
        "max_run_sec": max_run,
    }
    if capability == "PUBLIC_READ_ACQUIRE":
        queue_budget = min(30, max(1, max_run // 3))
        return {
            "url": str(request["requested_url"]),
            "queue_timeout_sec": queue_budget,
            "fetch_max_run_sec": max(1, max_run - queue_budget),
            "render_max_run_sec": max_run,
            "client_timeout_sec": max_run,
        }
    if capability == "C0_FETCH":
        base["client_timeout_sec"] = min(900, int(request["max_run_seconds"]) + 30)
        return base
    if capability == "C1_RENDER":
        base.update(profile="public-research", profile_mode="ephemeral", client_timeout_sec=min(900, int(request["max_run_seconds"]) + 60))
        return base
    if capability == "C2_INSPECT":
        base.update(profile="public-research", client_timeout_sec=min(900, int(request["max_run_seconds"]) + 60))
        return base
    if capability == "C3_BROWSER_USE":
        plan = request["interaction_plan"]
        base.update(
            actions=[dict(step) for step in plan["steps"]],
            profile="public-research",
            profile_mode="ephemeral",
            client_timeout_sec=min(900, int(request["max_run_seconds"]) + 60),
        )
        return base
    raise ProviderAgentError("unsupported capability")


def _public_job(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is False:
        raise ProviderAgentError("local MCP call returned error")
    structured = payload.get("structured_content", payload)
    if not isinstance(structured, dict):
        raise ProviderAgentError("local MCP structured result missing")
    if structured.get("state") != "SUCCEEDED":
        raise ProviderAgentError(f"Browser job not SUCCEEDED: {structured.get('state')}")
    if not isinstance(structured.get("job_id"), str) or not isinstance(structured.get("result"), dict):
        raise ProviderAgentError("Browser job result contract incomplete")
    return structured


def _portable_result(value: Any) -> Any:
    if isinstance(value, list):
        return [_portable_result(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"artifact_path", "screenshot"}:
            continue
        if key == "path" and isinstance(item, str) and item.startswith("/"):
            continue
        cleaned[key] = _portable_result(item)
    return cleaned


def _route_summary_string(value: Any, *, field: str, nullable: bool = True) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_ROUTE_SUMMARY_STRING:
        raise ProviderAgentError(f"PUBLIC_READ_ACQUIRE route metadata invalid: {field}")
    return value


def _public_read_route_summary(job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    selected = job.get("selected_capability")
    route = job.get("acquisition_route")
    if selected not in {"C0_FETCH", "C1_RENDER"} or not isinstance(route, dict):
        raise ProviderAgentError("PUBLIC_READ_ACQUIRE route metadata invalid")

    render_attempted = route.get("render_fallback_attempted")
    if not isinstance(render_attempted, bool):
        raise ProviderAgentError("PUBLIC_READ_ACQUIRE route metadata invalid: render_fallback_attempted")

    transport_route = result.get("transport_route")
    if transport_route is not None and not isinstance(transport_route, dict):
        raise ProviderAgentError("PUBLIC_READ_ACQUIRE route metadata invalid: transport_route")
    selected_transport_value = (
        transport_route.get("selected")
        if isinstance(transport_route, dict) and transport_route.get("selected") is not None
        else result.get("transport")
    )

    raw_attempts = job.get("attempts")
    if not isinstance(raw_attempts, list) or not 1 <= len(raw_attempts) <= MAX_ROUTE_SUMMARY_ATTEMPTS:
        raise ProviderAgentError("PUBLIC_READ_ACQUIRE route metadata invalid: attempts")
    raw_capabilities = [
        attempt.get("capability") if isinstance(attempt, dict) else None
        for attempt in raw_attempts
    ]
    if selected == "C0_FETCH":
        if raw_capabilities != ["C0_FETCH"] or render_attempted is not False:
            raise ProviderAgentError("PUBLIC_READ_ACQUIRE route metadata invalid: C0 sequence")
    elif (
        raw_capabilities != ["C0_FETCH", "C1_RENDER"]
        or render_attempted is not True
        or route.get("render_trigger") is None
    ):
        raise ProviderAgentError("PUBLIC_READ_ACQUIRE route metadata invalid: C1 sequence")
    attempts: list[dict[str, Any]] = []
    for index, attempt in enumerate(raw_attempts):
        if not isinstance(attempt, dict) or attempt.get("capability") not in {"C0_FETCH", "C1_RENDER"}:
            raise ProviderAgentError(f"PUBLIC_READ_ACQUIRE route metadata invalid: attempts[{index}]")
        http_status = attempt.get("http_status")
        if http_status is not None and (not isinstance(http_status, int) or isinstance(http_status, bool)):
            raise ProviderAgentError(f"PUBLIC_READ_ACQUIRE route metadata invalid: attempts[{index}].http_status")
        attempts.append(
            {
                "capability": attempt["capability"],
                "state": _route_summary_string(attempt.get("state"), field=f"attempts[{index}].state", nullable=False),
                "http_status": http_status,
                "engine": _route_summary_string(attempt.get("engine"), field=f"attempts[{index}].engine"),
                "browser_engine": _route_summary_string(
                    attempt.get("browser_engine"), field=f"attempts[{index}].browser_engine"
                ),
                "transport": _route_summary_string(attempt.get("transport"), field=f"attempts[{index}].transport"),
            }
        )

    return {
        "schema_version": 1,
        "policy": "public_read_auto_v1",
        "selected_capability": selected,
        "selected_engine": _route_summary_string(result.get("engine"), field="selected_engine"),
        "selected_browser_engine": _route_summary_string(
            result.get("browser_engine"), field="selected_browser_engine"
        ),
        "selected_transport": _route_summary_string(selected_transport_value, field="selected_transport"),
        "render_trigger": _route_summary_string(route.get("render_trigger"), field="render_trigger"),
        "render_fallback_attempted": render_attempted,
        "render_skipped_reason": _route_summary_string(
            route.get("render_skipped_reason"), field="render_skipped_reason"
        ),
        "attempt_count": len(attempts),
        "attempts": attempts,
        "c2_authorized": False,
        "c3_authorized": False,
    }


def _direct_structured(payload: dict[str, Any], *, tool: str) -> dict[str, Any]:
    if payload.get("ok") is False or payload.get("is_error") is True:
        raise ProviderAgentError(f"{tool} MCP call returned error")
    structured = payload.get("structured_content", payload)
    if not isinstance(structured, dict):
        raise ProviderAgentError(f"{tool} MCP structured result missing")
    return structured


def _provider_document_fetch(
    request: dict[str, Any],
    contract: dict[str, Any],
    *,
    paths: RuntimePaths | None = None,
) -> dict[str, Any]:
    """Fetch a PIC-authorized OCR PDF using the request byte budget.

    This is provider-internal. Public browser_fetch keeps its 1 MB contract;
    DOCUMENT_OCR may fetch a larger official PDF only after source-specific
    PIC validation has succeeded.
    """

    runtime_paths = paths or RuntimePaths.discover()
    runtime_paths.ensure()
    provider_request_id = str(request["provider_request_id"])
    evidence_dir = runtime_paths.evidence_dir / f"provider-document-{provider_request_id}"
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_dir.chmod(0o700)
    body_path = evidence_dir / "response.pdf"
    max_bytes = int(request["max_bytes"])
    max_run = int(request["max_run_seconds"])
    requested_url = str(request["requested_url"])
    curl = Path("/usr/bin/curl")
    if not curl.is_file():
        raise ProviderAgentError("DOCUMENT_OCR system curl unavailable")

    proc = subprocess.run(
        [
            str(curl),
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-time",
            str(max_run),
            "--max-filesize",
            str(max_bytes),
            "--user-agent",
            "mac-browser-plane-provider/0.1",
            "--output",
            str(body_path),
            "--write-out",
            "%{http_code}\n%{url_effective}\n%{content_type}\n",
            requested_url,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=max_run + 5,
    )

    transport = "system_curl"
    if proc.returncode == 0:
        lines = proc.stdout.splitlines()
        try:
            status = int(lines[0]) if lines else 0
        except ValueError as exc:
            raise ProviderAgentError("DOCUMENT_OCR curl HTTP status invalid") from exc
        final_url = lines[1] if len(lines) > 1 else requested_url
        content_type = lines[2] if len(lines) > 2 and lines[2] else None
        try:
            body = body_path.read_bytes()
        except OSError as exc:
            raise ProviderAgentError(f"DOCUMENT_OCR fetched artifact unreadable: {exc}") from exc
    else:
        direct_error = proc.stderr.strip()[:1000]
        if not curl_error_supports_impersonated_retry(proc.returncode):
            raise ProviderAgentError(
                f"DOCUMENT_OCR curl failed ({proc.returncode}): {direct_error}"
            )
        try:
            fallback = fetch_impersonated(
                requested_url,
                timeout_sec=max_run,
                max_bytes=max_bytes,
            )
        except Exception as exc:
            raise ProviderAgentError(
                f"DOCUMENT_OCR curl failed ({proc.returncode}): {direct_error}; "
                f"curl_cffi fallback failed: {type(exc).__name__}: {exc}"
            ) from exc
        transport = "curl_cffi"
        status = fallback.status
        final_url = fallback.url
        content_type = fallback.content_type
        body = fallback.body
        body_path.write_bytes(body)

    if len(body) > max_bytes:
        raise ProviderAgentError("DOCUMENT_OCR fetched PDF exceeds request max_bytes")
    if not body.startswith(b"%PDF-"):
        raise ProviderAgentError("DOCUMENT_OCR fetched artifact is not PDF")
    policies = contract.get("source_policies")
    source = policies.get(request.get("source_id")) if isinstance(policies, dict) else None
    targets = source.get("targets") if isinstance(source, dict) else None
    target = targets.get(request.get("target_role")) if isinstance(targets, dict) else None
    if not isinstance(target, dict):
        raise ProviderAgentError("DOCUMENT_OCR local target policy missing")
    final_policy = target.get("final_url_policy")
    if not isinstance(final_policy, dict):
        final_policy = target
    _validate_url(final_policy, final_url)
    if status < 200 or status >= 400:
        raise ProviderAgentError(f"DOCUMENT_OCR HTTP status not successful: {status}")

    body_path.chmod(0o600)
    digest = hashlib.sha256(body).hexdigest()
    return {
        "ok": True,
        "tool": "provider_document_fetch",
        "is_error": False,
        "structured_content": {
            "job_id": f"provider-document-fetch:{provider_request_id}",
            "state": "SUCCEEDED",
            "created_at": str(request.get("requested_at") or ""),
            "started_at": str(request.get("requested_at") or ""),
            "finished_at": datetime.now(UTC).isoformat(),
            "failure_class": None,
            "partial_effect_possible": False,
            "result": {
                "engine": "provider-document-fetch",
                "transport": transport,
                "url": final_url,
                "status": status,
                "content_type": content_type,
                "body_bytes": len(body),
                "artifact_path": str(body_path),
                "sha256": digest,
                "provider_byte_budget": max_bytes,
            },
        },
    }


def package_document_ocr_success(
    claim: dict[str, Any],
    fetch_payload: dict[str, Any],
    ocr_payload: dict[str, Any],
) -> bytes:
    request = claim["request"]
    fetch_job = _public_job(fetch_payload)
    fetch_result = fetch_job["result"]
    artifact_path = fetch_result.get("artifact_path")
    if not isinstance(artifact_path, str) or not artifact_path:
        raise ProviderAgentError("DOCUMENT_OCR fetch artifact_path missing")
    pdf_path = Path(artifact_path)
    try:
        pdf = pdf_path.read_bytes()
    except OSError as exc:
        raise ProviderAgentError(f"DOCUMENT_OCR fetched artifact unreadable: {exc}") from exc
    if not pdf.startswith(b"%PDF-"):
        raise ProviderAgentError("DOCUMENT_OCR fetched artifact is not PDF")
    if fetch_result.get("sha256") != hashlib.sha256(pdf).hexdigest():
        raise ProviderAgentError("DOCUMENT_OCR fetched artifact SHA mismatch")
    if fetch_result.get("body_bytes") != len(pdf):
        raise ProviderAgentError("DOCUMENT_OCR fetched artifact length mismatch")
    max_bytes = request.get("max_bytes")
    if not isinstance(max_bytes, int) or len(pdf) > max_bytes:
        raise ProviderAgentError("DOCUMENT_OCR fetched PDF exceeds request max_bytes")

    ocr = _direct_structured(ocr_payload, tool="document_ocr")
    if ocr.get("input_sha256") != hashlib.sha256(pdf).hexdigest():
        raise ProviderAgentError("DOCUMENT_OCR OCR input SHA does not match fetched PDF")
    if ocr.get("network_access") is not False:
        raise ProviderAgentError("DOCUMENT_OCR must report network_access=false")

    artifact = canonical_json(
        {
            "fetch": _portable_result(fetch_result),
            "document_ocr": _portable_result(ocr),
        }
    )
    if len(artifact) > int(max_bytes):
        raise ProviderAgentError("DOCUMENT_OCR result artifact exceeds request max_bytes")
    final_url = fetch_result.get("url")
    if not isinstance(final_url, str) or not final_url:
        raise ProviderAgentError("DOCUMENT_OCR final URL missing")
    status = fetch_result.get("status")
    if status is not None and not isinstance(status, int):
        raise ProviderAgentError("DOCUMENT_OCR HTTP status invalid")

    manifest = {
        "contract_version": CONTRACT_VERSION,
        "provider_request_id": claim["provider_request_id"],
        "provider_attempt_id": claim["provider_attempt_id"],
        "claim_token": claim["claim_token"],
        "browser_job_id": fetch_job["job_id"],
        "request_sha256": request["request_sha256"],
        "state": "SUCCEEDED",
        "mcp_tool": request["mcp_tool"],
        "final_url": final_url,
        "http_status": status,
        "media_type": "application/json",
        "artifact_bytes": len(artifact),
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
    }
    return canonical_json(manifest) + b"\n" + artifact


def package_success(claim: dict[str, Any], mcp_payload: dict[str, Any]) -> bytes:
    request = claim["request"]
    job = _public_job(mcp_payload)
    result = job["result"]
    capability = str(request["capability"])
    route_summary: dict[str, Any] | None = None
    if capability == "PUBLIC_READ_ACQUIRE":
        if job.get("acquisition_policy") != "public_read_auto_v1":
            raise ProviderAgentError("PUBLIC_READ_ACQUIRE acquisition policy mismatch")
        selected = job.get("selected_capability")
        if selected not in {"C0_FETCH", "C1_RENDER"}:
            raise ProviderAgentError("PUBLIC_READ_ACQUIRE selected capability outside C0/C1")
        route = job.get("acquisition_route")
        if (
            not isinstance(route, dict)
            or route.get("policy") != "public_read_auto_v1"
            or route.get("c2_authorized") is not False
            or route.get("c3_authorized") is not False
        ):
            raise ProviderAgentError("PUBLIC_READ_ACQUIRE route authorization boundary violated")
        route_summary = _public_read_route_summary(job, result)
    if capability in {"C0_FETCH", "PUBLIC_READ_ACQUIRE"}:
        path = result.get("artifact_path")
        if not isinstance(path, str):
            raise ProviderAgentError(f"{capability} raw artifact_path missing")
        artifact = Path(path).read_bytes()
        media_type = str(result.get("content_type") or "application/octet-stream").split(";", 1)[0].strip()
        if result.get("sha256") != hashlib.sha256(artifact).hexdigest() or result.get("body_bytes") != len(artifact):
            raise ProviderAgentError(f"{capability} local artifact integrity mismatch")
    else:
        artifact = canonical_json({"job_id": job["job_id"], "state": job["state"], "result": _portable_result(result)})
        media_type = "application/json"
    max_bytes = request.get("max_bytes")
    if not isinstance(max_bytes, int) or len(artifact) > max_bytes:
        raise ProviderAgentError("provider result artifact exceeds request max_bytes")
    final_url = result.get("url")
    if not isinstance(final_url, str) or not final_url:
        raise ProviderAgentError("Browser result final URL missing")
    status = result.get("status")
    if status is not None and not isinstance(status, int):
        raise ProviderAgentError("Browser result HTTP status invalid")
    manifest = {
        "contract_version": CONTRACT_VERSION,
        "provider_request_id": claim["provider_request_id"],
        "provider_attempt_id": claim["provider_attempt_id"],
        "claim_token": claim["claim_token"],
        "browser_job_id": job["job_id"],
        "request_sha256": request["request_sha256"],
        "state": "SUCCEEDED",
        "mcp_tool": request["mcp_tool"],
        "final_url": final_url,
        "http_status": status,
        "media_type": media_type,
        "artifact_bytes": len(artifact),
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
    }
    if route_summary is not None:
        manifest["route_summary"] = route_summary
    return canonical_json(manifest) + b"\n" + artifact


@dataclass(frozen=True)
class SshProviderTransport:
    host: str
    identity_file: str | None = None
    ssh_binary: str = "/usr/bin/ssh"
    timeout_seconds: int = 30

    def _argv(self, command: str) -> list[str]:
        args = [
            self.ssh_binary,
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ClearAllForwardings=yes",
            "-o", f"ConnectTimeout={min(30, self.timeout_seconds)}",
        ]
        if self.identity_file:
            args += ["-i", self.identity_file, "-o", "IdentitiesOnly=yes"]
        args += [self.host, command]
        return args

    def _run(
        self,
        command: str,
        stdin: bytes | None = None,
        *,
        unsupported_is_no_work: bool = False,
    ) -> dict[str, Any]:
        proc = subprocess.run(
            self._argv(command),
            input=stdin,
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
        )
        try:
            value = json.loads(proc.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = None
        if proc.returncode != 0:
            if (
                unsupported_is_no_work
                and proc.returncode == 126
                and isinstance(value, dict)
                and value.get("status") == "DENY"
                and "unsupported provider command" in str(value.get("error") or "")
            ):
                return {"status": "NO_WORK", "compatibility": "TRANSLATION_COMMAND_UNSUPPORTED"}
            raise ProviderAgentError(f"provider transport failed: rc={proc.returncode}")
        if not isinstance(value, dict):
            raise ProviderAgentError("provider transport returned invalid JSON")
        return value

    def claim(self) -> dict[str, Any]:
        return self._run("provider-claim-v1")

    def submit(self, payload: bytes) -> dict[str, Any]:
        return self._run("provider-submit-v1", payload)

    def fail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run("provider-fail-v1", canonical_json(payload))

    def translation_claim(self) -> dict[str, Any]:
        return self._run("translation-claim-v1", unsupported_is_no_work=True)

    def translation_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run("translation-submit-v1", canonical_json(payload))

    def translation_fail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run("translation-fail-v1", canonical_json(payload))


class LocalMcpInvoker:
    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(_call_tool(tool, arguments))


def run_once(*, transport: ProviderTransport, invoker: McpInvoker, contract: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    claim = transport.claim()
    if claim.get("status") == "NO_WORK":
        return claim
    if claim.get("status") != "CLAIMED" or not isinstance(claim.get("request"), dict):
        raise ProviderAgentError("claim response contract invalid")
    request = claim["request"]
    try:
        validate_claim(claim, contract, now=now)
        capability = str(request["capability"])
        if capability == "DOCUMENT_OCR":
            fetch_payload = _provider_document_fetch(request, contract)
            fetch_job = _public_job(fetch_payload)
            artifact_path = fetch_job["result"].get("artifact_path")
            if not isinstance(artifact_path, str) or not artifact_path:
                raise ProviderAgentError("DOCUMENT_OCR fetch artifact_path missing")
            ocr_payload = invoker.call(
                "document_ocr",
                {"artifact_path": artifact_path, "psm": 6, "max_pages": 12},
            )
            wire = package_document_ocr_success(claim, fetch_payload, ocr_payload)
        else:
            tool = str(request["mcp_tool"])
            payload = invoker.call(tool, mcp_arguments(request))
            wire = package_success(claim, payload)
        return transport.submit(wire)
    except Exception as exc:
        failure = {
            "provider_request_id": str(claim.get("provider_request_id", "")),
            "provider_attempt_id": str(claim.get("provider_attempt_id", "")),
            "claim_token": str(claim.get("claim_token", "")),
            "failure_class": "PROVIDER_CONTRACT_MISMATCH" if isinstance(exc, ProviderAgentError) else "PROVIDER_NOT_READY",
        }
        try:
            transport.fail(failure)
        except Exception:
            pass
        raise


def load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderAgentError(f"cannot load provider contract: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderAgentError("provider contract root must be object")
    return value


def _poll_delay(result: dict[str, Any], interval_sec: float) -> float:
    if result.get("status") != "NO_WORK":
        return 0.0
    return max(1.0, float(interval_sec))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signalforge-provider-agent")
    parser.add_argument("--host", required=True, help="Restricted Bangkok SSH host/alias")
    parser.add_argument("--contract", type=Path, required=True, help="Local provider authorization projection")
    parser.add_argument("--identity-file", help="Dedicated provider SSH identity")
    parser.add_argument("--interval-sec", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    transport = SshProviderTransport(args.host, args.identity_file)
    invoker = LocalMcpInvoker()
    translator = CodexOAuthTranslator()
    contract = load_contract(args.contract)
    try:
        while True:
            translation_result = run_translation_once(transport=transport, translator=translator)
            result = run_once(transport=transport, invoker=invoker, contract=contract)
            if args.once or translation_result.get("status") != "NO_WORK":
                print(
                    json.dumps({"ok": True, "translation_result": translation_result}, ensure_ascii=False, sort_keys=True),
                    flush=True,
                )
            if args.once or result.get("status") != "NO_WORK":
                print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True), flush=True)
            if args.once:
                return
            if translation_result.get("status") != "NO_WORK" or result.get("status") != "NO_WORK":
                continue
            time.sleep(max(1.0, float(args.interval_sec)))
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
