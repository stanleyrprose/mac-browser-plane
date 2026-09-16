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
        await asyncio.wait_for(page.sleep(0.5), timeout=max_run_sec)
        html = await asyncio.wait_for(page.get_content(), timeout=max_run_sec)
        title = await asyncio.wait_for(
            page.evaluate("document.title", return_by_value=True),
            timeout=max_run_sec,
        )
        body_text = await asyncio.wait_for(
            page.evaluate(
                "document.body ? document.body.innerText : ''",
                return_by_value=True,
            ),
            timeout=max_run_sec,
        )
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
            "title": title if isinstance(title, str) else "",
            "status": status,
            "elapsed_ms": elapsed_ms,
            "text_excerpt": body_text[:4000] if isinstance(body_text, str) else "",
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
