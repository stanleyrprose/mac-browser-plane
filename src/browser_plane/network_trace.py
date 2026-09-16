from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import RuntimePaths
from .db import RuntimeDB
from .processes import BrowserProcessRegistry

_HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\d{1,3}(?:\.\d{1,3}){3})$")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def find_mitmdump() -> str | None:
    return shutil.which("mitmdump")


def validate_host(host: str) -> str:
    value = host.strip().lower().rstrip(".")
    if not value or len(value) > 253 or not _HOST_RE.fullmatch(value):
        raise ValueError("host must be a bare DNS name or IPv4 address")
    if value == "0.0.0.0":
        raise ValueError("wildcard host is not allowed")
    return value


def choose_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _trace_dir(paths: RuntimePaths) -> Path:
    target = paths.evidence_dir / "network-trace"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)
    return target


def _state_path(paths: RuntimePaths) -> Path:
    return paths.run_dir / "network-trace.json"


def _addon_source(host: str, output_path: Path) -> str:
    return f'''from __future__ import annotations\nimport json\nfrom datetime import UTC, datetime\nfrom urllib.parse import urlsplit\nTARGET_HOST = {json.dumps(host)}\nOUTPUT = {json.dumps(str(output_path))}\ndef _matches(host: str) -> bool:\n    value = (host or "").lower().rstrip(".")\n    return value == TARGET_HOST or value.endswith("." + TARGET_HOST)\ndef response(flow):\n    req = flow.request\n    resp = flow.response\n    if not _matches(req.pretty_host):\n        return\n    split = urlsplit(req.pretty_url)\n    ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()\n    path = split.path or "/"\n    record = {{"timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "method": req.method, "scheme": split.scheme, "host": req.pretty_host.lower(), "path": path, "status": int(resp.status_code), "content_type": ctype, "response_size": len(resp.raw_content or b""), "api_like": bool(ctype == "application/json" or ctype.endswith("+json") or path.startswith("/api/") or "/api/" in path)}}\n    with open(OUTPUT, "a", encoding="utf-8") as fh:\n        fh.write(json.dumps(record, sort_keys=True) + "\\n")\n'''


def build_command(executable: str, *, host: str, port: int, addon_path: Path) -> list[str]:
    validated = validate_host(host)
    if not (1024 <= int(port) <= 65535):
        raise ValueError("port must be between 1024 and 65535")
    return [executable, "--listen-host", "127.0.0.1", "--listen-port", str(port), "--quiet", "--set", "termlog_verbosity=error", "--set", f"allow_hosts=^(?:.*\\.)?{re.escape(validated)}(?::\\d+)?$", "-s", str(addon_path)]


@dataclass
class TraceController:
    paths: RuntimePaths
    db: RuntimeDB

    def doctor(self) -> dict[str, Any]:
        executable = find_mitmdump()
        state = self._read_state()
        running = bool(state and self._state_running(state))
        return {"status": "READY" if executable else "UNAVAILABLE", "mitmdump": executable, "default_off": True, "loopback_only": True, "active": running, "active_host": state.get("host") if running and state else None}

    def start(self, host: str, port: int | None = None) -> dict[str, Any]:
        host = validate_host(host)
        executable = find_mitmdump()
        if executable is None:
            raise RuntimeError("mitmdump is not installed or not on PATH")
        existing = self._read_state()
        if existing and self._state_running(existing):
            raise RuntimeError("a network trace is already running")
        if existing:
            self._remove_state()
        trace_id = str(uuid.uuid4())
        trace_dir = _trace_dir(self.paths) / trace_id
        trace_dir.mkdir(mode=0o700)
        summary_path = trace_dir / "flows.jsonl"
        addon_path = trace_dir / "capture_addon.py"
        stderr_path = trace_dir / "mitmdump.stderr.log"
        addon_path.write_text(_addon_source(host, summary_path), encoding="utf-8")
        addon_path.chmod(0o600)
        summary_path.touch(mode=0o600)
        summary_path.chmod(0o600)
        stderr_path.touch(mode=0o600)
        stderr_path.chmod(0o600)
        selected_port = int(port or choose_loopback_port())
        command = build_command(executable, host=host, port=selected_port, addon_path=addon_path)
        stderr_handle = stderr_path.open("ab", buffering=0)
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr_handle, start_new_session=True)
        finally:
            stderr_handle.close()
        registry = BrowserProcessRegistry(self.db)
        process_id = registry.register(pid=proc.pid, job_id=f"trace:{trace_id}", runtime_kind="NETWORK_TRACE_MITMDUMP", profile_id=None, user_data_dir=None)
        state = {"trace_id": trace_id, "host": host, "port": selected_port, "pid": proc.pid, "browser_process_id": process_id, "summary_path": str(summary_path), "addon_path": str(addon_path), "stderr_path": str(stderr_path), "started_at": _iso_now()}
        self._write_state(state)
        try:
            self._wait_until_listening(proc, selected_port, stderr_path)
        except Exception:
            registry.terminate_owned(process_id, grace_sec=1.0)
            self._remove_state()
            raise
        return {"status": "RUNNING", "trace_id": trace_id, "host": host, "proxy_url": f"http://127.0.0.1:{selected_port}", "summary_path": str(summary_path)}

    def stop(self) -> dict[str, Any]:
        state = self._read_state()
        if not state:
            return {"status": "NOT_RUNNING"}
        registry = BrowserProcessRegistry(self.db)
        process_id = str(state["browser_process_id"])
        stopped = True
        if self._state_running(state):
            stopped = registry.terminate_owned(process_id, grace_sec=2.0)
        else:
            registry.mark_closed(process_id, "GONE")
        result = {"status": "STOPPED" if stopped else "OWNERSHIP_UNCERTAIN", "trace_id": state.get("trace_id"), "host": state.get("host"), "summary": self.summary(state=state)}
        if stopped:
            self._remove_state()
        return result

    def summary(self, *, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or self._read_state()
        if not state:
            return {"status": "NO_TRACE", "flows": [], "flow_count": 0}
        path = Path(str(state["summary_path"]))
        flows: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    flows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"status": "OK", "trace_id": state.get("trace_id"), "host": state.get("host"), "active": self._state_running(state), "flow_count": len(flows), "api_like_count": sum(1 for item in flows if item.get("api_like")), "flows": flows[-200:]}

    def _wait_until_listening(self, proc: subprocess.Popen[bytes], port: int, stderr_path: Path) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"mitmdump exited during startup: {detail}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("mitmdump did not become ready within 5 seconds")

    def _state_running(self, state: dict[str, Any]) -> bool:
        process_id = state.get("browser_process_id")
        return bool(process_id and BrowserProcessRegistry(self.db).verify_owned(str(process_id)))

    def _read_state(self) -> dict[str, Any] | None:
        path = _state_path(self.paths)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_state(self, state: dict[str, Any]) -> None:
        path = _state_path(self.paths)
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)

    def _remove_state(self) -> None:
        try:
            _state_path(self.paths).unlink()
        except FileNotFoundError:
            pass
