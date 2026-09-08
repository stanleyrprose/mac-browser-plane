from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .mcp_call import _call_tool

PROVIDER_ID = "mac-mm-01"
CONTRACT_VERSION = 1
CAPABILITY_TOOL_MAP = {
    "C0_FETCH": "browser_fetch",
    "C1_RENDER": "browser_render",
    "C2_INSPECT": "browser_inspect",
    "C3_BROWSER_USE": "browser_use",
}
C3_ALLOWED_ACTIONS = {"snapshot", "navigate", "click", "wait", "type", "select", "screenshot"}


class ProviderAgentError(RuntimeError):
    pass


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _request_sha256(request: dict[str, Any]) -> str:
    payload = dict(request)
    payload.pop("request_sha256", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ProviderAgentError("provider request timestamp missing")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProviderAgentError("provider request timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise ProviderAgentError("provider request timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _target_policy(contract: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != CONTRACT_VERSION or contract.get("provider_id") != PROVIDER_ID:
        raise ProviderAgentError("provider contract identity mismatch")
    source_id = request.get("source_id")
    sources = contract.get("source_policies")
    source = sources.get(source_id) if isinstance(sources, dict) and isinstance(source_id, str) else None
    if not isinstance(source, dict) or source.get("enabled") is not True:
        raise ProviderAgentError("source is not locally authorized")
    if request.get("source_policy_version") != source.get("source_policy_version"):
        raise ProviderAgentError("source policy version mismatch")
    capability = request.get("capability")
    if capability not in source.get("allowed_capabilities", []):
        raise ProviderAgentError("capability is not locally authorized for source")
    targets = source.get("targets")
    target = targets.get(request.get("target_role")) if isinstance(targets, dict) else None
    if not isinstance(target, dict) or capability not in target.get("capabilities", []):
        raise ProviderAgentError("capability is not locally authorized for target role")
    return target


def _validate_url(url: object, target: dict[str, Any]) -> str:
    if not isinstance(url, str):
        raise ProviderAgentError("requested_url missing")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ProviderAgentError("provider URL violates HTTPS authority boundary")
    if parsed.port not in (None, 443):
        raise ProviderAgentError("provider URL custom port is forbidden")
    decoded = unquote(parsed.path)
    if ".." in decoded.split("/"):
        raise ProviderAgentError("provider URL path traversal is forbidden")
    exact = target.get("exact_urls")
    if isinstance(exact, list) and exact:
        if url not in exact:
            raise ProviderAgentError("provider URL is not an approved exact target")
        return url
    if parsed.hostname != target.get("https_host"):
        raise ProviderAgentError("provider URL host is not approved")
    prefix = target.get("path_prefix")
    if not isinstance(prefix, str) or not parsed.path.startswith(prefix):
        raise ProviderAgentError("provider URL path is outside approved prefix")
    suffix = target.get("path_suffix")
    if isinstance(suffix, str) and suffix and not parsed.path.lower().endswith(suffix.lower()):
        raise ProviderAgentError("provider URL suffix is not approved")
    if parsed.query and target.get("allow_query") is not True:
        raise ProviderAgentError("provider URL query is not approved")
    if parsed.fragment and target.get("allow_fragment") is not True:
        raise ProviderAgentError("provider URL fragment is not approved")
    return url


def validate_claim(claim: dict[str, Any], contract: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if claim.get("status") != "CLAIMED" or claim.get("provider_id") != PROVIDER_ID:
        raise ProviderAgentError("invalid provider claim envelope")
    request = claim.get("request")
    if not isinstance(request, dict):
        raise ProviderAgentError("provider claim request missing")
    if request.get("contract_version") != CONTRACT_VERSION or request.get("provider_id") != PROVIDER_ID:
        raise ProviderAgentError("provider request contract identity mismatch")
    if claim.get("provider_request_id") != request.get("provider_request_id"):
        raise ProviderAgentError("provider request correlation mismatch")
    supplied_hash = request.get("request_sha256")
    if not isinstance(supplied_hash, str) or supplied_hash != _request_sha256(request):
        raise ProviderAgentError("provider request SHA-256 mismatch")
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if _parse_time(request.get("expires_at")) <= observed:
        raise ProviderAgentError("provider request expired")
    if _parse_time(claim.get("claim_expires_at")) <= observed:
        raise ProviderAgentError("provider claim expired")

    target = _target_policy(contract, request)
    requested_url = _validate_url(request.get("requested_url"), target)
    capability = str(request.get("capability"))
    tool = CAPABILITY_TOOL_MAP.get(capability)
    if not tool or request.get("mcp_tool") != tool:
        raise ProviderAgentError("provider capability/MCP tool mismatch")

    args: dict[str, Any] = {
        "url": requested_url,
        "max_run_sec": int(request.get("max_run_seconds", 60)),
        "client_timeout_sec": min(int(request.get("max_run_seconds", 60)) + 30, 900),
    }
    if capability in {"C1_RENDER", "C2_INSPECT", "C3_BROWSER_USE"}:
        args["profile"] = "public-research"
    if capability in {"C1_RENDER", "C3_BROWSER_USE"}:
        args["profile_mode"] = "ephemeral"
    if capability == "C3_BROWSER_USE":
        plan = request.get("interaction_plan")
        if not isinstance(plan, dict) or plan.get("side_effect_class") != "READ_ONLY_NAVIGATION":
            raise ProviderAgentError("C3 requires READ_ONLY_NAVIGATION interaction plan")
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps or len(steps) > 50:
            raise ProviderAgentError("C3 interaction steps must contain 1..50 entries")
        actions: list[dict[str, Any]] = []
        for index, raw in enumerate(steps, start=1):
            if not isinstance(raw, dict) or raw.get("action") not in C3_ALLOWED_ACTIONS:
                raise ProviderAgentError(f"C3 action {index} is not supported by local runtime contract")
            action = dict(raw)
            if action.get("action") == "navigate":
                action["url"] = _validate_url(action.get("url"), target)
            if any(key in action for key in ("shell", "javascript", "script", "command")):
                raise ProviderAgentError("C3 arbitrary execution fields are forbidden")
            actions.append(action)
        args["actions"] = actions
    return {"request": request, "tool": tool, "arguments": args}


def build_completion(claim: dict[str, Any], mcp_result: dict[str, Any]) -> dict[str, Any]:
    if mcp_result.get("ok") is not True or mcp_result.get("is_error") is not False:
        raise ProviderAgentError("local MCP call failed")
    content = mcp_result.get("structured_content")
    if not isinstance(content, dict) or content.get("state") != "SUCCEEDED":
        raise ProviderAgentError("local Browser job did not succeed")
    browser_job_id = content.get("job_id")
    if not isinstance(browser_job_id, str) or not browser_job_id:
        raise ProviderAgentError("local Browser job_id missing")
    result_sha256 = hashlib.sha256(_canonical_json(mcp_result)).hexdigest()
    return {
        "provider_request_id": claim["provider_request_id"],
        "provider_attempt_id": claim["provider_attempt_id"],
        "claim_token": claim["claim_token"],
        "result_sha256": result_sha256,
        "browser_job_id": browser_job_id,
    }


class SshDispatcher:
    def __init__(self, ssh_host: str, *, ssh_bin: str = "/usr/bin/ssh") -> None:
        if not ssh_host or any(ch.isspace() for ch in ssh_host):
            raise ProviderAgentError("ssh_host must be one configured SSH host token")
        self.ssh_host = ssh_host
        self.ssh_bin = ssh_bin

    def call(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if command not in {"provider-claim-v1", "provider-status-v1", "provider-complete-v1", "provider-fail-v1"}:
            raise ProviderAgentError("unsupported dispatcher command")
        completed = subprocess.run(
            [self.ssh_bin, "-o", "BatchMode=yes", self.ssh_host, command],
            input=None if payload is None else json.dumps(payload, separators=(",", ":")),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise ProviderAgentError(f"dispatcher transport failed ({completed.returncode})")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderAgentError("dispatcher returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ProviderAgentError("dispatcher returned non-object JSON")
        return result


def run_once(
    contract: dict[str, Any],
    dispatcher: SshDispatcher,
    *,
    mcp_caller: Callable[[str, dict[str, Any]], Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    claim = dispatcher.call("provider-claim-v1")
    if claim.get("status") == "NO_WORK":
        return claim
    try:
        validated = validate_claim(claim, contract, now=now)
        if mcp_caller is None:
            mcp_result = asyncio.run(_call_tool(validated["tool"], validated["arguments"]))
        else:
            mcp_result = mcp_caller(validated["tool"], validated["arguments"])
        completion = build_completion(claim, mcp_result)
        ack = dispatcher.call("provider-complete-v1", completion)
        return {"status": "COMPLETED", "claim": claim, "mcp_result": mcp_result, "ack": ack}
    except Exception as exc:
        failure = {
            "provider_request_id": claim.get("provider_request_id"),
            "provider_attempt_id": claim.get("provider_attempt_id"),
            "claim_token": claim.get("claim_token"),
            "failure_class": "PROVIDER_RESULT_INVALID" if isinstance(exc, ProviderAgentError) else "PROVIDER_EXECUTION_FAILED",
        }
        if all(isinstance(failure.get(field), str) and failure.get(field) for field in ("provider_request_id", "provider_attempt_id", "claim_token")):
            try:
                dispatcher.call("provider-fail-v1", failure)
            except Exception:
                pass
        raise


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderAgentError(f"cannot load provider contract: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderAgentError("provider contract must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mac-browser-provider-agent")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--interval-sec", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    contract = _load_contract(args.contract)
    dispatcher = SshDispatcher(args.ssh_host)
    try:
        while True:
            result = run_once(contract, dispatcher)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            if args.once:
                return
            time.sleep(max(1.0, args.interval_sec))
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
