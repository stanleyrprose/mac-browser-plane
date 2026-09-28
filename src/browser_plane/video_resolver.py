from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class VideoResolveError(RuntimeError):
    pass


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtube-nocookie.com",
}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass(frozen=True)
class _Strategy:
    name: str
    extractor_args: str | None = None


def _find_executable(name: str) -> str | None:
    sibling = Path(sys.executable).with_name(name)
    if sibling.is_file() and sibling.stat().st_mode & 0o111:
        return str(sibling)
    return shutil.which(name)


def video_resolver_readiness() -> dict[str, Any]:
    yt_dlp = _find_executable("yt-dlp")
    ffmpeg = _find_executable("ffmpeg")
    node = _find_executable("node")
    deno = _find_executable("deno")
    js_runtime = "node" if node else ("deno" if deno else None)
    return {
        "ready": bool(yt_dlp and js_runtime),
        "backend": "yt-dlp",
        "yt_dlp_path": yt_dlp,
        "ffmpeg_path": ffmpeg,
        "js_runtime": js_runtime,
        "node_path": node,
        "deno_path": deno,
        "session_mode": "anonymous_only_v1",
        "youtube_challenge_provider": "external_optional_v1",
    }


def _is_youtube(url: str) -> bool:
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com")


def _strategies(url: str) -> tuple[_Strategy, ...]:
    if not _is_youtube(url):
        return (_Strategy("default"),)
    return (
        _Strategy("youtube-default"),
        _Strategy("youtube-mweb", "youtube:player_client=mweb"),
        _Strategy("youtube-web-safari-hls", "youtube:player_client=web_safari"),
    )


def _safe_error(text: str, limit: int = 600) -> str:
    clean = _URL_RE.sub("<url>", text or "").strip()
    if len(clean) > limit:
        clean = clean[-limit:]
    return clean


def _format_summary(raw: dict[str, Any], *, max_formats: int) -> tuple[list[dict[str, Any]], int]:
    formats = raw.get("formats")
    if not isinstance(formats, list):
        return [], 0

    media_formats: list[dict[str, Any]] = []
    for item in formats:
        if not isinstance(item, dict):
            continue
        vcodec = item.get("vcodec")
        acodec = item.get("acodec")
        if (vcodec in (None, "none")) and (acodec in (None, "none")):
            continue
        media_formats.append(
            {
                key: item.get(key)
                for key in (
                    "format_id",
                    "format_note",
                    "ext",
                    "protocol",
                    "width",
                    "height",
                    "resolution",
                    "fps",
                    "vcodec",
                    "acodec",
                    "abr",
                    "vbr",
                    "tbr",
                    "filesize",
                    "filesize_approx",
                )
                if item.get(key) is not None
            }
        )

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        height = int(item.get("height") or 0)
        has_video = int(item.get("vcodec") not in (None, "none"))
        has_audio = int(item.get("acodec") not in (None, "none"))
        return (has_video + has_audio, height, int(item.get("tbr") or 0))

    media_formats.sort(key=score, reverse=True)
    return media_formats[:max_formats], len(media_formats)


def _public_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "title",
        "extractor",
        "extractor_key",
        "webpage_url",
        "duration",
        "timestamp",
        "upload_date",
        "uploader",
        "uploader_id",
        "channel",
        "channel_id",
        "live_status",
        "is_live",
        "availability",
        "age_limit",
    )
    return {key: raw.get(key) for key in keys if raw.get(key) is not None}


def resolve_video(
    url: str,
    *,
    timeout_sec: int = 60,
    max_formats: int = 40,
) -> dict[str, Any]:
    if timeout_sec < 15 or timeout_sec > 180:
        raise VideoResolveError("timeout_sec must be between 15 and 180")
    if max_formats < 1 or max_formats > 100:
        raise VideoResolveError("max_formats must be between 1 and 100")

    readiness = video_resolver_readiness()
    if not readiness["ready"]:
        raise VideoResolveError(
            "video resolver is not ready: yt-dlp and one supported JS runtime (Node or Deno) are required"
        )

    yt_dlp = str(readiness["yt_dlp_path"])
    js_runtime = str(readiness["js_runtime"])
    attempts: list[dict[str, Any]] = []
    strategies = _strategies(url)
    deadline = time.monotonic() + timeout_sec

    for index, strategy in enumerate(strategies):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        strategies_left = len(strategies) - index
        attempt_timeout = max(3.0, remaining / strategies_left)
        attempt_timeout = min(remaining, attempt_timeout)
        socket_timeout = max(3, min(8, int(attempt_timeout) - 1))
        command = [
            yt_dlp,
            "--ignore-config",
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            "--socket-timeout",
            str(socket_timeout),
            "--retries",
            "1",
            "--js-runtimes",
            js_runtime,
        ]
        if strategy.extractor_args:
            command.extend(["--extractor-args", strategy.extractor_args])
        command.append(url)

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=attempt_timeout,
            )
        except subprocess.TimeoutExpired:
            attempts.append(
                {
                    "strategy": strategy.name,
                    "status": "timeout",
                    "detail": f"yt-dlp exceeded strategy budget ({attempt_timeout:.1f}s)",
                }
            )
            continue
        except OSError as exc:
            raise VideoResolveError(f"failed to start yt-dlp: {type(exc).__name__}: {exc}") from exc

        if completed.returncode != 0:
            attempts.append(
                {
                    "strategy": strategy.name,
                    "status": "failed",
                    "exit_code": completed.returncode,
                    "detail": _safe_error(completed.stderr),
                }
            )
            continue

        try:
            raw = json.loads(completed.stdout.strip())
        except (TypeError, json.JSONDecodeError) as exc:
            attempts.append(
                {
                    "strategy": strategy.name,
                    "status": "invalid_json",
                    "detail": f"{type(exc).__name__}: yt-dlp did not return valid JSON",
                }
            )
            continue

        summary, media_format_count = _format_summary(raw, max_formats=max_formats)
        if media_format_count < 1:
            attempts.append(
                {
                    "strategy": strategy.name,
                    "status": "no_media_formats",
                    "detail": "metadata resolved but no playable audio/video formats were returned",
                }
            )
            continue

        attempts.append({"strategy": strategy.name, "status": "succeeded"})
        return {
            "status": "RESOLVED",
            "strategy": strategy.name,
            "backend": "yt-dlp",
            "session_mode": "anonymous",
            "youtube_challenge_provider": readiness["youtube_challenge_provider"],
            "metadata": _public_metadata(raw),
            "format_count": media_format_count,
            "formats": summary,
            "formats_truncated": media_format_count > len(summary),
            "attempts": attempts,
            "sensitive_stream_urls_returned": False,
            "download_hint": {
                "strategy": strategy.name,
                "extractor_args": strategy.extractor_args,
            },
        }

    detail = attempts[-1].get("detail") if attempts else "no resolver strategy ran"
    raise VideoResolveError(f"all video resolver strategies failed: {detail}")
