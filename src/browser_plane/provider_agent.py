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

from .mcp_call import _call_tool

PROVIDER_ID = "mac-mm-01"
CONTRACT_VERSION = 1
CAPABILITY_TOOL_MAP = {
    "C0_FETCH": "browser_fetch",
    "C1_RENDER": "browser_render",
    "C2_INSPECT": "browser_inspect",
    "C3_BROWSER_USE": "browser_use",
}
PIC_C3_ACTIONS = {"snapshot", "navigate", "click", "wait", "type", "select", "press", "screenshot"}
MAX_C0_BYTES = 1_000_000


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
    base = {
        "url": str(request["requested_url"]),
        "queue_timeout_sec": min(60, int(request["max_run_seconds"])),
        "max_run_sec": int(request["max_run_seconds"]),
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


def package_success(claim: dict[str, Any], mcp_payload: dict[str, Any]) -> bytes:
    request = claim["request"]
    job = _public_job(mcp_payload)
    result = job["result"]
    capability = str(request["capability"])
    if capability == "C0_FETCH":
        path = result.get("artifact_path")
        if not isinstance(path, str):
            raise ProviderAgentError("C0 raw artifact_path missing")
        artifact = Path(path).read_bytes()
        media_type = str(result.get("content_type") or "application/octet-stream").split(";", 1)[0].strip()
        if result.get("sha256") != hashlib.sha256(artifact).hexdigest() or result.get("body_bytes") != len(artifact):
            raise ProviderAgentError("C0 local artifact integrity mismatch")
    else:
        artifact = canonical_json({"job_id": job["job_id"], "state": job["state"], "result": _portable_result(result)})
        media_type = "application/json"
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

    def _run(self, command: str, stdin: bytes | None = None) -> dict[str, Any]:
        proc = subprocess.run(
            self._argv(command),
            input=stdin,
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
        )
        if proc.returncode != 0:
            raise ProviderAgentError(f"provider transport failed: rc={proc.returncode}")
        try:
            value = json.loads(proc.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderAgentError("provider transport returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ProviderAgentError("provider transport JSON root must be object")
        return value

    def claim(self) -> dict[str, Any]:
        return self._run("provider-claim-v1")

    def submit(self, payload: bytes) -> dict[str, Any]:
        return self._run("provider-submit-v1", payload)

    def fail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run("provider-fail-v1", canonical_json(payload))


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
    contract = load_contract(args.contract)
    try:
        while True:
            result = run_once(transport=transport, invoker=invoker, contract=contract)
            if args.once or result.get("status") != "NO_WORK":
                print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True), flush=True)
            if args.once:
                return
            delay = _poll_delay(result, args.interval_sec)
            if delay:
                time.sleep(delay)
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
