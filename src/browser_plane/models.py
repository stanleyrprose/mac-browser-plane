from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    QUEUED = "QUEUED"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    RUNNING = "RUNNING"
    PAUSED_FOR_INSPECTION = "PAUSED_FOR_INSPECTION"
    WAITING_HUMAN = "WAITING_HUMAN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    QUEUE_TIMEOUT = "QUEUE_TIMEOUT"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    STALLED_HUMAN_TIMEOUT = "STALLED_HUMAN_TIMEOUT"


TERMINAL_STATES = {
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.CANCELLED,
    JobState.QUEUE_TIMEOUT,
    JobState.EXECUTION_TIMEOUT,
    JobState.STALLED_HUMAN_TIMEOUT,
}


class TaskType(StrEnum):
    FETCH = "fetch"
    AUTOMATE = "automate"
    INSPECT = "inspect"
    USE = "use"
    AGENT = "agent"


class Egress(StrEnum):
    AUTO = "auto"
    DIRECT = "direct"
    SOUTHEAST_ASIA = "southeast_asia"
    CHINA = "china"


class ProfileMode(StrEnum):
    EPHEMERAL = "ephemeral"
    STORAGE_STATE = "storage-state"
    EXCLUSIVE_PERSISTENT = "exclusive-persistent"


class BrowserEngine(StrEnum):
    AUTO = "auto"
    CHROME = "chrome"
    LIGHTPANDA = "lightpanda"
    CAMOUFOX = "camoufox"


@dataclass(frozen=True)
class JobSpec:
    task_type: TaskType
    url: str
    engine: BrowserEngine = BrowserEngine.AUTO
    egress: Egress = Egress.AUTO
    profile: str = "public-research"
    profile_mode: ProfileMode = ProfileMode.EPHEMERAL
    queue_timeout_sec: int = 300
    max_run_sec: int = 120
    human_hold_sec: int = 600
    evidence_policy: str = "on_failure"
    control_mode: str = "normal"
    retry_policy: str = "none"
    allow_egress_fallback: bool = False
    idempotency_key: str | None = None
    actions: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "JobSpec":
        raw_actions = data.get("actions", [])
        if not isinstance(raw_actions, (list, tuple)):
            raise ValueError("actions must be a list")
        return cls(
            task_type=TaskType(data.get("task_type", "fetch")),
            url=str(data["url"]),
            engine=BrowserEngine(data.get("engine", "auto")),
            egress=Egress(data.get("egress", "auto")),
            profile=str(data.get("profile", "public-research")),
            profile_mode=ProfileMode(data.get("profile_mode", "ephemeral")),
            queue_timeout_sec=int(data.get("queue_timeout_sec", 300)),
            max_run_sec=int(data.get("max_run_sec", 120)),
            human_hold_sec=int(data.get("human_hold_sec", 600)),
            evidence_policy=str(data.get("evidence_policy", "on_failure")),
            control_mode=str(data.get("control_mode", "normal")),
            retry_policy=str(data.get("retry_policy", "none")),
            allow_egress_fallback=bool(data.get("allow_egress_fallback", False)),
            idempotency_key=data.get("idempotency_key"),
            actions=tuple(dict(action) for action in raw_actions),
        )
