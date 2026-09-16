from __future__ import annotations

import time
from typing import Any


C1_CONTENT_QUALITY_GATE = "nonempty_rendered_body_v1"
C1_CONTENT_MAX_WAIT_SEC = 5.0
C1_CONTENT_POLL_INTERVAL_SEC = 0.5


class C1ContentQualityError(RuntimeError):
    """Rendered C1 output did not meet the minimum source-independent truthfulness gate."""


def require_nonempty_c1_body(body_text: object, *, engine: str) -> str:
    text = body_text if isinstance(body_text, str) else ""
    text = text.strip()
    if not text:
        raise C1ContentQualityError(
            f"{engine} C1 content quality gate failed: rendered body remained empty"
        )
    return text


def c1_content_quality_metadata(body_text: object, *, wait_ms: int) -> dict[str, object]:
    text = require_nonempty_c1_body(body_text, engine="browser")
    return {
        "content_quality": {
            "status": "PASS",
            "gate": C1_CONTENT_QUALITY_GATE,
            "text_chars": len(text),
        },
        "content_ready_wait_ms": max(0, int(wait_ms)),
    }


def wait_for_sync_c1_content(
    page: Any,
    *,
    engine: str,
    max_wait_sec: float = C1_CONTENT_MAX_WAIT_SEC,
    poll_interval_sec: float = C1_CONTENT_POLL_INTERVAL_SEC,
) -> tuple[str, str, int]:
    """Wait briefly for a rendered body to become non-empty after DOMContentLoaded.

    This is intentionally a minimum acquisition-quality gate, not a business-content
    classifier. Access-denied, stopped-site, login, and other non-empty pages remain
    truthful browser results for the caller/source policy to classify.
    """

    started = time.monotonic()
    deadline = started + max(0.0, max_wait_sec)
    latest_html = ""

    while True:
        latest_html = str(page.content() or "")
        body_value = page.evaluate("document.body ? document.body.innerText : ''")
        body_text = body_value if isinstance(body_value, str) else ""
        if body_text.strip():
            return latest_html, body_text, int((time.monotonic() - started) * 1000)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise C1ContentQualityError(
                f"{engine} C1 content quality gate failed: rendered body remained empty"
            )
        page.wait_for_timeout(min(poll_interval_sec, remaining) * 1000)
