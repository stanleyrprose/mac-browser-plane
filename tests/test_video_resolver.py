from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from browser_plane.video_resolver import (
    VideoResolveError,
    _safe_error,
    _strategies,
    resolve_video,
    video_resolver_readiness,
)


def _resolved_payload() -> dict[str, object]:
    return {
        "id": "video-1",
        "title": "Example",
        "extractor": "youtube",
        "webpage_url": "https://www.youtube.com/watch?v=video-1",
        "duration": 42,
        "formats": [
            {
                "format_id": "sb0",
                "protocol": "mhtml",
                "vcodec": "none",
                "acodec": "none",
                "url": "https://example.invalid/storyboard",
            },
            {
                "format_id": "137",
                "ext": "mp4",
                "protocol": "https",
                "height": 1080,
                "vcodec": "avc1",
                "acodec": "none",
                "url": "https://media.invalid/signed-video",
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "protocol": "https",
                "vcodec": "none",
                "acodec": "mp4a",
                "abr": 129,
                "url": "https://media.invalid/signed-audio",
            },
        ],
    }


class VideoResolverTests(unittest.TestCase):
    def test_readiness_requires_ytdlp_and_js_runtime(self) -> None:
        mapping = {
            "yt-dlp": "/tmp/yt-dlp",
            "ffmpeg": "/tmp/ffmpeg",
            "node": "/tmp/node",
            "deno": None,
        }
        with patch("browser_plane.video_resolver._find_executable", side_effect=lambda name: mapping[name]):
            report = video_resolver_readiness()
        self.assertTrue(report["ready"])
        self.assertEqual(report["js_runtime"], "node")
        self.assertEqual(report["session_mode"], "anonymous_only_v1")

        mapping["node"] = None
        with patch("browser_plane.video_resolver._find_executable", side_effect=lambda name: mapping[name]):
            report = video_resolver_readiness()
        self.assertFalse(report["ready"])

    def test_youtube_strategy_order_is_bounded(self) -> None:
        self.assertEqual(
            [item.name for item in _strategies("https://www.youtube.com/watch?v=abc")],
            ["youtube-default", "youtube-mweb", "youtube-web-safari-hls"],
        )
        self.assertEqual(
            [item.name for item in _strategies("https://vimeo.com/123")],
            ["default"],
        )

    def test_resolve_success_redacts_signed_media_urls(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(_resolved_payload()),
            stderr="",
        )
        ready = {
            "ready": True,
            "yt_dlp_path": "/tmp/yt-dlp",
            "js_runtime": "node",
            "youtube_challenge_provider": "external_optional_v1",
        }
        with (
            patch("browser_plane.video_resolver.video_resolver_readiness", return_value=ready),
            patch("browser_plane.video_resolver.subprocess.run", return_value=completed) as run,
        ):
            result = resolve_video("https://www.youtube.com/watch?v=abc", max_formats=10)

        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["strategy"], "youtube-default")
        self.assertEqual(result["format_count"], 2)
        self.assertEqual(len(result["formats"]), 2)
        self.assertFalse(result["sensitive_stream_urls_returned"])
        self.assertNotIn("url", result["formats"][0])
        command = run.call_args.args[0]
        self.assertIn("--ignore-config", command)
        self.assertIn("--no-playlist", command)

    def test_resolve_falls_back_after_first_strategy_failure(self) -> None:
        failure = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=1,
            stdout="",
            stderr="ERROR failed to resolve https://media.invalid/private-path",
        )
        success = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(_resolved_payload()),
            stderr="",
        )
        ready = {
            "ready": True,
            "yt_dlp_path": "/tmp/yt-dlp",
            "js_runtime": "node",
            "youtube_challenge_provider": "external_optional_v1",
        }
        with (
            patch("browser_plane.video_resolver.video_resolver_readiness", return_value=ready),
            patch("browser_plane.video_resolver.subprocess.run", side_effect=[failure, success]) as run,
        ):
            result = resolve_video("https://youtu.be/abc")

        self.assertEqual(result["strategy"], "youtube-mweb")
        self.assertEqual(
            [attempt["status"] for attempt in result["attempts"]],
            ["failed", "succeeded"],
        )
        second_command = run.call_args_list[1].args[0]
        self.assertIn("youtube:player_client=mweb", second_command)

    def test_error_text_does_not_echo_urls(self) -> None:
        safe = _safe_error("failed GET https://example.invalid/path?x=1")
        self.assertNotIn("example.invalid", safe)
        self.assertIn("<url>", safe)

    def test_unready_resolver_fails_closed(self) -> None:
        with patch(
            "browser_plane.video_resolver.video_resolver_readiness",
            return_value={"ready": False},
        ):
            with self.assertRaises(VideoResolveError):
                resolve_video("https://example.com/video")


if __name__ == "__main__":
    unittest.main()
