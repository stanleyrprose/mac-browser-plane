from __future__ import annotations

import fcntl
import json
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .models import JobSpec, ProfileMode


_SCHEMA_VERSION = 1
_MAX_EXCEPTION_CHARS = 1200
_MAX_TITLE_CHARS = 300
_MAX_TEXT_CHARS = 2000
_MAX_ARIA_CHARS = 4000
_MAX_TARGET_CHARS = 300

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization)\b\s*[:=]\s*([^\s,;]+)"
)


def _safe_url(url: str) -> str:
    """Keep route identity while dropping credentials, query, and fragment data."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return ""
    if not parsed.scheme or not host:
        return ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))


def _redact_text(value: str, limit: int, sensitive_literals: tuple[str, ...] = ()) -> str:
    redacted = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=REDACTED", value)
    for literal in sorted((item for item in sensitive_literals if len(item) >= 3), key=len, reverse=True):
        redacted = redacted.replace(literal, "[REDACTED_INPUT]")
    return redacted[:limit]


def _safe_action(action: dict[str, Any]) -> dict[str, object]:
    """Capture action shape without typed text, selected values, or credentials."""
    safe: dict[str, object] = {
        "action": str(action.get("action", "")).strip().lower(),
    }
    if "timeout_ms" in action:
        safe["timeout_ms"] = action["timeout_ms"]
    for key in ("selector", "role", "label", "text_target", "name"):
        if key in action:
            safe[key] = _redact_text(str(action[key]), _MAX_TARGET_CHARS)
    if "exact" in action:
        safe["exact"] = bool(action["exact"])
    if "force" in action:
        safe["force"] = bool(action["force"])
    if safe["action"] == "navigate" and action.get("url"):
        safe["url"] = _safe_url(str(action["url"]))
    if safe["action"] == "type":
        safe["typed_chars"] = len(str(action.get("text", "")))
    if safe["action"] == "select":
        safe["value_present"] = "value" in action
    if safe["action"] == "press" and action.get("key"):
        safe["key"] = _redact_text(str(action["key"]), 80)
    return safe


def classify_failure(exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}".lower()
    if "strict mode violation" in message or "resolved to" in message and "elements" in message:
        return "TARGET_AMBIGUOUS"
    if "frame was detached" in message or "frame detached" in message:
        return "FRAME_DETACHED"
    if "not attached" in message or "detached from" in message or "stale" in message:
        return "DETACHED_OR_STALE"
    if "timeout" in message:
        return "ACTION_TIMEOUT"
    if "download" in message:
        return "DOWNLOAD_FAILED"
    if "navigation" in message or "page.goto" in message:
        return "NAVIGATION_FAILED"
    return "ACTION_ERROR"


class C3FailureCorpus:
    """Append-only, local/private corpus of observed C3 execution failures."""

    def __init__(self, paths: RuntimePaths, db: RuntimeDB):
        self.paths = paths
        self.jobs = JobStore(db)
        self.path = paths.state_dir / "c3-failure-corpus.jsonl"

    def _job_spec(self, job_id: str) -> JobSpec | None:
        row = self.jobs.get(job_id)
        if not row or not row.get("spec_json"):
            return None
        try:
            return JobSpec.from_mapping(json.loads(str(row["spec_json"])))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def _page_context(
        self,
        page: Any,
        *,
        allow_content: bool,
        sensitive_literals: tuple[str, ...] = (),
    ) -> dict[str, object]:
        context: dict[str, object] = {}
        try:
            context["url"] = _safe_url(str(page.url))
        except Exception:
            context["url"] = ""
        try:
            context["title"] = _redact_text(str(page.title()), _MAX_TITLE_CHARS, sensitive_literals)
        except Exception:
            context["title"] = ""

        if not allow_content:
            context["content_capture"] = "metadata_only"
            return context

        context["content_capture"] = "bounded_public_context"
        try:
            body = page.locator("body")
            text = body.inner_text(timeout=1000)
            context["text_excerpt"] = _redact_text(str(text), _MAX_TEXT_CHARS, sensitive_literals)
        except Exception:
            context["text_excerpt"] = ""
        try:
            body = page.locator("body")
            aria = body.aria_snapshot(timeout=1000, depth=6, mode="ai")
            context["aria_snapshot"] = _redact_text(str(aria), _MAX_ARIA_CHARS, sensitive_literals)
            context["aria_snapshot_truncated"] = len(str(aria)) > _MAX_ARIA_CHARS
        except Exception:
            context["aria_snapshot"] = ""
            context["aria_snapshot_truncated"] = False
        return context

    def record_action_failure(
        self,
        *,
        page: Any,
        job_id: str,
        browser_engine: str,
        step: int,
        action: dict[str, Any],
        exc: BaseException,
    ) -> dict[str, object]:
        spec = self._job_spec(job_id)
        sensitive_literals: tuple[str, ...] = ()
        if spec is not None:
            sensitive_literals = tuple(
                str(candidate)
                for job_action in spec.actions
                for key in ("text", "value")
                for candidate in (job_action.get(key),)
                if candidate not in (None, "")
            )
        allow_content = bool(
            spec
            and spec.profile == "public-research"
            and spec.profile_mode == ProfileMode.EPHEMERAL
        )
        host = ""
        try:
            host = (urlsplit(str(page.url)).hostname or "").lower()
        except Exception:
            pass

        record: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "failure_id": str(uuid.uuid4()),
            "recorded_at": datetime.now(UTC).isoformat(),
            "job_id": job_id,
            "observed_failure_class": classify_failure(exc),
            "browser_engine": browser_engine,
            "host": host,
            "step": step,
            "action": _safe_action(action),
            "exception": {
                "type": type(exc).__name__,
                "message": _redact_text(str(exc), _MAX_EXCEPTION_CHARS, sensitive_literals),
            },
            "page": self._page_context(
                page,
                allow_content=allow_content,
                sensitive_literals=sensitive_literals,
            ),
        }
        if spec is not None:
            record["profile"] = spec.profile
            record["profile_mode"] = spec.profile_mode.value
            record["job_engine_request"] = spec.engine.value

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        self.path.chmod(0o600)
        return record

    def recent(self, limit: int = 20) -> list[dict[str, object]]:
        if limit < 1:
            return []
        records = self._read_all()
        return records[-limit:][::-1]

    def summary(self) -> dict[str, object]:
        records = self._read_all()
        by_class = Counter(str(item.get("observed_failure_class") or "UNKNOWN") for item in records)
        by_action = Counter(str(dict(item.get("action") or {}).get("action") or "UNKNOWN") for item in records)
        by_host = Counter(str(item.get("host") or "UNKNOWN") for item in records)
        return {
            "schema_version": _SCHEMA_VERSION,
            "path": str(self.path),
            "total_failures": len(records),
            "by_failure_class": dict(sorted(by_class.items())),
            "by_action": dict(sorted(by_action.items())),
            "by_host": dict(sorted(by_host.items())),
        }

    def _read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        records: list[dict[str, object]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return records
