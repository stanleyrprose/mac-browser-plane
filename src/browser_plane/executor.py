from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from .config import RuntimePaths
from .db import JobStore, RuntimeDB
from .leases import LeaseManager
from .models import Egress, JobSpec, JobState, ProfileMode, TaskType
from .processes import BrowserProcessRegistry


class CapabilityError(RuntimeError):
    pass


class BrowserExecutor:
    def __init__(self, paths: RuntimePaths, db: RuntimeDB):
        self.paths = paths
        self.db = db
        self.jobs = JobStore(db)
        self.leases = LeaseManager(db)
        self.processes = BrowserProcessRegistry(db)

    def preflight(self, spec: JobSpec) -> None:
        if spec.egress not in {Egress.AUTO, Egress.DIRECT}:
            raise CapabilityError("M1 supports direct egress only")
        if spec.task_type in {TaskType.INSPECT, TaskType.AGENT}:
            raise CapabilityError("C2/C3 are not installed in M1")
        if spec.task_type == TaskType.AUTOMATE and not self._playwright_available():
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
                result = self._run_fetch(spec)
            elif spec.task_type == TaskType.AUTOMATE:
                result = self._run_playwright(job_id, spec, profile_epoch)
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
                self.jobs.transition(
                    job_id,
                    {JobState.RUNNING},
                    JobState.FAILED,
                    failure_class="AUTOMATION_FAILED" if spec.task_type == TaskType.AUTOMATE else "FETCH_FAILED",
                    result={"error": f"{type(exc).__name__}: {exc}"},
                )
        finally:
            if profile_epoch is not None:
                self.leases.release_profile(spec.profile, job_id, profile_epoch)
        return True

    def _run_fetch(self, spec: JobSpec) -> dict[str, object]:
        request = Request(spec.url, headers={"User-Agent": "mac-browser-plane/0.1"})
        started = time.monotonic()
        with urlopen(request, timeout=spec.max_run_sec) as response:  # nosec B310: URLs are explicit job input in local M1
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

    def _run_playwright(self, job_id: str, spec: JobSpec, profile_epoch: int | None) -> dict[str, object]:
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
                runtime_kind="C1",
                profile_id=spec.profile if persistent else None,
                user_data_dir=str(user_data_dir),
            )
            if persistent and profile_epoch is not None:
                if not self.leases.bind_profile_process(spec.profile, job_id, profile_epoch, browser_process_id):
                    raise RuntimeError("profile lease fencing check failed")
            control_epoch = self.leases.acquire_control(browser_session_id, job_id, "PLAYWRIGHT")
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
                started = time.monotonic()
                response = page.goto(spec.url, wait_until="domcontentloaded", timeout=spec.max_run_sec * 1000)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                result = {
                    "engine": "c1-playwright",
                    "url": page.url,
                    "title": page.title(),
                    "status": response.status if response else None,
                    "elapsed_ms": elapsed_ms,
                    "text_excerpt": page.locator("body").inner_text(timeout=5000)[:4000],
                    "browser_process_id": browser_process_id,
                    "browser_session_id": browser_session_id,
                }
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
        (evidence_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _playwright_available() -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True
