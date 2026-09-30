from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any

from .models import JobState


ACQUISITION_POLICY = "public_read_auto_v1"
_CHALLENGE_TRIGGERS = {
    "cloudflare_challenge",
    "akamai_challenge",
    "datadome_challenge",
}
_JS_REQUIRED_MARKERS = (
    "enable javascript",
    "javascript is required",
    "javascript required",
    "please turn on javascript",
    "please enable javascript",
    "requires javascript",
)
_SPA_ROOT_RE = re.compile(
    r"""id\s*=\s*["'](?:app|root|__next|app-root|main-app)["']""",
    re.IGNORECASE,
)
_SPA_RUNTIME_MARKERS = (
    "__next_data__",
    "webpack",
    "vite",
    "data-reactroot",
    "ng-version",
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "template", "svg", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "template", "svg", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    @property
    def text(self) -> str:
        return " ".join(self.parts).strip()


def _result(public_job: dict[str, Any]) -> dict[str, Any]:
    value = public_job.get("result")
    return value if isinstance(value, dict) else {}


def _c0_body_text(public_job: dict[str, Any]) -> str:
    result = _result(public_job)
    artifact_path = result.get("artifact_path")
    if isinstance(artifact_path, str) and artifact_path:
        try:
            with Path(artifact_path).open("rb") as handle:
                raw = handle.read(1_000_001)
        except OSError:
            raw = b""
        if raw:
            return raw[:1_000_000].decode("utf-8", errors="replace")

    excerpt = result.get("text_excerpt")
    return excerpt if isinstance(excerpt, str) else ""


def c0_render_trigger(public_job: dict[str, Any]) -> str | None:
    """Return a conservative reason to escalate explicit public-read acquisition to C1.

    This function never authorizes rendering by itself. The caller must already be
    executing the explicit browser_acquire composite capability.
    """

    if public_job.get("state") != JobState.SUCCEEDED.value:
        return None

    result = _result(public_job)
    route = result.get("transport_route")
    route = route if isinstance(route, dict) else {}
    challenge = route.get("trigger")
    if (
        isinstance(challenge, str)
        and challenge in _CHALLENGE_TRIGGERS
        and route.get("selected") == "system_curl"
    ):
        return challenge

    status = result.get("status")
    if not isinstance(status, int) or status < 200 or status >= 400:
        return None

    content_type = str(result.get("content_type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "application/xhtml+xml"}:
        return None

    body = _c0_body_text(public_job)
    if not body.strip():
        return "html_empty_body"

    parser = _VisibleTextParser()
    try:
        parser.feed(body)
    except Exception:
        return None

    visible = parser.text
    lower = body.lower()

    if (
        len(visible) < 300
        and any(marker in lower for marker in _JS_REQUIRED_MARKERS)
        and ("<noscript" in lower or "<script" in lower)
    ):
        return "javascript_required"

    has_spa_root = bool(_SPA_ROOT_RE.search(body))
    has_spa_runtime = any(marker in lower for marker in _SPA_RUNTIME_MARKERS)
    if len(visible) < 120 and "<script" in lower and (has_spa_root or has_spa_runtime):
        return "spa_shell_low_text"

    return None


def attempt_summary(capability: str, public_job: dict[str, Any]) -> dict[str, Any]:
    result = _result(public_job)
    return {
        "capability": capability,
        "job_id": public_job.get("job_id"),
        "state": public_job.get("state"),
        "http_status": result.get("status"),
        "engine": result.get("engine"),
        "browser_engine": result.get("browser_engine"),
        "transport": result.get("transport"),
    }


def acquisition_outcome(public_job: dict[str, Any]) -> str:
    if public_job.get("state") != JobState.SUCCEEDED.value:
        return "EXECUTION_FAILED"
    status = _result(public_job).get("status")
    if isinstance(status, int) and status >= 400:
        return "HTTP_RESPONSE_NOT_SUCCESS"
    return "CONTENT_RETURNED"
