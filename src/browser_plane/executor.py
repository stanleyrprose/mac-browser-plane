from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from html.parser import HTMLParser
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .c3_failure_corpus import C3FailureCorpus
from .config import RuntimePaths
from .content_quality import c1_content_quality_metadata, require_nonempty_c1_body, wait_for_sync_c1_content
from .db import JobStore, RuntimeDB
from .leases import LeaseManager
from .models import BrowserEngine, Egress, JobSpec, JobState, ProfileMode, TaskType
from .processes import BrowserProcessRegistry


MAX_RENDERED_ARTIFACT_BYTES = 10_000_000

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "code",
        "key",
        "password",
        "secret",
        "session",
        "signature",
        "sig",
        "token",
    }
)
_API_NOISE_HOST_SUFFIXES = (
    "doubleclick.net",
    "google-analytics.com",
    "googletagmanager.com",
)
_API_NOISE_PATH_MARKERS = ("/captcha/", "/telemetry/", "/tracking/")


def _safe_network_candidate_url(url: str) -> str:
    split = urlsplit(url)
    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _SENSITIVE_QUERY_KEYS or any(marker in lowered for marker in ("token", "secret", "password", "signature")):
            value = "REDACTED"
        query.append((key, value))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), ""))


def derive_api_candidates(
    page_url: str,
    requests: list[dict[str, str]],
    responses: list[dict[str, object]],
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    """Derive likely application-data endpoints from C2 network metadata.

    This is intentionally heuristic and evidence-only. It never reads response bodies
    and does not imply that a candidate is stable enough for production acquisition.
    """
    page_host = (urlsplit(page_url).hostname or "").lower()
    response_by_url = {str(item.get("url") or ""): item for item in responses}
    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for request in requests:
        resource_type = str(request.get("resource_type") or "").lower()
        if resource_type not in {"xhr", "fetch"}:
            continue
        raw_url = str(request.get("url") or "")
        split = urlsplit(raw_url)
        host = (split.hostname or "").lower()
        path = split.path or "/"
        path_lower = path.lower()
        response = response_by_url.get(raw_url, {})
        content_type = str(response.get("content_type") or "").split(";", 1)[0].strip().lower()
        same_origin = bool(page_host and host == page_host)
        reasons: list[str] = [resource_type]
        score = 0

        if same_origin:
            score += 3
            reasons.append("same_origin")
        if path_lower.startswith("/api/") or "/api/" in path_lower or "graphql" in path_lower:
            score += 3
            reasons.append("api_path")
        if content_type == "application/json" or content_type.endswith("+json"):
            score += 3
            reasons.append("json_response")
        if str(request.get("method") or "GET").upper() != "GET":
            score += 1
            reasons.append("non_get")

        if any(host == suffix or host.endswith("." + suffix) for suffix in _API_NOISE_HOST_SUFFIXES):
            continue
        if any(marker in path_lower for marker in _API_NOISE_PATH_MARKERS):
            continue
        if score < 3:
            continue

        method = str(request.get("method") or "GET").upper()
        safe_url = _safe_network_candidate_url(raw_url)
        identity = (method, safe_url)
        if identity in seen:
            continue
        seen.add(identity)

        candidates.append(
            {
                "score": score,
                "method": method,
                "url": safe_url,
                "resource_type": resource_type,
                "status": response.get("status"),
                "content_type": content_type or None,
                "same_origin": same_origin,
                "reasons": reasons,
            }
        )

    candidates.sort(key=lambda item: (-int(item["score"]), str(item["url"])))
    return candidates[: max(0, limit)]


class CapabilityError(RuntimeError):
    pass


class _RenderedHTMLTextParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._in_body = False
        self._skip_depth = 0
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name == "title":
            self._in_title = True
        if name == "body":
            self._in_body = True
        elif self._in_body and name in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self._in_title = False
        if self._in_body and name in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif name == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._in_body and self._skip_depth == 0:
            self.body_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def body_text(self) -> str:
        return "\n".join(self.body_parts).strip()


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
        self.c3_failures = C3FailureCorpus(paths, db)

    def preflight(self, spec: JobSpec) -> None:
        if spec.egress not in {Egress.AUTO, Egress.DIRECT}:
            raise CapabilityError("M1 supports direct egress only")
        if spec.task_type == TaskType.AGENT:
            raise CapabilityError("autonomous Browser Agent is not installed")
        nodriver_c1 = spec.engine == BrowserEngine.NODRIVER and spec.task_type == TaskType.AUTOMATE
        if (
            spec.task_type in {TaskType.AUTOMATE, TaskType.INSPECT, TaskType.USE}
            and not nodriver_c1
            and not self._playwright_available()
        ):
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
                result = self._run_browser(job_id, spec, profile_epoch)
            elif spec.task_type == TaskType.INSPECT:
                result = self._run_browser(job_id, spec, profile_epoch, inspect_mode=True)
            elif spec.task_type == TaskType.USE:
                result = self._run_browser(job_id, spec, profile_epoch, use_mode=True)
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

    def _persist_rendered_html(self, job_id: str, html: str) -> dict[str, object]:
        rendered = html.encode("utf-8")
        metadata: dict[str, object] = {
            "body_bytes": len(rendered),
            "content_type": "text/html; charset=utf-8",
            "sha256": hashlib.sha256(rendered).hexdigest(),
        }
        if len(rendered) > MAX_RENDERED_ARTIFACT_BYTES:
            metadata["artifact_omitted_reason"] = "RENDERED_HTML_EXCEEDS_10MB_LIMIT"
            return metadata
        evidence_dir = self.paths.evidence_dir / job_id
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        evidence_dir.chmod(0o700)
        artifact_path = evidence_dir / "rendered.html"
        artifact_path.write_bytes(rendered)
        artifact_path.chmod(0o600)
        metadata["artifact_path"] = str(artifact_path)
        return metadata

    def _run_browser(
        self,
        job_id: str,
        spec: JobSpec,
        profile_epoch: int | None,
        *,
        inspect_mode: bool = False,
        use_mode: bool = False,
    ) -> dict[str, object]:
        selected, reason = self._select_browser_engine(spec, inspect_mode=inspect_mode, use_mode=use_mode)
        if selected == BrowserEngine.LIGHTPANDA:
            try:
                result = self._run_lightpanda_fetch(job_id, spec)
            except Exception as exc:
                if spec.engine == BrowserEngine.LIGHTPANDA:
                    raise
                fallback_error = f"{type(exc).__name__}: {exc}"[:1000]
                result = self._run_playwright(
                    job_id,
                    spec,
                    profile_epoch,
                    inspect_mode=inspect_mode,
                    use_mode=use_mode,
                )
                result["engine_route"] = {
                    "requested": spec.engine.value,
                    "selected": BrowserEngine.CHROME.value,
                    "attempted": [BrowserEngine.LIGHTPANDA.value, BrowserEngine.CHROME.value],
                    "reason": reason,
                    "fallback": {
                        "from": BrowserEngine.LIGHTPANDA.value,
                        "to": BrowserEngine.CHROME.value,
                        "error": fallback_error,
                    },
                }
                return result
            result["engine_route"] = {
                "requested": spec.engine.value,
                "selected": BrowserEngine.LIGHTPANDA.value,
                "attempted": [BrowserEngine.LIGHTPANDA.value],
                "reason": reason,
                "fallback": None,
            }
            return result

        if selected == BrowserEngine.NODRIVER:
            result = self._run_nodriver(job_id, spec)
            result["engine_route"] = {
                "requested": spec.engine.value,
                "selected": BrowserEngine.NODRIVER.value,
                "attempted": [BrowserEngine.NODRIVER.value],
                "reason": reason,
                "fallback": None,
            }
            return result

        if selected == BrowserEngine.CAMOUFOX:
            result = self._run_camoufox(job_id, spec, use_mode=use_mode)
            result["engine_route"] = {
                "requested": spec.engine.value,
                "selected": BrowserEngine.CAMOUFOX.value,
                "attempted": [BrowserEngine.CAMOUFOX.value],
                "reason": reason,
                "fallback": None,
            }
            return result

        result = self._run_playwright(
            job_id,
            spec,
            profile_epoch,
            inspect_mode=inspect_mode,
            use_mode=use_mode,
        )
        result["engine_route"] = {
            "requested": spec.engine.value,
            "selected": BrowserEngine.CHROME.value,
            "attempted": [BrowserEngine.CHROME.value],
            "reason": reason,
            "fallback": None,
        }
        return result

    def _select_browser_engine(
        self,
        spec: JobSpec,
        *,
        inspect_mode: bool,
        use_mode: bool,
    ) -> tuple[BrowserEngine, str]:
        if spec.engine == BrowserEngine.CHROME:
            return BrowserEngine.CHROME, "explicit_chrome"

        if spec.engine == BrowserEngine.NODRIVER:
            ineligible = self._nodriver_ineligible_reason(
                spec,
                inspect_mode=inspect_mode,
                use_mode=use_mode,
            )
            if ineligible:
                raise CapabilityError(f"nodriver is not eligible for this job: {ineligible}")
            if not self._nodriver_available():
                raise CapabilityError(
                    "nodriver was explicitly requested but its package/Chrome runtime is not installed"
                )
            return BrowserEngine.NODRIVER, "explicit_nodriver"

        if spec.engine == BrowserEngine.CAMOUFOX:
            ineligible = self._camoufox_ineligible_reason(spec, inspect_mode=inspect_mode)
            if ineligible:
                raise CapabilityError(f"Camoufox is not eligible for this job: {ineligible}")
            if not self._camoufox_available():
                raise CapabilityError("Camoufox was explicitly requested but its package/browser asset is not installed")
            return BrowserEngine.CAMOUFOX, "explicit_camoufox"

        ineligible = self._lightpanda_ineligible_reason(spec, inspect_mode=inspect_mode, use_mode=use_mode)
        if spec.engine == BrowserEngine.LIGHTPANDA:
            if ineligible:
                raise CapabilityError(f"Lightpanda is not eligible for this job: {ineligible}")
            if self._lightpanda_binary() is None:
                raise CapabilityError("Lightpanda was explicitly requested but no binary is installed")
            return BrowserEngine.LIGHTPANDA, "explicit_lightpanda"

        if ineligible:
            return BrowserEngine.CHROME, ineligible
        if self._lightpanda_binary() is None:
            return BrowserEngine.CHROME, "lightpanda_unavailable"
        return BrowserEngine.LIGHTPANDA, "auto_lightpanda_eligible"

    @staticmethod
    def _nodriver_ineligible_reason(
        spec: JobSpec,
        *,
        inspect_mode: bool,
        use_mode: bool,
    ) -> str | None:
        if inspect_mode or spec.task_type == TaskType.INSPECT:
            return "c2_requires_chrome_diagnostics"
        if spec.profile_mode != ProfileMode.EPHEMERAL:
            return "nodriver_v1_ephemeral_only"
        if use_mode or spec.task_type == TaskType.USE:
            return "c3_nodriver_not_supported_v1"
        if spec.task_type != TaskType.AUTOMATE:
            return "task_not_nodriver_routable"
        return None

    @staticmethod
    def _nodriver_available() -> bool:
        try:
            import nodriver  # noqa: F401
        except ImportError:
            return False
        chrome = Path(
            os.environ.get(
                "BROWSER_PLANE_CHROME",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            )
        )
        return chrome.exists()

    def _run_nodriver(self, job_id: str, spec: JobSpec) -> dict[str, object]:
        if not self._nodriver_available():
            raise CapabilityError("nodriver Python package/Chrome runtime is not installed")
        ineligible = self._nodriver_ineligible_reason(spec, inspect_mode=False, use_mode=False)
        if ineligible:
            raise CapabilityError(f"nodriver is not eligible for this job: {ineligible}")

        with tempfile.TemporaryDirectory(prefix="nodriver-", dir=self.paths.run_dir) as tmp:
            request_path = Path(tmp) / "request.json"
            response_path = Path(tmp) / "response.json"
            request_path.write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "url": spec.url,
                        "max_run_sec": spec.max_run_sec,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            request_path.chmod(0o600)

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "browser_plane.nodriver_runner",
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=env,
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
                    runtime_kind="C1_NODRIVER",
                    profile_id=None,
                    user_data_dir=None,
                )
                control_epoch = self.leases.acquire_control(
                    browser_session_id,
                    job_id,
                    "NODRIVER_RENDER",
                )
                if control_epoch is None:
                    raise RuntimeError("control lease unavailable")

                def heartbeat() -> None:
                    while not heartbeat_stop.wait(1.0):
                        if control_epoch is not None:
                            self.leases.heartbeat_control(browser_session_id, job_id, control_epoch)
                        if browser_process_id is not None:
                            self.processes.mark_seen(browser_process_id)
                        current = self.jobs.get(job_id)
                        if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                            if browser_process_id is not None:
                                self.processes.terminate_owned(browser_process_id, grace_sec=3.0)
                            return

                heartbeat_thread = threading.Thread(
                    target=heartbeat,
                    name=f"nodriver-heartbeat-{job_id}",
                    daemon=True,
                )
                heartbeat_thread.start()
                try:
                    _, stderr = proc.communicate(timeout=spec.max_run_sec + 15)
                except subprocess.TimeoutExpired as exc:
                    if browser_process_id is not None:
                        self.processes.terminate_owned(browser_process_id, grace_sec=3.0)
                    try:
                        _, stderr = proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        stderr = "nodriver runner did not exit after termination"
                    raise TimeoutError("nodriver exceeded Browser Plane execution deadline") from exc

                if proc.returncode != 0:
                    raise RuntimeError(
                        f"nodriver runner failed rc={proc.returncode}: {(stderr or '').strip()[:1000]}"
                    )
                if not response_path.exists():
                    raise RuntimeError("nodriver runner exited without a response")
                payload = json.loads(response_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise RuntimeError("nodriver runner returned a non-object response")
                payload["browser_process_id"] = browser_process_id
                payload["browser_session_id"] = browser_session_id
                return payload
            finally:
                heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1.0)
                if control_epoch is not None:
                    self.leases.release_control(browser_session_id, job_id, control_epoch)
                if browser_process_id is not None:
                    if proc.poll() is None:
                        self.processes.terminate_owned(browser_process_id, grace_sec=3.0)
                    else:
                        self.processes.mark_closed(browser_process_id)
                elif proc.poll() is None:
                    proc.terminate()

    @staticmethod
    def _camoufox_ineligible_reason(spec: JobSpec, *, inspect_mode: bool) -> str | None:
        if inspect_mode or spec.task_type == TaskType.INSPECT:
            return "c2_requires_chrome_diagnostics"
        if spec.profile_mode != ProfileMode.EPHEMERAL:
            return "camoufox_v1_ephemeral_only"
        if spec.task_type not in {TaskType.AUTOMATE, TaskType.USE}:
            return "task_not_camoufox_routable"
        return None

    @staticmethod
    def _camoufox_available() -> bool:
        try:
            from camoufox.pkgman import camoufox_path

            browser_path = camoufox_path(download_if_missing=False)
        except Exception:
            return False
        return browser_path.exists()

    def _run_camoufox(self, job_id: str, spec: JobSpec, *, use_mode: bool) -> dict[str, object]:
        if not self._camoufox_available():
            raise CapabilityError("Camoufox Python package is not installed")
        ineligible = self._camoufox_ineligible_reason(spec, inspect_mode=False)
        if ineligible:
            raise CapabilityError(f"Camoufox is not eligible for this job: {ineligible}")

        with tempfile.TemporaryDirectory(prefix="camoufox-", dir=self.paths.run_dir) as tmp:
            request_path = Path(tmp) / "request.json"
            response_path = Path(tmp) / "response.json"
            request_path.write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "url": spec.url,
                        "max_run_sec": spec.max_run_sec,
                        "use_mode": use_mode,
                        "actions": list(spec.actions),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            request_path.chmod(0o600)

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "browser_plane.camoufox_runner",
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=env,
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
                    runtime_kind="C3_CAMOUFOX" if use_mode else "C1_CAMOUFOX",
                    profile_id=None,
                    user_data_dir=None,
                )
                control_epoch = self.leases.acquire_control(
                    browser_session_id,
                    job_id,
                    "CAMOUFOX_USE" if use_mode else "CAMOUFOX_RENDER",
                )
                if control_epoch is None:
                    raise RuntimeError("control lease unavailable")

                def heartbeat() -> None:
                    while not heartbeat_stop.wait(1.0):
                        if control_epoch is not None:
                            self.leases.heartbeat_control(browser_session_id, job_id, control_epoch)
                        if browser_process_id is not None:
                            self.processes.mark_seen(browser_process_id)
                        current = self.jobs.get(job_id)
                        if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                            if browser_process_id is not None:
                                self.processes.terminate_owned(browser_process_id, grace_sec=3.0)
                            return

                heartbeat_thread = threading.Thread(
                    target=heartbeat,
                    name=f"camoufox-heartbeat-{job_id}",
                    daemon=True,
                )
                heartbeat_thread.start()
                try:
                    _, stderr = proc.communicate(timeout=spec.max_run_sec + 15)
                except subprocess.TimeoutExpired as exc:
                    if browser_process_id is not None:
                        self.processes.terminate_owned(browser_process_id, grace_sec=3.0)
                    try:
                        _, stderr = proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        stderr = "Camoufox runner did not exit after termination"
                    raise TimeoutError("Camoufox exceeded Browser Plane execution deadline") from exc

                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Camoufox runner failed rc={proc.returncode}: {(stderr or '').strip()[:1000]}"
                    )
                if not response_path.exists():
                    raise RuntimeError("Camoufox runner exited without a response")
                payload = json.loads(response_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise RuntimeError("Camoufox runner returned a non-object response")
                payload["browser_process_id"] = browser_process_id
                payload["browser_session_id"] = browser_session_id
                return payload
            finally:
                heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1.0)
                if control_epoch is not None:
                    self.leases.release_control(browser_session_id, job_id, control_epoch)
                if browser_process_id is not None:
                    if proc.poll() is None:
                        self.processes.terminate_owned(browser_process_id, grace_sec=3.0)
                    else:
                        self.processes.mark_closed(browser_process_id)
                elif proc.poll() is None:
                    proc.terminate()

    @staticmethod
    def _lightpanda_ineligible_reason(
        spec: JobSpec,
        *,
        inspect_mode: bool,
        use_mode: bool,
    ) -> str | None:
        if inspect_mode or spec.task_type == TaskType.INSPECT:
            return "c2_requires_chrome_diagnostics"
        if spec.profile_mode != ProfileMode.EPHEMERAL:
            return "persistent_profile_requires_chrome"
        if use_mode or spec.task_type == TaskType.USE:
            return "c3_requires_chrome_v1"
        if spec.task_type != TaskType.AUTOMATE:
            return "task_not_lightpanda_routable"
        return None

    @staticmethod
    def _lightpanda_binary() -> Path | None:
        configured = os.environ.get("BROWSER_PLANE_LIGHTPANDA")
        candidates = [
            configured,
            shutil.which("lightpanda"),
            "/opt/homebrew/bin/lightpanda",
            "/usr/local/bin/lightpanda",
        ]
        for raw in candidates:
            if not raw:
                continue
            path = Path(raw).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return path
        return None

    def _run_lightpanda_fetch(self, job_id: str, spec: JobSpec) -> dict[str, object]:
        lightpanda = self._lightpanda_binary()
        if lightpanda is None:
            raise CapabilityError("Lightpanda binary is not installed")
        if spec.profile_mode != ProfileMode.EPHEMERAL:
            raise CapabilityError("Lightpanda v1 fast path supports ephemeral C1 only")

        env = os.environ.copy()
        env["LIGHTPANDA_DISABLE_TELEMETRY"] = "true"
        env["LIGHTPANDA_DISABLE_CORE_DUMP"] = "1"
        deadline_ms = max(1_000, spec.max_run_sec * 1_000)
        command = [
            str(lightpanda),
            "fetch",
            "--json",
            "--dump",
            "html",
            "--dump-max-bytes",
            "1000000",
            "--wait-until",
            "domcontentloaded",
            "--terminate-ms",
            str(deadline_ms),
            "--http-timeout",
            str(deadline_ms),
            "--log-level",
            "error",
            spec.url,
        ]
        started = time.monotonic()
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=env,
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
                runtime_kind="C1_LIGHTPANDA",
                profile_id=None,
                user_data_dir=None,
            )
            control_epoch = self.leases.acquire_control(
                browser_session_id,
                job_id,
                "LIGHTPANDA_FETCH",
            )
            if control_epoch is None:
                raise RuntimeError("control lease unavailable")

            def heartbeat() -> None:
                while not heartbeat_stop.wait(1.0):
                    if control_epoch is not None:
                        self.leases.heartbeat_control(browser_session_id, job_id, control_epoch)
                    if browser_process_id is not None:
                        self.processes.mark_seen(browser_process_id)
                    current = self.jobs.get(job_id)
                    if current and current["state"] == JobState.CANCEL_REQUESTED.value:
                        if browser_process_id is not None:
                            self.processes.terminate_owned(browser_process_id, grace_sec=1.0)
                        return

            heartbeat_thread = threading.Thread(
                target=heartbeat,
                name=f"lightpanda-heartbeat-{job_id}",
                daemon=True,
            )
            heartbeat_thread.start()
            try:
                stdout, stderr = proc.communicate(timeout=spec.max_run_sec + 5)
            except subprocess.TimeoutExpired as exc:
                if browser_process_id is not None:
                    self.processes.terminate_owned(browser_process_id, grace_sec=1.0)
                proc.communicate(timeout=3)
                raise TimeoutError("Lightpanda fetch exceeded Browser Plane execution deadline") from exc

            elapsed_ms = int((time.monotonic() - started) * 1000)
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Lightpanda returned invalid JSON: {stdout[:500]!r}; stderr={stderr[:500]!r}"
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeError("Lightpanda returned a non-object JSON payload")
            if proc.returncode != 0 or payload.get("error"):
                raise RuntimeError(
                    f"Lightpanda fetch failed rc={proc.returncode} error={payload.get('error')!r} stderr={stderr[:500]!r}"
                )

            status = int(payload.get("http_status") or 0)
            content = str(payload.get("content") or "")
            if status in {401, 403, 429} or status >= 500:
                raise RuntimeError(f"Lightpanda HTTP {status} is eligible for Chrome fallback")
            if status and not content:
                raise RuntimeError("Lightpanda returned an empty rendered DOM")

            parser = _RenderedHTMLTextParser()
            parser.feed(content)
            body_text = require_nonempty_c1_body(parser.body_text, engine="lightpanda")
            headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
            content_type = next(
                (
                    str(item.get("value"))
                    for item in headers
                    if isinstance(item, dict) and str(item.get("name", "")).lower() == "content-type"
                ),
                None,
            )
            result = {
                "engine": "c1-lightpanda",
                "browser_engine": BrowserEngine.LIGHTPANDA.value,
                "url": str(payload.get("url") or spec.url),
                "title": parser.title,
                "status": status or None,
                "elapsed_ms": elapsed_ms,
                "content_type": content_type,
                "body_bytes": len(content.encode("utf-8")),
                "text_excerpt": body_text[:4000],
                "browser_process_id": browser_process_id,
                "browser_session_id": browser_session_id,
            }
            result.update(c1_content_quality_metadata(body_text, wait_ms=0))
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

        chrome = Path(
            os.environ.get(
                "BROWSER_PLANE_CHROME",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            )
        )
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
            capability_kind = "C3" if use_mode else ("C2" if inspect_mode else "C1")
            browser_process_id = self.processes.register(
                pid=proc.pid,
                job_id=job_id,
                runtime_kind=f"{capability_kind}_CHROME",
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
                context = browser.contexts[0] if browser.contexts else browser.new_context(
                    viewport={"width": 1440, "height": 900}
                )
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
                    def record_response(resp: Any) -> None:
                        if len(responses) >= 200:
                            return
                        content_type = str(resp.headers.get("content-type", ""))
                        responses.append(
                            {
                                "status": resp.status,
                                "url": resp.url,
                                "content_type": content_type,
                            }
                        )

                    page.on("response", record_response)

                started = time.monotonic()
                response = page.goto(spec.url, wait_until="domcontentloaded", timeout=spec.max_run_sec * 1000)
                action_results: list[dict[str, object]] = []
                if use_mode:
                    action_results = self._run_browser_actions(
                        page,
                        job_id,
                        spec.actions,
                        browser_engine=BrowserEngine.CHROME.value,
                    )
                c1_html: str | None = None
                c1_body_text: str | None = None
                c1_ready_wait_ms: int | None = None
                if not inspect_mode and not use_mode:
                    c1_html, c1_body_text, c1_ready_wait_ms = wait_for_sync_c1_content(
                        page,
                        engine="chrome",
                        max_wait_sec=min(5.0, max(1.0, float(spec.max_run_sec))),
                    )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                status = response.status if response else None
                for action_result in reversed(action_results):
                    if "status" in action_result:
                        status = action_result["status"]
                        break
                engine_name = "c3-browser-use" if use_mode else (
                    "c2-readonly-inspect" if inspect_mode else "c1-playwright"
                )
                text_excerpt = (
                    c1_body_text[:4000]
                    if c1_body_text is not None
                    else page.locator("body").inner_text(timeout=5000)[:4000]
                )
                result: dict[str, object] = {
                    "engine": engine_name,
                    "browser_engine": BrowserEngine.CHROME.value,
                    "url": page.url,
                    "title": page.title(),
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "text_excerpt": text_excerpt,
                    "browser_process_id": browser_process_id,
                    "browser_session_id": browser_session_id,
                }
                if not inspect_mode and not use_mode:
                    assert c1_html is not None and c1_body_text is not None and c1_ready_wait_ms is not None
                    result.update(self._persist_rendered_html(job_id, c1_html))
                    result.update(c1_content_quality_metadata(c1_body_text, wait_ms=c1_ready_wait_ms))
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
                    result["api_candidates"] = derive_api_candidates(page.url, requests, responses)
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

    @staticmethod
    def _action_locator(page: Any, action: dict[str, Any], *, required: bool) -> Any | None:
        targets = [
            ("selector", str(action.get("selector", "")).strip()),
            ("role", str(action.get("role", "")).strip()),
            ("label", str(action.get("label", "")).strip()),
            ("text_target", str(action.get("text_target", "")).strip()),
        ]
        targets = [(kind, value) for kind, value in targets if value]
        if len(targets) > 1:
            raise CapabilityError("browser action must use exactly one target form")
        if not targets:
            if required:
                raise CapabilityError("browser action requires selector, role, label, or text_target")
            return None

        kind, value = targets[0]
        exact = action.get("exact")
        if exact is not None and not isinstance(exact, bool):
            raise CapabilityError("semantic target exact must be a boolean")
        if kind == "selector":
            if "name" in action or exact is not None:
                raise CapabilityError("selector targeting does not accept name/exact")
            return page.locator(value)
        if kind == "role":
            kwargs: dict[str, Any] = {}
            name = str(action.get("name", "")).strip()
            if name:
                kwargs["name"] = name
            if exact is not None:
                kwargs["exact"] = exact
            return page.get_by_role(value, **kwargs)
        if "name" in action:
            raise CapabilityError("name is allowed only with role targeting")
        if kind == "label":
            return page.get_by_label(value, exact=exact)
        return page.get_by_text(value, exact=exact)

    @staticmethod
    def _action_target(action: dict[str, Any]) -> dict[str, object]:
        return {
            key: action[key]
            for key in ("selector", "role", "label", "text_target", "name", "exact")
            if key in action
        }

    def _run_browser_actions(
        self,
        page: Any,
        job_id: str,
        actions: tuple[dict[str, Any], ...],
        *,
        browser_engine: str = BrowserEngine.CHROME.value,
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
                    locator = self._action_locator(page, action, required=True)
                    force = bool(action.get("force", False))
                    locator.click(timeout=timeout_ms, force=force)
                    item = {
                        "step": index,
                        "action": kind,
                        "target": self._action_target(action),
                        "force": force,
                        "url": page.url,
                    }
                elif kind == "type":
                    locator = self._action_locator(page, action, required=True)
                    text = str(action.get("text", ""))
                    locator.fill(text, timeout=timeout_ms)
                    item = {
                        "step": index,
                        "action": kind,
                        "target": self._action_target(action),
                        "chars": len(text),
                    }
                elif kind == "select":
                    locator = self._action_locator(page, action, required=True)
                    if "value" not in action:
                        raise CapabilityError("select requires value")
                    force = bool(action.get("force", False))
                    selected = locator.select_option(value=str(action["value"]), timeout=timeout_ms, force=force)
                    item = {
                        "step": index,
                        "action": kind,
                        "target": self._action_target(action),
                        "force": force,
                        "selected": list(selected),
                    }
                elif kind == "press":
                    key = str(action.get("key", "")).strip()
                    if not key:
                        raise CapabilityError("press requires key")
                    locator = self._action_locator(page, action, required=False)
                    if locator is not None:
                        locator.press(key, timeout=timeout_ms)
                    else:
                        page.keyboard.press(key)
                    item = {
                        "step": index,
                        "action": kind,
                        "key": key,
                        "target": self._action_target(action) if locator is not None else None,
                    }
                elif kind == "wait":
                    locator = self._action_locator(page, action, required=False)
                    if locator is not None:
                        state = str(action.get("state", "visible"))
                        if state not in {"attached", "detached", "visible", "hidden"}:
                            raise CapabilityError("wait state is invalid")
                        locator.wait_for(state=state, timeout=timeout_ms)
                        item = {
                            "step": index,
                            "action": kind,
                            "target": self._action_target(action),
                            "state": state,
                        }
                    else:
                        wait_ms = int(action.get("ms", 1000))
                        if wait_ms < 0 or wait_ms > 30_000:
                            raise CapabilityError("wait ms must be between 0 and 30000")
                        page.wait_for_timeout(wait_ms)
                        item = {"step": index, "action": kind, "ms": wait_ms}
                elif kind == "snapshot":
                    body = page.locator("body")
                    aria_tree = body.aria_snapshot(timeout=timeout_ms, depth=8, mode="ai")
                    item = {
                        "step": index,
                        "action": kind,
                        "url": page.url,
                        "title": page.title(),
                        "text_excerpt": body.inner_text(timeout=timeout_ms)[:4000],
                        "aria_snapshot": aria_tree[:12000],
                        "aria_snapshot_truncated": len(aria_tree) > 12000,
                    }
                elif kind == "screenshot":
                    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    evidence_dir.chmod(0o700)
                    screenshot_path = evidence_dir / f"screenshot-{index}.png"
                    page.screenshot(path=str(screenshot_path), full_page=bool(action.get("full_page", False)))
                    screenshot_path.chmod(0o600)
                    item = {"step": index, "action": kind, "path": str(screenshot_path)}
                elif kind == "download":
                    locator = self._action_locator(page, action, required=True)
                    with page.expect_download(timeout=timeout_ms) as download_info:
                        locator.click(timeout=timeout_ms)
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
                        "target": self._action_target(action),
                        "path": str(target),
                        "bytes": target.stat().st_size,
                        "sha256": digest,
                    }
                else:
                    raise CapabilityError(f"unsupported browser action: {kind or '<missing>'}")
            except Exception as exc:
                if isinstance(exc, CapabilityError):
                    raise
                try:
                    self.c3_failures.record_action_failure(
                        page=page,
                        job_id=job_id,
                        browser_engine=browser_engine,
                        step=index,
                        action=action,
                        exc=exc,
                    )
                except Exception:
                    # Corpus capture is diagnostic-only and must never mask the
                    # original C3 execution failure.
                    pass
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
