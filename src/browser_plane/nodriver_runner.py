from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from .config import RuntimePaths
from .db import RuntimeDB
from .executor import BrowserExecutor


def _terminate_requested(_signum: int, _frame: object) -> None:
    raise SystemExit(143)


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _string_value(value: object) -> str:
    if isinstance(value, str):
        return value
    remote_value = getattr(value, "value", None)
    return remote_value if isinstance(remote_value, str) else ""


async def _wait_for_rendered_content(
    page: Any,
    *,
    max_wait_sec: float,
    poll_interval_sec: float = 0.5,
) -> tuple[str, str, int]:
    started = time.monotonic()
    deadline = started + max(0.0, max_wait_sec)
    latest_html = ""

    while True:
        latest_html = await page.get_content()
        body_value = await page.evaluate(
            "document.body ? document.body.innerText : ''",
            return_by_value=True,
        )
        body_text = _string_value(body_value)
        if body_text.strip():
            return latest_html, body_text, int((time.monotonic() - started) * 1000)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("nodriver rendered body remained empty after bounded hydration wait")
        await page.sleep(min(poll_interval_sec, remaining))


async def _run_async(request: dict[str, Any]) -> dict[str, object]:
    import nodriver as uc

    job_id = str(request["job_id"])
    url = str(request["url"])
    max_run_sec = int(request["max_run_sec"])
    chrome = Path(
        os.environ.get(
            "BROWSER_PLANE_CHROME",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
    )
    if not chrome.exists():
        raise FileNotFoundError(f"Chrome not found: {chrome}")

    paths = RuntimePaths.discover()
    paths.ensure()
    db = RuntimeDB(paths.db_path)
    db.initialize()
    executor = BrowserExecutor(paths, db)

    browser = await asyncio.wait_for(
        uc.start(
            headless=True,
            browser_executable_path=str(chrome),
        ),
        timeout=max_run_sec,
    )
    try:
        started = time.monotonic()
        page = await asyncio.wait_for(browser.get(url), timeout=max_run_sec)
        hydration_budget_sec = min(5.0, max(1.0, float(max_run_sec)))
        html, body_text, content_ready_wait_ms = await asyncio.wait_for(
            _wait_for_rendered_content(page, max_wait_sec=hydration_budget_sec),
            timeout=hydration_budget_sec + 2.0,
        )
        title_value = await asyncio.wait_for(
            page.evaluate("document.title", return_by_value=True),
            timeout=max_run_sec,
        )
        title = _string_value(title_value)
        status_value = await asyncio.wait_for(
            page.evaluate(
                "performance.getEntriesByType('navigation')[0]?.responseStatus || null",
                return_by_value=True,
            ),
            timeout=max_run_sec,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        status = int(status_value) if isinstance(status_value, (int, float)) else None
        result: dict[str, object] = {
            "engine": "c1-nodriver",
            "browser_engine": "nodriver",
            "url": str(page.url or url),
            "title": title,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "content_ready_wait_ms": content_ready_wait_ms,
            "text_excerpt": body_text[:4000],
        }
        result.update(executor._persist_rendered_html(job_id, html))
        return result
    finally:
        browser.stop()
        await asyncio.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal Mac Browser Plane nodriver runner")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _terminate_requested)
    signal.signal(signal.SIGINT, _terminate_requested)

    request_path = Path(args.request)
    response_path = Path(args.response)
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        import nodriver as uc

        result = uc.loop().run_until_complete(_run_async(request))
        _write_private_json(response_path, result)
        return 0
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"{type(exc).__name__}: {exc}"[:2000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
