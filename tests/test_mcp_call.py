from __future__ import annotations

import json
import subprocess
import sys
import unittest

from browser_plane.mcp_call import AUTHORIZED_TOOLS, _parse_args_json


class McpCallUnitTests(unittest.TestCase):
    def test_parse_args_json_requires_object(self) -> None:
        self.assertEqual(_parse_args_json('{"url":"https://example.com"}'), {"url": "https://example.com"})
        with self.assertRaises(ValueError):
            _parse_args_json('[1,2,3]')
        with self.assertRaises(ValueError):
            _parse_args_json('{bad json')

    def test_authorized_surface_matches_adapter_contract(self) -> None:
        self.assertEqual(
            AUTHORIZED_TOOLS,
            {
                "browser_capabilities",
                "browser_doctor",
                "browser_fetch",
                "browser_render",
                "browser_use",
                "browser_inspect",
                "browser_status",
                "browser_result",
                "browser_cancel",
            },
        )


class McpCallStdioSmokeTests(unittest.TestCase):
    def _run(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, "-m", "browser_plane.mcp_call", *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        return json.loads(completed.stdout)

    def test_list_real_stdio_server(self) -> None:
        payload = self._run("list")
        self.assertTrue(payload["ok"])
        self.assertEqual(set(payload["tools"]), AUTHORIZED_TOOLS)
        self.assertEqual(payload["unexpected_tools"], [])
        self.assertEqual(payload["missing_tools"], [])

    def test_call_capabilities_real_stdio_server(self) -> None:
        payload = self._run("call", "browser_capabilities")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool"], "browser_capabilities")
        capabilities = payload["structured_content"]
        self.assertIsInstance(capabilities, dict)
        self.assertEqual(capabilities.get("provider_id"), "mac-mm-01")
        self.assertTrue(capabilities.get("production_enabled"))
        self.assertTrue(capabilities["capabilities"]["remote_invocation"])


if __name__ == "__main__":
    unittest.main()
