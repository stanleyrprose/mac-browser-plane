from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from browser_plane.c0_transport import (
    C0BodyTooLarge,
    browser_challenge_evidence,
    curl_error_supports_impersonated_retry,
    fetch_impersonated,
)


class C0TransportTests(unittest.TestCase):
    def test_challenge_detection_is_evidence_based(self) -> None:
        body = b'<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>'
        self.assertEqual(
            browser_challenge_evidence(403, "text/html", body),
            "cloudflare_challenge",
        )
        self.assertIsNone(
            browser_challenge_evidence(403, "text/html", b"Forbidden"),
        )
        self.assertIsNone(
            browser_challenge_evidence(429, "text/plain", b"rate limited"),
        )

    def test_only_client_compat_curl_errors_retry(self) -> None:
        for code in (16, 35, 52, 56, 92):
            self.assertTrue(curl_error_supports_impersonated_retry(code))
        for code in (6, 7, 28, 60):
            self.assertFalse(curl_error_supports_impersonated_retry(code))

    def test_impersonated_fetch_is_bounded_and_browser_like(self) -> None:
        seen_user_agent: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                seen_user_agent.append(self.headers.get("User-Agent", ""))
                body = b"impersonated-ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = fetch_impersonated(
                f"http://127.0.0.1:{server.server_port}/",
                timeout_sec=5,
            )
            self.assertEqual(result.status, 200)
            self.assertEqual(result.body, b"impersonated-ok")
            self.assertTrue(seen_user_agent)
            self.assertIn("Chrome/", seen_user_agent[-1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_impersonated_fetch_enforces_body_limit(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b"x" * 4096
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(C0BodyTooLarge):
                fetch_impersonated(
                    f"http://127.0.0.1:{server.server_port}/",
                    timeout_sec=5,
                    max_bytes=1024,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
