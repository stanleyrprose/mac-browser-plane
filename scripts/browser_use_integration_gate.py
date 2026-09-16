#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Browser Use must see these before it is imported. Keep the gate local-only and
# disable upstream telemetry/logging setup explicitly.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("BROWSER_USE_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_SETUP_LOGGING", "false")
os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "critical")

import psutil

from browser_plane.config import RuntimePaths
from browser_plane.db import JobStore, RuntimeDB
from browser_plane.executor import BrowserExecutor
from browser_plane.leases import LeaseManager
from browser_plane.models import JobSpec, TaskType
from browser_plane.processes import BrowserProcessRegistry
from browser_plane.worker import Worker


FIXTURE_HTML = b"""<!doctype html>
<html lang='en'>
<head><meta charset='utf-8'><title>Browser Use Gate</title></head>
<body>
  <main aria-label='Integration gate fixture'>
    <h1>Dynamic semantic fixture</h1>
    <p id='status' role='status'>idle</p>
    <div id='mount'></div>
  </main>
  <script>
    setTimeout(() => {
      const button = document.createElement('button');
      button.setAttribute('aria-label', 'Activate semantic target');
      button.textContent = 'Activate semantic target';
      button.addEventListener('click', () => {
        document.getElementById('status').textContent = 'activated';
        button.textContent = 'Activated';
      });
      document.getElementById('mount').appendChild(button);
    }, 180);
  </script>
</body>
</html>"""


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = FIXTURE_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def make_runtime(root: Path) -> tuple[RuntimePaths, RuntimeDB, JobStore]:
    paths = RuntimePaths(
        root=root,
        state_dir=root / "state",
        evidence_dir=root / "evidence",
        profiles_dir=root / "profiles",
        auth_state_dir=root / "auth-state",
        logs_dir=root / "logs",
        run_dir=root / "run",
        db_path=root / "state" / "runtime.db",
    )
    paths.ensure()
    db = RuntimeDB(paths.db_path)
    db.initialize()
    return paths, db, JobStore(db)


def cpu_seconds(proc: psutil.Process) -> float:
    times = proc.cpu_times()
    return float(times.user + times.system)


def debug_chrome_roots() -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            command = " ".join(cmdline)
            if "Google Chrome" not in command:
                continue
            if "--remote-debugging-port" not in command:
                continue
            if "--type=" in command:
                continue
            roots.append({"pid": int(proc.info["pid"]), "command": command})
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            continue
    return roots


def text_for_node(node: Any) -> str:
    getter = getattr(node, "get_all_children_text", None)
    if getter is not None:
        try:
            return str(getter(max_depth=3))
        except TypeError:
            try:
                return str(getter())
            except Exception:
                pass
    return str(getattr(node, "node_value", "") or "")


def run_current_c3(fixture_url: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="browser-use-gate-c3-") as tmp:
        paths, db, jobs = make_runtime(Path(tmp))
        spec = JobSpec(
            task_type=TaskType.USE,
            url=fixture_url,
            max_run_sec=20,
            actions=(
                {
                    "action": "wait",
                    "role": "button",
                    "name": "Activate semantic target",
                    "state": "visible",
                    "timeout_ms": 5000,
                },
                {
                    "action": "click",
                    "role": "button",
                    "name": "Activate semantic target",
                    "timeout_ms": 5000,
                },
                {"action": "snapshot", "timeout_ms": 5000},
            ),
        )
        job_id = jobs.submit(spec)
        started = time.monotonic()
        ran = Worker(paths, db).once()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        row = jobs.get(job_id)
        if not ran or row is None:
            raise RuntimeError("current C3 baseline did not execute")
        result = json.loads(str(row.get("result_json") or "{}"))
        actions = result.get("actions") if isinstance(result, dict) else None
        snapshot = actions[-1] if isinstance(actions, list) and actions else {}
        snapshot_text = str(snapshot.get("text_excerpt") or "") if isinstance(snapshot, dict) else ""
        return {
            "job_state": row["state"],
            "elapsed_ms": elapsed_ms,
            "activated": "activated" in snapshot_text.lower(),
            "aria_snapshot_present": bool(snapshot.get("aria_snapshot")) if isinstance(snapshot, dict) else False,
            "engine": result.get("engine"),
            "browser_engine": result.get("browser_engine"),
            "actions": len(actions) if isinstance(actions, list) else 0,
        }


async def run_browser_use_attach(
    *,
    fixture_url: str,
    paths: RuntimePaths,
    db: RuntimeDB,
) -> dict[str, Any]:
    python_proc = psutil.Process(os.getpid())
    rss_before_import = python_proc.memory_info().rss
    cpu_before_import = cpu_seconds(python_proc)
    import_started = time.monotonic()

    from browser_use import BrowserSession
    from browser_use.browser.events import ClickElementEvent

    import_ms = int((time.monotonic() - import_started) * 1000)
    rss_after_import = python_proc.memory_info().rss
    cpu_after_import = cpu_seconds(python_proc)

    chrome = Path(
        os.environ.get(
            "BROWSER_PLANE_CHROME",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
    )
    if not chrome.exists():
        raise RuntimeError(f"Chrome not found: {chrome}")

    user_data_dir = Path(tempfile.mkdtemp(prefix="browser-use-gate-chrome-", dir=paths.run_dir))
    proc = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=0",
            f"--user-data-dir={user_data_dir}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    registry = BrowserProcessRegistry(db)
    leases = LeaseManager(db)
    job_id = f"browser-use-gate-{uuid.uuid4()}"
    browser_session_id = str(uuid.uuid4())
    browser_process_id: str | None = None
    control_epoch: int | None = None
    session: Any | None = None

    try:
        browser_process_id = registry.register(
            pid=proc.pid,
            job_id=job_id,
            runtime_kind="EXPERIMENT_BROWSER_USE_GATE",
            profile_id=None,
            user_data_dir=str(user_data_dir),
        )
        control_epoch = leases.acquire_control(
            browser_session_id,
            job_id,
            "BROWSER_USE_GATE",
            ttl_sec=30,
        )
        if control_epoch is None:
            raise RuntimeError("gate could not acquire Browser Plane control lease")
        competing_epoch = leases.acquire_control(
            browser_session_id,
            "competing-job",
            "BROWSER_USE_GATE",
            ttl_sec=30,
        )
        lease_second_owner_denied = competing_epoch is None

        endpoint = BrowserExecutor._wait_for_cdp(user_data_dir, proc, timeout_sec=10)
        roots_before_attach = debug_chrome_roots()
        owned_alive_before_attach = registry.verify_owned(browser_process_id)
        rss_before_attach = python_proc.memory_info().rss
        cpu_before_attach = cpu_seconds(python_proc)
        attach_started = time.monotonic()

        session = BrowserSession(
            cdp_url=endpoint,
            allowed_domains=["127.0.0.1"],
            keep_alive=True,
            highlight_elements=False,
            dom_highlight_elements=False,
        )
        await session.start()
        attach_ms = int((time.monotonic() - attach_started) * 1000)
        await session.navigate_to(fixture_url)
        await asyncio.sleep(0.35)

        state_started = time.monotonic()
        state = await session.get_browser_state_summary(include_screenshot=False, cached=False)
        state_ms = int((time.monotonic() - state_started) * 1000)
        selector_map = state.dom_state.selector_map if state.dom_state is not None else {}

        target_index: int | None = None
        target_node: Any | None = None
        for index, node in selector_map.items():
            attrs = getattr(node, "attributes", {}) or {}
            if attrs.get("aria-label") == "Activate semantic target" or "Activate semantic target" in text_for_node(node):
                target_index = int(index)
                target_node = node
                break
        if target_node is None:
            raise RuntimeError("Browser Use state did not expose the semantic target")

        click_started = time.monotonic()
        click_event = session.event_bus.dispatch(ClickElementEvent(node=target_node))
        await click_event
        await click_event.event_result(raise_if_any=True, raise_if_none=False)
        click_ms = int((time.monotonic() - click_started) * 1000)
        await asyncio.sleep(0.1)

        after_state = await session.get_browser_state_summary(include_screenshot=False, cached=False)
        after_repr = after_state.dom_state.llm_representation() if after_state.dom_state is not None else ""
        activated = "activated" in after_repr.lower()

        roots_after_action = debug_chrome_roots()
        rss_after_action = python_proc.memory_info().rss
        cpu_after_action = cpu_seconds(python_proc)
        resolved_cdp_url = str(session.cdp_url)
        endpoint_parts = urlparse(endpoint)
        resolved_parts = urlparse(resolved_cdp_url)
        endpoint_matches = (
            endpoint_parts.hostname == resolved_parts.hostname
            and endpoint_parts.port == resolved_parts.port
        )

        await session.stop()
        session = None
        await asyncio.sleep(0.1)
        chrome_alive_after_session_stop = proc.poll() is None and registry.verify_owned(browser_process_id)

        return {
            "browser_use_version": __import__("importlib.metadata").metadata.version("browser-use"),
            "cdp_endpoint": endpoint,
            "browser_use_cdp_url": resolved_cdp_url,
            "endpoint_matches": endpoint_matches,
            "owned_alive_before_attach": owned_alive_before_attach,
            "chrome_alive_after_session_stop": chrome_alive_after_session_stop,
            "lease_second_owner_denied": lease_second_owner_denied,
            "selector_count": len(selector_map),
            "target_index": target_index,
            "target_exposed": target_node is not None,
            "activated": activated,
            "import_ms": import_ms,
            "attach_ms": attach_ms,
            "state_ms": state_ms,
            "click_ms": click_ms,
            "rss_before_import_bytes": rss_before_import,
            "rss_after_import_bytes": rss_after_import,
            "rss_import_delta_bytes": rss_after_import - rss_before_import,
            "rss_before_attach_bytes": rss_before_attach,
            "rss_after_action_bytes": rss_after_action,
            "rss_attach_action_delta_bytes": rss_after_action - rss_before_attach,
            "cpu_import_delta_sec": round(cpu_after_import - cpu_before_import, 4),
            "cpu_attach_action_delta_sec": round(cpu_after_action - cpu_before_attach, 4),
            "debug_chrome_roots_before_attach": len(roots_before_attach),
            "debug_chrome_roots_after_action": len(roots_after_action),
            "debug_chrome_root_delta": len(roots_after_action) - len(roots_before_attach),
            "telemetry_env": {
                "ANONYMIZED_TELEMETRY": os.environ.get("ANONYMIZED_TELEMETRY"),
                "BROWSER_USE_TELEMETRY": os.environ.get("BROWSER_USE_TELEMETRY"),
                "BROWSER_USE_SETUP_LOGGING": os.environ.get("BROWSER_USE_SETUP_LOGGING"),
            },
        }
    finally:
        if session is not None:
            try:
                await session.stop()
            except Exception:
                pass
        if control_epoch is not None:
            leases.release_control(browser_session_id, job_id, control_epoch)
        if browser_process_id is not None:
            if proc.poll() is None:
                registry.terminate_owned(browser_process_id, grace_sec=2.0)
            else:
                registry.mark_closed(browser_process_id)
        elif proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            for child in user_data_dir.iterdir():
                pass
        except OSError:
            pass
        import shutil

        shutil.rmtree(user_data_dir, ignore_errors=True)


def decide_gates(c3: dict[str, Any], browser_use: dict[str, Any]) -> dict[str, Any]:
    gate1_pass = all(
        (
            browser_use.get("endpoint_matches"),
            browser_use.get("owned_alive_before_attach"),
            browser_use.get("chrome_alive_after_session_stop"),
            browser_use.get("debug_chrome_root_delta") == 0,
            browser_use.get("target_exposed"),
            browser_use.get("activated"),
        )
    )
    gate2_pass = bool(browser_use.get("lease_second_owner_denied"))

    # Gate 3 is an adoption gate, not merely "we measured it". Import/attach must
    # remain bounded, but dependency footprint is assessed separately in the report.
    rss_delta = int(browser_use.get("rss_import_delta_bytes") or 0) + int(
        browser_use.get("rss_attach_action_delta_bytes") or 0
    )
    gate3_pass = rss_delta < 256 * 1024 * 1024 and browser_use.get("debug_chrome_root_delta") == 0

    # Current C3 already completes role/name targeting + dynamic wait + click +
    # bounded ARIA snapshot on the same fixture. The Browser Use gate demonstrates
    # a richer model-facing DOM representation, but not a material new execution
    # capability on this workload.
    c3_equivalent = bool(c3.get("activated") and c3.get("aria_snapshot_present"))
    browser_use_success = bool(browser_use.get("activated") and browser_use.get("target_exposed"))
    gate4_pass = browser_use_success and not c3_equivalent

    return {
        "gate_1_existing_cdp_reuse": "PASS" if gate1_pass else "FAIL",
        "gate_2_lease_compatibility": "PASS" if gate2_pass else "FAIL",
        "gate_3_runtime_resource_overhead": "PASS" if gate3_pass else "FAIL",
        "gate_4_material_capability_gain": "PASS" if gate4_pass else "FAIL",
        "overall_promote_to_production": bool(gate1_pass and gate2_pass and gate3_pass and gate4_pass),
        "rationale": (
            "Browser Use is technically attachable behind Browser Plane ownership, but promotion requires a material "
            "capability gain over current deterministic C3; this fixture does not demonstrate one."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Experimental Browser Use -> Mac Browser Plane integration gate")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON only")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    fixture_url = f"http://127.0.0.1:{server.server_address[1]}/"

    try:
        c3 = run_current_c3(fixture_url)
        with tempfile.TemporaryDirectory(prefix="browser-use-gate-runtime-") as tmp:
            paths, db, _ = make_runtime(Path(tmp))
            browser_use = asyncio.run(run_browser_use_attach(fixture_url=fixture_url, paths=paths, db=db))
        gates = decide_gates(c3, browser_use)
        report = {
            "fixture_url": fixture_url,
            "current_c3": c3,
            "browser_use": browser_use,
            "gates": gates,
        }
        print(json.dumps(report, indent=None if args.json else 2, sort_keys=True))
        return 0 if not any(value == "UNKNOWN" for value in gates.values()) else 2
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
