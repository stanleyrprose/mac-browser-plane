from __future__ import annotations

import importlib.resources
import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .doctor import Doctor
from .models import Egress, JobSpec, JobState, ProfileMode, TERMINAL_STATES, TaskType


mcp = MCPServer(
    "Mac Browser Plane",
    instructions=(
        "Local stdio-only adapter over the existing Mac Browser Plane runtime. "
        "Use browser_fetch for strict-TLS HTTP acquisition, browser_render for deterministic "
        "engine-routed JS/DOM rendering, browser_inspect for Chrome read-only diagnostics, and browser_use for "
        "multi-step Playwright interaction with internal engine routing. Arbitrary JavaScript, raw CDP, and remote invocation "
        "are not available."
    ),
)

_ALLOWED_PROFILES = {"public-research", "authenticated-work", "development"}
_ALLOWED_PROFILE_MODES = {ProfileMode.EPHEMERAL.value, ProfileMode.EXCLUSIVE_PERSISTENT.value}
_ALLOWED_BROWSER_ACTIONS = {
    "navigate",
    "click",
    "type",
    "select",
    "press",
    "wait",
    "snapshot",
    "screenshot",
    "download",
}
_BROWSER_TARGET_FIELDS = ("selector", "role", "label", "text_target")
_BROWSER_TARGET_REQUIRED_ACTIONS = {"click", "type", "select", "download"}
_BROWSER_TARGET_OPTIONAL_ACTIONS = {"press", "wait"}


def _normalize_browser_target(action: dict[str, Any], index: int, *, required: bool) -> str | None:
    targets: dict[str, str] = {}
    for field in _BROWSER_TARGET_FIELDS:
        raw = action.get(field)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        if len(value) > 2_000:
            raise ToolError(f"action {index} {field} is too large")
        targets[field] = value
        action[field] = value

    if len(targets) > 1:
        raise ToolError(
            f"action {index} must use exactly one target form: selector, role, label, or text_target"
        )
    if required and not targets:
        raise ToolError(
            f"action {index} requires one target form: selector, role, label, or text_target"
        )

    target_kind = next(iter(targets), None)
    if "name" in action:
        if target_kind != "role":
            raise ToolError(f"action {index} name is allowed only with role targeting")
        name = str(action["name"]).strip()
        if not name:
            raise ToolError(f"action {index} role name must not be empty")
        if len(name) > 2_000:
            raise ToolError(f"action {index} role name is too large")
        action["name"] = name
    if "exact" in action:
        if target_kind not in {"role", "label", "text_target"}:
            raise ToolError(f"action {index} exact is allowed only with semantic targeting")
        if not isinstance(action["exact"], bool):
            raise ToolError(f"action {index} exact must be a boolean")
        action["exact"] = bool(action["exact"])
    return target_kind


def _runtime() -> tuple[RuntimePaths, RuntimeDB, JobStore]:
    paths = RuntimePaths.discover()
    paths.ensure()
    db = RuntimeDB(paths.db_path)
    db.initialize()
    return paths, db, JobStore(db)


def _load_capabilities() -> dict[str, Any]:
    resource = importlib.resources.files("browser_plane").joinpath("capabilities.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _validate_url(url: str) -> str:
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ToolError("Only absolute http:// or https:// URLs are allowed.")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ToolError("Localhost and .local targets are not allowed through the agent adapter.")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ToolError("Non-global IP targets are not allowed through the agent adapter.")
    return value


def _bounded_seconds(value: int, *, name: str, minimum: int, maximum: int) -> int:
    if value < minimum or value > maximum:
        raise ToolError(f"{name} must be between {minimum} and {maximum} seconds.")
    return value


def _profile(name: str) -> str:
    if name not in _ALLOWED_PROFILES:
        raise ToolError(f"profile must be one of: {', '.join(sorted(_ALLOWED_PROFILES))}")
    return name


def _profile_mode(value: str) -> ProfileMode:
    if value not in _ALLOWED_PROFILE_MODES:
        raise ToolError("profile_mode must be ephemeral or exclusive-persistent")
    return ProfileMode(value)


def _validate_browser_actions(actions: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    if not isinstance(actions, list) or not actions:
        raise ToolError("actions must be a non-empty list")
    if len(actions) > 50:
        raise ToolError("actions may contain at most 50 steps")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(actions, start=1):
        if not isinstance(raw, dict):
            raise ToolError(f"action {index} must be an object")
        action = dict(raw)
        kind = str(action.get("action", "")).strip().lower()
        if kind not in _ALLOWED_BROWSER_ACTIONS:
            raise ToolError(f"action {index} has unsupported action: {kind or '<missing>'}")
        action["action"] = kind

        try:
            timeout_ms = int(action.get("timeout_ms", 10_000))
        except (TypeError, ValueError) as exc:
            raise ToolError(f"action {index} timeout_ms must be an integer") from exc
        if timeout_ms < 1 or timeout_ms > 60_000:
            raise ToolError(f"action {index} timeout_ms must be between 1 and 60000")
        action["timeout_ms"] = timeout_ms

        target_kind: str | None = None
        if kind in _BROWSER_TARGET_REQUIRED_ACTIONS:
            target_kind = _normalize_browser_target(action, index, required=True)
        elif kind in _BROWSER_TARGET_OPTIONAL_ACTIONS:
            target_kind = _normalize_browser_target(action, index, required=False)

        if kind in {"click", "select"} and "force" in action:
            if not isinstance(action["force"], bool):
                raise ToolError(f"action {index} {kind} force must be a boolean")
            action["force"] = bool(action["force"])

        if kind == "navigate":
            action["url"] = _validate_url(str(action.get("url", "")))
            wait_until = str(action.get("wait_until", "domcontentloaded"))
            if wait_until not in {"commit", "domcontentloaded", "load", "networkidle"}:
                raise ToolError(f"action {index} navigate wait_until is invalid")
            action["wait_until"] = wait_until
        elif kind == "type":
            text = str(action.get("text", ""))
            if len(text) > 100_000:
                raise ToolError(f"action {index} type text is too large")
            action["text"] = text
        elif kind == "select":
            if "value" not in action:
                raise ToolError(f"action {index} select requires value")
            action["value"] = str(action["value"])
        elif kind == "press":
            key = str(action.get("key", "")).strip()
            if not key:
                raise ToolError(f"action {index} press requires key")
            action["key"] = key
        elif kind == "wait":
            if target_kind:
                state = str(action.get("state", "visible"))
                if state not in {"attached", "detached", "visible", "hidden"}:
                    raise ToolError(f"action {index} wait state is invalid")
                action["state"] = state
            else:
                try:
                    wait_ms = int(action.get("ms", 1000))
                except (TypeError, ValueError) as exc:
                    raise ToolError(f"action {index} wait ms must be an integer") from exc
                if wait_ms < 0 or wait_ms > 30_000:
                    raise ToolError(f"action {index} wait ms must be between 0 and 30000")
                action["ms"] = wait_ms

        normalized.append(action)
    return tuple(normalized)


def _public_job(row: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(row["result_json"]) if row.get("result_json") else None
    return {
        "job_id": row["job_id"],
        "state": row["state"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "failure_class": row["failure_class"],
        "partial_effect_possible": bool(row["partial_effect_possible"]),
        "result": result,
    }


def _submit_and_wait(
    *,
    task_type: TaskType,
    url: str,
    profile: str = "public-research",
    profile_mode: ProfileMode = ProfileMode.EPHEMERAL,
    queue_timeout_sec: int,
    max_run_sec: int,
    client_timeout_sec: int,
    evidence_policy: str,
    control_mode: str = "normal",
    actions: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    target = _validate_url(url)
    queue_timeout_sec = _bounded_seconds(queue_timeout_sec, name="queue_timeout_sec", minimum=1, maximum=600)
    max_run_sec = _bounded_seconds(max_run_sec, name="max_run_sec", minimum=1, maximum=600)
    client_timeout_sec = _bounded_seconds(client_timeout_sec, name="client_timeout_sec", minimum=1, maximum=900)
    profile = _profile(profile)

    _, _, jobs = _runtime()
    spec = JobSpec(
        task_type=task_type,
        url=target,
        egress=Egress.DIRECT,
        profile=profile,
        profile_mode=profile_mode,
        queue_timeout_sec=queue_timeout_sec,
        max_run_sec=max_run_sec,
        evidence_policy=evidence_policy,
        control_mode=control_mode,
        retry_policy="none",
        allow_egress_fallback=False,
        actions=actions,
    )
    job_id = jobs.submit(spec)
    row = jobs.wait(job_id, float(client_timeout_sec), poll_sec=0.2)
    if row is None:
        raise ToolError(f"Job disappeared after submission: {job_id}")
    public = _public_job(row)
    if JobState(row["state"]) not in TERMINAL_STATES:
        public["status"] = "JOB_STILL_PENDING"
    return public


@mcp.tool()
def browser_capabilities() -> dict[str, Any]:
    """Return the machine-readable Browser Plane capability and security manifest."""
    return _load_capabilities()


@mcp.tool()
def browser_doctor() -> dict[str, Any]:
    """Run Browser Plane readiness checks without starting a second worker."""
    paths, db, _ = _runtime()
    doctor = Doctor(paths, db)
    report = doctor.run()
    report["report_path"] = str(doctor.write_report(report))
    return report


@mcp.tool()
def browser_fetch(
    url: str,
    queue_timeout_sec: int = 60,
    max_run_sec: int = 60,
    client_timeout_sec: int = 90,
) -> dict[str, Any]:
    """Fetch a public HTTP(S) URL through C0 strict-TLS acquisition and preserve raw evidence."""
    return _submit_and_wait(
        task_type=TaskType.FETCH,
        url=url,
        queue_timeout_sec=queue_timeout_sec,
        max_run_sec=max_run_sec,
        client_timeout_sec=client_timeout_sec,
        evidence_policy="always",
    )


@mcp.tool()
def browser_render(
    url: str,
    profile: str = "public-research",
    profile_mode: str = "ephemeral",
    queue_timeout_sec: int = 60,
    max_run_sec: int = 120,
    client_timeout_sec: int = 180,
) -> dict[str, Any]:
    """Render JS/DOM for a public HTTP(S) URL through the internal C1 engine router; this does not click or type."""
    return _submit_and_wait(
        task_type=TaskType.AUTOMATE,
        url=url,
        profile=profile,
        profile_mode=_profile_mode(profile_mode),
        queue_timeout_sec=queue_timeout_sec,
        max_run_sec=max_run_sec,
        client_timeout_sec=client_timeout_sec,
        evidence_policy="on_failure",
    )


@mcp.tool()
def browser_use(
    url: str,
    actions: list[dict[str, Any]],
    profile: str = "public-research",
    profile_mode: str = "ephemeral",
    queue_timeout_sec: int = 60,
    max_run_sec: int = 180,
    client_timeout_sec: int = 240,
) -> dict[str, Any]:
    """Run deterministic C3 Browser Use in runtime-owned Chrome; Lightpanda v1 is limited to ephemeral C1 rendering."""
    return _submit_and_wait(
        task_type=TaskType.USE,
        url=url,
        profile=profile,
        profile_mode=_profile_mode(profile_mode),
        queue_timeout_sec=queue_timeout_sec,
        max_run_sec=max_run_sec,
        client_timeout_sec=client_timeout_sec,
        evidence_policy="always",
        control_mode="use",
        actions=_validate_browser_actions(actions),
    )


@mcp.tool()
def browser_inspect(
    url: str,
    profile: str = "public-research",
    queue_timeout_sec: int = 60,
    max_run_sec: int = 120,
    client_timeout_sec: int = 180,
) -> dict[str, Any]:
    """Inspect a public HTTP(S) URL through C2 read-only browser diagnostics and screenshot evidence."""
    return _submit_and_wait(
        task_type=TaskType.INSPECT,
        url=url,
        profile=profile,
        profile_mode=ProfileMode.EPHEMERAL,
        queue_timeout_sec=queue_timeout_sec,
        max_run_sec=max_run_sec,
        client_timeout_sec=client_timeout_sec,
        evidence_policy="always",
        control_mode="inspect",
    )


@mcp.tool()
def browser_status(job_id: str) -> dict[str, Any]:
    """Return public lifecycle state for one Browser Plane job."""
    _, _, jobs = _runtime()
    row = jobs.get(job_id)
    if row is None:
        raise ToolError(f"JOB_NOT_FOUND: {job_id}")
    return _public_job(row)


@mcp.tool()
def browser_result(job_id: str) -> dict[str, Any]:
    """Return the stored result/failure payload for one Browser Plane job."""
    _, _, jobs = _runtime()
    row = jobs.get(job_id)
    if row is None:
        raise ToolError(f"JOB_NOT_FOUND: {job_id}")
    result = json.loads(row["result_json"]) if row.get("result_json") else None
    return {
        "job_id": job_id,
        "state": row["state"],
        "result": result,
        "failure_class": row["failure_class"],
    }


@mcp.tool()
def browser_cancel(job_id: str) -> dict[str, Any]:
    """Request cancellation of a queued or currently running Browser Plane job."""
    _, _, jobs = _runtime()
    before = jobs.get(job_id)
    if before is None:
        raise ToolError(f"JOB_NOT_FOUND: {job_id}")
    changed = jobs.request_cancel(job_id)
    row = jobs.get(job_id)
    assert row is not None
    return {"job_id": job_id, "cancel_accepted": changed, "state": row["state"]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
