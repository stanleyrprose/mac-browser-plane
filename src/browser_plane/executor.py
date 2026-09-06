from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .leases import LeaseManager
from .models import Egress, JobSpec, JobState, ProfileMode, TaskType
from .processes import BrowserProcessRegistry


class CapabilityError(RuntimeError):
    pass


class BrowserExecutor:
    READ_ONLY_CDP_METHODS = frozenset(
        {
            "Accessibility.getFullAXTree",
            "Page.getNavigationHistory",
            "Performance.enable",
            "Performance.getMetrics",
        }
    )

    def __init__(self, paths: RuntimePaths, db: RuntimeDB):
        self.paths = paths
        self.db = db
        self.jobs = JobStore(db)
        self.leases = LeaseManager(db)
        self.processes = BrowserProcessRegistry(db)

    def preflight(self, spec: JobSpec) -> None:
        if spec.egress not in {Egress.AUTO, Egress.DIRECT}:
            raise CapabilityError("M1 supports direct egress only")
        if spec.task_type == TaskType.AGENT:
            raise CapabilityError("autonomous Browser Agent is not installed")
        if spec.task_type in {TaskType.AUTOMATE, TaskType.INSPECT, TaskType.USE} and not self._playwright_available():
            raise CapabilityError("Playwright Python package is not installed")

    def run_one(self, row: dict[str, object]) -> bool:
        job_id = str(row["job_id"])
        spec = JobSpec.from_mapping(json.loads(str(row["spec_json"])))
        try:
            self.preflight(spec)
        except CapabilityError as exc:
            self.jobs.transition(
                job_id,
                {JobState.QUEUED, JobState.WAITING_RESOURCE},
                JobState.FAILED,
                failure_class="CAPABILITY_COMBINATION_INVALID",
                result={"error": str(exc)},
            )
            return True

        profile_epoch: int | None = None
        if spec.profile_mode == ProfileMode.EXCLUSIVE_PERSISTENT:
            profile_epoch = self.leases.acquire_profile(spec.profile, job_id)
            if profile_epoch is None:
                if JobState(str(row["state"])) == JobState.QUEUED:
                    self.jobs.transition(job_id, {JobState.QUEUED}, JobState.WAITING_RESOURCE)
                return False

        if not self.jobs.transition(
            job_id,
            {JobState.QUEUED, JobState.WAITING_RESOURCE},
            JobState.RUNNING,
        ):
            if profile_epoch is not None:
                self.leases.release_profile(spec.profile, job_id, profile_epoch)
            return False

        try:
            if spec.task_type == TaskType.FETCH:
                result = self._run_fetch(job_id, spec)
            elif spec.task_type == TaskType.AUTOMATE:
                result = self._run_playwright(job_id, spec, profile_epoch)
            elif spec.task_type == TaskType.INSPECT:
                result = self._run_playwright(job_id, spec, profile_epoch, inspect_mode=True)
            elif spec.task_type == TaskType.USE:
                result = self._run_playwright(job_id, spec, profile_epoch, use_mode=True)
            else:
                raise CapabilityError(f"unsupported task type {spec.task_type}")
            self._write_evidence(job_id, result)
            current = self.jobs.get(job_id)
            if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                self.jobs.transition(
                    job_id,
                    {JobState.CANCEL_REQUESTED},
                    JobState.CANCELLED,
                    result=result,
                    partial_effect_possible=True,
                )
            else:
                self.jobs.transition(job_id, {JobState.RUNNING}, JobState.SUCCEEDED, result=result)
        except TimeoutError as exc:
            current = self.jobs.get(job_id)
            if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                self.jobs.transition(
                    job_id,
                    {JobState.CANCEL_REQUESTED},
                    JobState.CANCELLED,
                    result={"error": str(exc)},
                    partial_effect_possible=True,
                )
            else:
                self.jobs.transition(
                    job_id,
                    {JobState.RUNNING},
                    JobState.EXECUTION_TIMEOUT,
                    failure_class="EXECUTION_TIMEOUT",
                    result={"error": str(exc)},
                    partial_effect_possible=spec.task_type == TaskType.USE,
                )
        except Exception as exc:
            current = self.jobs.get(job_id)
            if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                self.jobs.transition(
                    job_id,
                    {JobState.CANCEL_REQUESTED},
                    JobState.CANCELLED,
                    result={"error": f"{type(exc).__name__}: {exc}"},
                    partial_effect_possible=True,
                )
            else:
                failure_class = {
                    TaskType.AUTOMATE: "AUTOMATION_FAILED",
                    TaskType.INSPECT: "INSPECT_FAILED",
                    TaskType.USE: "BROWSER_USE_FAILED",
                }.get(spec.task_type, "FETCH_FAILED")
                self.jobs.transition(
                    job_id,
                    {JobState.RUNNING},
                    JobState.FAILED,
                    failure_class=failure_class,
                    result={"error": f"{type(exc).__name__}: {exc}"},
                    partial_effect_possible=spec.task_type == TaskType.USE,
                )
        finally:
            if profile_epoch is not None:
                self.leases.release_profile(spec.profile, job_id, profile_epoch)
        return True

    def _run_fetch(self, job_id: str, spec: JobSpec) -> dict[str, object]:
        if spec.url.startswith("data:"):
            request = Request(spec.url, headers={"User-Agent": "mac-browser-plane/0.1"})
            started = time.monotonic()
            with urlopen(request, timeout=spec.max_run_sec) as response:  # nosec B310: local test fixture only
                body = response.read(1_000_000)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return {
                    "engine": "c0-fetch",
                    "url": response.geturl(),
                    "status": getattr(response, "status", 200),
                    "elapsed_ms": elapsed_ms,
                    "content_type": response.headers.get("Content-Type"),
                    "body_bytes": len(body),
                    "text_excerpt": body.decode("utf-8", errors="replace")[:4000],
                }

        if not spec.url.startswith(("http://", "https://")):
            raise CapabilityError("C0 supports only http/https URLs")

        curl = Path("/usr/bin/curl")
        if not curl.exists():
            raise CapabilityError("system curl not found: /usr/bin/curl")
        with tempfile.TemporaryDirectory(prefix="c0-fetch-", dir=self.paths.run_dir) as tmp:
            body_path = Path(tmp) / "body.bin"
            started = time.monotonic()
            proc = subprocess.run(
                [
                    str(curl),
                    "--silent",
                    "--show-error",
                    "--location",
                    "--max-time",
                    str(spec.max_run_sec),
                    "--max-filesize",
                    "1000000",
                    "--user-agent",
                    "mac-browser-plane/0.1",
                    "--output",
                    str(body_path),
                    "--write-out",
                    "%{http_code}\\n%{url_effective}\\n%{content_type}\\n",
                    spec.url,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=spec.max_run_sec + 5,
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if proc.returncode != 0:
                raise RuntimeError(f"curl failed ({proc.returncode}): {proc.stderr.strip()[:1000]}")
            metadata = proc.stdout.splitlines()
            if len(metadata) < 2:
                raise RuntimeError("curl returned incomplete metadata")
            body = body_path.read_bytes() if body_path.exists() else b""
            content_type = metadata[2] if len(metadata) > 2 and metadata[2] else None
            result: dict[str, object] = {
                "engine": "c0-fetch",
                "url": metadata[1],
                "status": int(metadata[0]),
                "elapsed_ms": elapsed_ms,
                "content_type": content_type,
                "body_bytes": len(body),
            }
            evidence_dir = self.paths.evidence_dir / job_id
            evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            evidence_dir.chmod(0o700)
            artifact_path = evidence_dir / f"response{self._artifact_suffix(content_type, metadata[1])}"
            shutil.copy2(body_path, artifact_path)
            artifact_path.chmod(0o600)
            result["artifact_path"] = str(artifact_path)
            result["sha256"] = hashlib.sha256(body).hexdigest()
            if self._is_textual_content(content_type):
                result["text_excerpt"] = body.decode("utf-8", errors="replace")[:4000]
            return result

    @staticmethod
    def _artifact_suffix(content_type: str | None, url: str) -> str:
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        mapped = {
            "text/html": ".html",
            "text/plain": ".txt",
            "application/json": ".json",
            "application/ld+json": ".json",
            "application/xml": ".xml",
            "application/xhtml+xml": ".html",
            "application/pdf": ".pdf",
        }.get(media_type)
        if mapped:
            return mapped
        suffix = Path(urlsplit(url).path).suffix.lower()
        return suffix if suffix and len(suffix) <= 10 else ".bin"

    @staticmethod
    def _is_textual_content(content_type: str | None) -> bool:
        if not content_type:
            return False
        media_type = content_type.split(";", 1)[0].strip().lower()
        return media_type.startswith("text/") or media_type in {
            "application/json",
            "application/ld+json",
            "application/xml",
            "application/xhtml+xml",
        }

    def _run_playwright(
        self,
        job_id: str,
        spec: JobSpec,
        profile_epoch: int | None,
        *,
        inspect_mode: bool = False,
        use_mode: bool = False,
    ) -> dict[str, object]:
        if inspect_mode and use_mode:
            raise CapabilityError("inspect_mode and use_mode are mutually exclusive")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CapabilityError("Playwright is not installed") from exc

        persistent = spec.profile_mode == ProfileMode.EXCLUSIVE_PERSISTENT
        if persistent:
            user_data_dir = self.paths.profiles_dir / spec.profile
            user_data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            remove_dir = False
        else:
            user_data_dir = Path(tempfile.mkdtemp(prefix=f"job-{job_id}-", dir=self.paths.run_dir))
            remove_dir = True

        chrome = Path(os.environ.get("BROWSER_PLANE_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
        if not chrome.exists():
            raise CapabilityError(f"Chrome not found: {chrome}")

        # Persistent profiles retain Chrome's previous random CDP discovery file.
        # Under the exclusive Profile Lease it is safe to remove only this runtime
        # discovery artifact before launching a new owned Chrome. Never delete
        # SingletonLock/SingletonCookie as a recovery shortcut.
        self._clear_stale_cdp_discovery(user_data_dir)

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
        browser_process_id: str | None = None
        control_epoch: int | None = None
        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        browser_session_id = str(uuid.uuid4())
        try:
            browser_process_id = self.processes.register(
                pid=proc.pid,
                job_id=job_id,
                runtime_kind="C3" if use_mode else ("C2" if inspect_mode else "C1"),
                profile_id=spec.profile if persistent else None,
                user_data_dir=str(user_data_dir),
            )
            if persistent and profile_epoch is not None:
                if not self.leases.bind_profile_process(spec.profile, job_id, profile_epoch, browser_process_id):
                    raise RuntimeError("profile lease fencing check failed")
            control_epoch = self.leases.acquire_control(
                browser_session_id,
                job_id,
                "PLAYWRIGHT_USE" if use_mode else ("DEVTOOLS_READ" if inspect_mode else "PLAYWRIGHT"),
            )
            if control_epoch is None:
                raise RuntimeError("control lease unavailable")

            def heartbeat() -> None:
                while not heartbeat_stop.wait(5.0):
                    if persistent and profile_epoch is not None:
                        self.leases.heartbeat_profile(spec.profile, job_id, profile_epoch)
                    if control_epoch is not None:
                        self.leases.heartbeat_control(browser_session_id, job_id, control_epoch)
                    current = self.jobs.get(job_id)
                    if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                        if browser_process_id is not None:
                            self.processes.terminate_owned(browser_process_id, grace_sec=1.0)
                        return

            heartbeat_thread = threading.Thread(target=heartbeat, name=f"lease-heartbeat-{job_id}", daemon=True)
            heartbeat_thread.start()

            endpoint = self._wait_for_cdp(user_data_dir, proc, timeout_sec=10)
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(endpoint)
                context = browser.contexts[0] if browser.contexts else browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.pages[0] if context.pages else context.new_page()
                page.set_viewport_size({"width": 1440, "height": 900})

                console_messages: list[dict[str, str]] = []
                requests: list[dict[str, str]] = []
                responses: list[dict[str, object]] = []
                if inspect_mode:
                    page.on(
                        "console",
                        lambda msg: console_messages.append({"type": msg.type, "text": msg.text})
                        if len(console_messages) < 100
                        else None,
                    )
                    page.on(
                        "request",
                        lambda req: requests.append(
                            {"method": req.method, "url": req.url, "resource_type": req.resource_type}
                        )
                        if len(requests) < 200
                        else None,
                    )
                    page.on(
                        "response",
                        lambda resp: responses.append({"status": resp.status, "url": resp.url})
                        if len(responses) < 200
                        else None,
                    )

                started = time.monotonic()
                response = page.goto(spec.url, wait_until="domcontentloaded", timeout=spec.max_run_sec * 1000)
                action_results: list[dict[str, object]] = []
                if use_mode:
                    action_results = self._run_browser_actions(page, job_id, spec.actions)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                status = response.status if response else None
                for action_result in reversed(action_results):
                    if "status" in action_result:
                        status = action_result["status"]
                        break
                result: dict[str, object] = {
                    "engine": "c3-browser-use" if use_mode else ("c2-readonly-inspect" if inspect_mode else "c1-playwright"),
                    "url": page.url,
                    "title": page.title(),
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "text_excerpt": page.locator("body").inner_text(timeout=5000)[:4000],
                    "browser_process_id": browser_process_id,
                    "browser_session_id": browser_session_id,
                }
                if use_mode:
                    result["actions"] = action_results

                if inspect_mode:
                    cdp = context.new_cdp_session(page)
                    try:
                        navigation = self._readonly_cdp_send(cdp, "Page.getNavigationHistory")
                        self._readonly_cdp_send(cdp, "Performance.enable")
                        performance = self._readonly_cdp_send(cdp, "Performance.getMetrics")
                        accessibility = self._readonly_cdp_send(cdp, "Accessibility.getFullAXTree")
                    finally:
                        cdp.detach()
                    evidence_dir = self.paths.evidence_dir / job_id
                    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    screenshot_path = evidence_dir / "screenshot.png"
                    page.screenshot(path=str(screenshot_path), full_page=False)
                    screenshot_path.chmod(0o600)
                    result["console"] = console_messages
                    result["requests"] = requests
                    result["responses"] = responses
                    result["cdp"] = {
                        "navigation_history": navigation,
                        "performance_metrics": performance,
                        "accessibility_node_count": len(accessibility.get("nodes", [])),
                    }
                    result["screenshot"] = str(screenshot_path)

                browser.close()
                return result
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)
            if control_epoch is not None:
                self.leases.release_control(browser_session_id, job_id, control_epoch)
            if browser_process_id is not None:
                if proc.poll() is None:
                    self.processes.terminate_owned(browser_process_id)
                else:
                    self.processes.mark_closed(browser_process_id)
            elif proc.poll() is None:
                proc.terminate()
            if remove_dir:
                shutil.rmtree(user_data_dir, ignore_errors=True)

    def _run_browser_actions(
        self,
        page: Any,
        job_id: str,
        actions: tuple[dict[str, Any], ...],
    ) -> list[dict[str, object]]:
        if not actions:
            raise CapabilityError("C3 Browser Use requires at least one action")
        if len(actions) > 50:
            raise CapabilityError("C3 Browser Use supports at most 50 actions per job")

        evidence_dir = self.paths.evidence_dir / job_id
        results: list[dict[str, object]] = []
        for index, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                raise CapabilityError(f"browser action {index} must be an object")
            kind = str(action.get("action", "")).strip().lower()
            timeout_ms = int(action.get("timeout_ms", 10_000))
            if timeout_ms < 1 or timeout_ms > 60_000:
                raise CapabilityError(f"browser action {index} timeout_ms must be between 1 and 60000")

            try:
                if kind == "navigate":
                    target = str(action.get("url", "")).strip()
                    parsed = urlsplit(target)
                    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                        raise CapabilityError("navigate requires an absolute http(s) URL")
                    wait_until = str(action.get("wait_until", "domcontentloaded"))
                    if wait_until not in {"commit", "domcontentloaded", "load", "networkidle"}:
                        raise CapabilityError("navigate wait_until is invalid")
                    response = page.goto(target, wait_until=wait_until, timeout=timeout_ms)
                    item: dict[str, object] = {
                        "step": index,
                        "action": kind,
                        "url": page.url,
                        "status": response.status if response else None,
                    }
                elif kind == "click":
                    selector = str(action.get("selector", "")).strip()
                    if not selector:
                        raise CapabilityError("click requires selector")
                    force = bool(action.get("force", False))
                    page.locator(selector).click(timeout=timeout_ms, force=force)
                    item = {
                        "step": index,
                        "action": kind,
                        "selector": selector,
                        "force": force,
                        "url": page.url,
                    }
                elif kind == "type":
                    selector = str(action.get("selector", "")).strip()
                    if not selector:
                        raise CapabilityError("type requires selector")
                    text = str(action.get("text", ""))
                    page.locator(selector).fill(text, timeout=timeout_ms)
                    item = {"step": index, "action": kind, "selector": selector, "chars": len(text)}
                elif kind == "select":
                    selector = str(action.get("selector", "")).strip()
                    if not selector or "value" not in action:
                        raise CapabilityError("select requires selector and value")
                    force = bool(action.get("force", False))
                    selected = page.locator(selector).select_option(
                        value=str(action["value"]), timeout=timeout_ms, force=force
                    )
                    item = {
                        "step": index,
                        "action": kind,
                        "selector": selector,
                        "force": force,
                        "selected": list(selected),
                    }
                elif kind == "press":
                    key = str(action.get("key", "")).strip()
                    if not key:
                        raise CapabilityError("press requires key")
                    selector = str(action.get("selector", "")).strip()
                    if selector:
                        page.locator(selector).press(key, timeout=timeout_ms)
                    else:
                        page.keyboard.press(key)
                    item = {"step": index, "action": kind, "key": key, "selector": selector or None}
                elif kind == "wait":
                    selector = str(action.get("selector", "")).strip()
                    if selector:
                        state = str(action.get("state", "visible"))
                        if state not in {"attached", "detached", "visible", "hidden"}:
                            raise CapabilityError("wait state is invalid")
                        page.locator(selector).wait_for(state=state, timeout=timeout_ms)
                        item = {"step": index, "action": kind, "selector": selector, "state": state}
                    else:
                        wait_ms = int(action.get("ms", 1000))
                        if wait_ms < 0 or wait_ms > 30_000:
                            raise CapabilityError("wait ms must be between 0 and 30000")
                        page.wait_for_timeout(wait_ms)
                        item = {"step": index, "action": kind, "ms": wait_ms}
                elif kind == "snapshot":
                    item = {
                        "step": index,
                        "action": kind,
                        "url": page.url,
                        "title": page.title(),
                        "text_excerpt": page.locator("body").inner_text(timeout=timeout_ms)[:4000],
                    }
                elif kind == "screenshot":
                    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    evidence_dir.chmod(0o700)
                    screenshot_path = evidence_dir / f"screenshot-{index}.png"
                    page.screenshot(path=str(screenshot_path), full_page=bool(action.get("full_page", False)))
                    screenshot_path.chmod(0o600)
                    item = {"step": index, "action": kind, "path": str(screenshot_path)}
                elif kind == "download":
                    selector = str(action.get("selector", "")).strip()
                    if not selector:
                        raise CapabilityError("download requires selector")
                    with page.expect_download(timeout=timeout_ms) as download_info:
                        page.locator(selector).click(timeout=timeout_ms)
                    download = download_info.value
                    raw_name = str(action.get("filename") or download.suggested_filename or f"download-{index}.bin")
                    safe_name = Path(raw_name).name
                    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe_name)[:180]
                    if not safe_name or safe_name in {".", ".."}:
                        safe_name = f"download-{index}.bin"
                    downloads_dir = evidence_dir / "downloads"
                    downloads_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    downloads_dir.chmod(0o700)
                    target = downloads_dir / safe_name
                    download.save_as(str(target))
                    target.chmod(0o600)
                    with target.open("rb") as handle:
                        digest = hashlib.file_digest(handle, "sha256").hexdigest()
                    item = {
                        "step": index,
                        "action": kind,
                        "selector": selector,
                        "path": str(target),
                        "bytes": target.stat().st_size,
                        "sha256": digest,
                    }
                else:
                    raise CapabilityError(f"unsupported browser action: {kind or '<missing>'}")
            except Exception as exc:
                if isinstance(exc, CapabilityError):
                    raise
                raise RuntimeError(f"browser action {index} ({kind or '<missing>'}) failed: {exc}") from exc
            results.append(item)

        return results

    @classmethod
    def _readonly_cdp_send(cls, session: Any, method: str) -> dict[str, Any]:
        if method not in cls.READ_ONLY_CDP_METHODS:
            raise CapabilityError(f"CDP method is not allowed in R1 read-only inspect: {method}")
        return dict(session.send(method))

    @staticmethod
    def _clear_stale_cdp_discovery(user_data_dir: Path) -> None:
        active_port = user_data_dir / "DevToolsActivePort"
        if active_port.exists():
            active_port.unlink()

    @staticmethod
    def _wait_for_cdp(user_data_dir: Path, proc: subprocess.Popen[bytes], timeout_sec: float) -> str:
        active_port = user_data_dir / "DevToolsActivePort"
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"Chrome exited before CDP became ready: {proc.returncode}")
            if active_port.exists():
                lines = active_port.read_text(encoding="utf-8").splitlines()
                if lines:
                    return f"http://127.0.0.1:{int(lines[0])}"
            time.sleep(0.05)
        raise TimeoutError("Chrome CDP did not become ready")

    def _write_evidence(self, job_id: str, result: dict[str, object]) -> None:
        evidence_dir = self.paths.evidence_dir / job_id
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        evidence_dir.chmod(0o700)
        target = evidence_dir / "result.json"
        target.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        target.chmod(0o600)

    @staticmethod
    def _playwright_available() -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True
