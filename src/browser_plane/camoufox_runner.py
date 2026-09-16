from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

from .config import RuntimePaths
from .content_quality import c1_content_quality_metadata, wait_for_sync_c1_content
from .db import RuntimeDB
from .executor import BrowserExecutor


def _terminate_requested(_signum: int, _frame: object) -> None:
    raise SystemExit(143)


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _run(request: dict[str, Any]) -> dict[str, object]:
    from camoufox.sync_api import Camoufox

    job_id = str(request["job_id"])
    url = str(request["url"])
    max_run_sec = int(request["max_run_sec"])
    use_mode = bool(request.get("use_mode", False))
    raw_actions = request.get("actions", [])
    if not isinstance(raw_actions, list):
        raise ValueError("actions must be a list")
    actions = tuple(dict(action) for action in raw_actions)

    paths = RuntimePaths.discover()
    paths.ensure()
    db = RuntimeDB(paths.db_path)
    db.initialize()
    executor = BrowserExecutor(paths, db)

    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        started = time.monotonic()
        response = page.goto(url, wait_until="domcontentloaded", timeout=max_run_sec * 1000)
        action_results: list[dict[str, object]] = []
        if use_mode:
            action_results = executor._run_browser_actions(
                page,
                job_id,
                actions,
                browser_engine="camoufox",
            )
        c1_html: str | None = None
        c1_body_text: str | None = None
        c1_ready_wait_ms: int | None = None
        if not use_mode:
            c1_html, c1_body_text, c1_ready_wait_ms = wait_for_sync_c1_content(
                page,
                engine="camoufox",
                max_wait_sec=min(5.0, max(1.0, float(max_run_sec))),
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        status = response.status if response else None
        for action_result in reversed(action_results):
            if "status" in action_result:
                status = action_result["status"]
                break

        body = page.locator("body")
        text_excerpt = (
            c1_body_text[:4000]
            if c1_body_text is not None
            else body.inner_text(timeout=5000)[:4000]
        )
        result: dict[str, object] = {
            "engine": "c3-camoufox-use" if use_mode else "c1-camoufox",
            "browser_engine": "camoufox",
            "url": page.url,
            "title": page.title(),
            "status": status,
            "elapsed_ms": elapsed_ms,
            "text_excerpt": text_excerpt,
        }
        if use_mode:
            result["actions"] = action_results
        else:
            assert c1_html is not None and c1_body_text is not None and c1_ready_wait_ms is not None
            result.update(c1_content_quality_metadata(c1_body_text, wait_ms=c1_ready_wait_ms))
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal Mac Browser Plane Camoufox runner")
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
        result = _run(request)
        _write_private_json(response_path, result)
        return 0
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"{type(exc).__name__}: {exc}"[:2000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
