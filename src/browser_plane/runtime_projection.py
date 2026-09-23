from __future__ import annotations

from typing import Any

from .models import JobState

RUNTIME_ID = "mac-mm-01"
RUNTIME_TYPE = "browser"
RUNTIME_CONTRACT_VERSION = "agent-runtime-v1.1"

_JOB_STATE_MAP = {
    JobState.QUEUED.value: "queued",
    JobState.WAITING_RESOURCE.value: "waiting",
    JobState.RUNNING.value: "running",
    JobState.PAUSED_FOR_INSPECTION.value: "waiting",
    JobState.WAITING_HUMAN.value: "waiting",
    JobState.RECOVERY_REQUIRED.value: "recovery_required",
    JobState.CANCEL_REQUESTED.value: "running",
    JobState.SUCCEEDED.value: "succeeded",
    JobState.FAILED.value: "failed",
    JobState.CANCELLED.value: "cancelled",
    JobState.QUEUE_TIMEOUT.value: "timeout",
    JobState.EXECUTION_TIMEOUT.value: "timeout",
    JobState.STALLED_HUMAN_TIMEOUT.value: "timeout",
}


def _runtime_state_unknown(reason: str) -> dict[str, Any]:
    return {
        "runtime_id": RUNTIME_ID,
        "runtime_type": RUNTIME_TYPE,
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "operational_state": "unknown",
        "reason_codes": [reason],
    }


def _verification_state(result: dict[str, Any] | None, normalized_job_state: str) -> dict[str, Any]:
    if normalized_job_state in {"queued", "waiting", "running"}:
        return {
            "status": "pending",
            "scope": "business_semantics",
            "reason": "JOB_NOT_TERMINAL",
            "checks": [],
        }
    if normalized_job_state != "succeeded":
        return {
            "status": "unknown",
            "scope": "business_semantics",
            "reason": "JOB_NOT_SUCCEEDED",
            "checks": [],
        }

    value = result or {}
    checks: list[dict[str, str]] = []
    content_quality = value.get("content_quality")
    if isinstance(content_quality, dict):
        status = str(content_quality.get("status") or "").upper()
        checks.append(
            {
                "name": str(content_quality.get("gate") or "content_quality"),
                "status": "pass" if status == "PASS" else "fail" if status == "FAIL" else "unknown",
            }
        )
    if value.get("network_access") is False:
        checks.append({"name": "network_access_disabled", "status": "pass"})
    if isinstance(value.get("input_sha256"), str):
        checks.append({"name": "input_digest_recorded", "status": "pass"})

    semantics = str(value.get("result_semantics") or "").upper()
    reason = (
        "SOURCE_CROSS_CHECK_REQUIRED"
        if "SOURCE_CROSS_CHECK" in semantics or "EVIDENCE_ENRICHMENT_ONLY" in semantics
        else "CALLER_VERIFICATION_REQUIRED"
    )
    return {
        "status": "unknown",
        "scope": "business_semantics",
        "reason": reason,
        "checks": checks,
    }


def _artifact(
    *,
    kind: str,
    private_ref: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    retained: bool | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": kind, "portable": False}
    if private_ref:
        value["private_ref"] = private_ref
    if sha256:
        value["sha256"] = sha256
    if isinstance(size_bytes, int):
        value["bytes"] = size_bytes
    if retained is not None:
        value["retained"] = retained
    return value


def artifacts_from_result(
    result: dict[str, Any] | None,
    *,
    input_ref: str | None = None,
    input_kind: str | None = None,
) -> list[dict[str, Any]]:
    value = result or {}
    artifacts: list[dict[str, Any]] = []

    artifact_path = value.get("artifact_path")
    if isinstance(artifact_path, str) and artifact_path:
        artifacts.append(
            _artifact(
                kind="browser_output",
                private_ref=artifact_path,
                sha256=value.get("sha256") if isinstance(value.get("sha256"), str) else None,
                size_bytes=value.get("body_bytes") if isinstance(value.get("body_bytes"), int) else None,
                retained=True,
            )
        )

    screenshot = value.get("screenshot")
    if isinstance(screenshot, str) and screenshot:
        artifacts.append(_artifact(kind="screenshot", private_ref=screenshot, retained=True))

    actions = value.get("actions")
    if isinstance(actions, list):
        for item in actions:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str) or not path:
                continue
            artifacts.append(
                _artifact(
                    kind=str(item.get("action") or "browser_action_artifact"),
                    private_ref=path,
                    sha256=item.get("sha256") if isinstance(item.get("sha256"), str) else None,
                    size_bytes=item.get("bytes") if isinstance(item.get("bytes"), int) else None,
                    retained=True,
                )
            )

    if input_ref:
        artifacts.append(
            _artifact(
                kind=input_kind or "input_evidence",
                private_ref=input_ref,
                sha256=value.get("input_sha256") if isinstance(value.get("input_sha256"), str) else None,
                size_bytes=value.get("input_bytes") if isinstance(value.get("input_bytes"), int) else None,
                retained=True,
            )
        )

    pages = value.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            digest = page.get("image_sha256")
            if isinstance(digest, str) and digest:
                artifacts.append(
                    _artifact(
                        kind="ocr_page_raster_evidence",
                        sha256=digest,
                        size_bytes=page.get("image_bytes") if isinstance(page.get("image_bytes"), int) else None,
                        retained=False,
                    )
                )

    return artifacts


def project_job(row: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    native_state = str(row.get("state") or "UNKNOWN")
    normalized = _JOB_STATE_MAP.get(native_state, "unknown")
    return {
        "runtime_state": _runtime_state_unknown("READINESS_NOT_RECHECKED_FOR_JOB"),
        "job_state": {
            "job_id": row.get("job_id"),
            "native_state": native_state,
            "state": normalized,
            "failure_class": row.get("failure_class"),
            "partial_effect_possible": bool(row.get("partial_effect_possible")),
        },
        "verification_state": _verification_state(result, normalized),
        "artifacts": artifacts_from_result(result),
    }


def project_immediate_ocr(kind: str, result: dict[str, Any], artifact_path: str) -> dict[str, Any]:
    return {
        "runtime_state": _runtime_state_unknown("READINESS_NOT_RECHECKED_FOR_IMMEDIATE_CALL"),
        "job_state": {
            "job_id": None,
            "native_state": "IMMEDIATE_SUCCEEDED",
            "state": "succeeded",
            "job_type": kind,
            "failure_class": None,
            "partial_effect_possible": False,
        },
        "verification_state": _verification_state(result, "succeeded"),
        "artifacts": artifacts_from_result(
            result,
            input_ref=artifact_path,
            input_kind="ocr_input",
        ),
    }


def project_doctor(report: dict[str, Any], report_path: str | None = None) -> dict[str, Any]:
    native = str(report.get("status") or "UNKNOWN")
    operational = {
        "READY": "ready",
        "DEGRADED": "degraded",
        "NOT_READY": "blocked",
    }.get(native, "unknown")
    checks = report.get("checks")
    conditions: list[dict[str, Any]] = []
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            ok = check.get("ok")
            conditions.append(
                {
                    "type": str(check.get("name") or "unknown"),
                    "status": "True" if ok is True else "False" if ok is False else "Unknown",
                    "reason": "CHECK_PASSED" if ok is True else "CHECK_FAILED" if ok is False else "CHECK_UNKNOWN",
                }
            )
    artifacts: list[dict[str, Any]] = []
    if report_path:
        artifacts.append(_artifact(kind="doctor_report", private_ref=report_path, retained=True))
    return {
        "runtime_state": {
            "runtime_id": RUNTIME_ID,
            "runtime_type": RUNTIME_TYPE,
            "contract_version": RUNTIME_CONTRACT_VERSION,
            "native_state": native,
            "operational_state": operational,
            "reason_codes": [],
            "conditions": conditions,
        },
        "job_state": None,
        "verification_state": {
            "status": "not_required",
            "scope": "runtime_readiness",
            "reason": "READINESS_PROBE",
            "checks": [],
        },
        "artifacts": artifacts,
    }
