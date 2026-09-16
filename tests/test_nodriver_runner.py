from __future__ import annotations

import unittest

from browser_plane.nodriver_runner import _string_value, _wait_for_rendered_content


class _RemoteString:
    def __init__(self, value: str):
        self.value = value


class _HydratingPage:
    def __init__(self) -> None:
        self.attempt = 0
        self.sleeps: list[float] = []

    async def get_content(self) -> str:
        return "<html><body>loading</body></html>" if self.attempt == 0 else "<html><body>ready</body></html>"

    async def evaluate(self, _expression: str, *, return_by_value: bool) -> object:
        assert return_by_value is True
        value: object = _RemoteString("") if self.attempt == 0 else "ready business content"
        self.attempt += 1
        return value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class _EmptyPage:
    async def get_content(self) -> str:
        return "<html><body></body></html>"

    async def evaluate(self, _expression: str, *, return_by_value: bool) -> object:
        assert return_by_value is True
        return _RemoteString("")

    async def sleep(self, _seconds: float) -> None:
        return None


class NodriverHydrationTests(unittest.IsolatedAsyncioTestCase):
    def test_string_value_accepts_plain_and_remote_strings(self) -> None:
        self.assertEqual(_string_value("plain"), "plain")
        self.assertEqual(_string_value(_RemoteString("remote")), "remote")
        self.assertEqual(_string_value(object()), "")

    async def test_wait_for_rendered_content_allows_bounded_hydration(self) -> None:
        page = _HydratingPage()
        html, body_text, wait_ms = await _wait_for_rendered_content(
            page,
            max_wait_sec=1.0,
            poll_interval_sec=0.0,
        )
        self.assertIn("ready", html)
        self.assertEqual(body_text, "ready business content")
        self.assertGreaterEqual(wait_ms, 0)
        self.assertEqual(page.sleeps, [0.0])

    async def test_wait_for_rendered_content_fails_closed_when_body_stays_empty(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "rendered body remained empty"):
            await _wait_for_rendered_content(
                _EmptyPage(),
                max_wait_sec=0.0,
                poll_interval_sec=0.0,
            )


if __name__ == "__main__":
    unittest.main()
