from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client, StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError

from browser_plane.mcp_adapter import _profile_mode, _submit_and_wait, _validate_browser_actions, _validate_url, mcp
from browser_plane.models import Egress, JobState, ProfileMode, TaskType


class _FakeJobs:
    def __init__(self) -> None:
        self.spec = None

    def submit(self, spec):
        self.spec = spec
        return "job-test-1"

    def wait(self, job_id: str, timeout_sec: float, poll_sec: float = 0.2):
        assert job_id == "job-test-1"
        return {
            "job_id": job_id,
            "state": JobState.SUCCEEDED.value,
            "created_at": "2026-09-05T00:00:00+00:00",
            "started_at": "2026-09-05T00:00:01+00:00",
            "finished_at": "2026-09-05T00:00:02+00:00",
            "failure_class": None,
            "partial_effect_possible": 0,
            "result_json": json.dumps({"engine": "c0-fetch", "status": 200}),
        }


class MCPAdapterContractTests(unittest.TestCase):
    def test_url_guard_rejects_non_web_and_obvious_local_targets(self) -> None:
        for value in (
            "file:///etc/passwd",
            "data:text/plain,hello",
            "javascript:alert(1)",
            "http://localhost:8000",
            "http://service.local/path",
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/",
            "http://[::1]/",
        ):
            with self.subTest(value=value), self.assertRaises(ToolError):
                _validate_url(value)
        self.assertEqual(_validate_url("https://example.com/path"), "https://example.com/path")

    def test_profile_mode_surface_is_intentionally_small(self) -> None:
        self.assertEqual(_profile_mode("ephemeral"), ProfileMode.EPHEMERAL)
        self.assertEqual(_profile_mode("exclusive-persistent"), ProfileMode.EXCLUSIVE_PERSISTENT)
        with self.assertRaises(ToolError):
            _profile_mode("storage-state")

    def test_browser_action_validation_accepts_use_surface_and_rejects_bad_steps(self) -> None:
        actions = _validate_browser_actions(
            [
                {"action": "navigate", "url": "https://example.com/next"},
                {"action": "click", "selector": "#go", "force": True},
                {"action": "type", "selector": "#q", "text": "tender"},
                {"action": "snapshot"},
            ]
        )
        self.assertEqual([item["action"] for item in actions], ["navigate", "click", "type", "snapshot"])
        self.assertTrue(actions[1]["force"])
        with self.assertRaises(ToolError):
            _validate_browser_actions([])
        with self.assertRaises(ToolError):
            _validate_browser_actions([{"action": "evaluate_js", "script": "1+1"}])
        with self.assertRaises(ToolError):
            _validate_browser_actions([{"action": "click"}])
        with self.assertRaises(ToolError):
            _validate_browser_actions([{"action": "click", "selector": "#go", "force": "true"}])

    def test_submit_and_wait_uses_existing_runtime_queue_not_a_second_worker(self) -> None:
        jobs = _FakeJobs()
        with patch("browser_plane.mcp_adapter._runtime", return_value=(object(), object(), jobs)):
            result = _submit_and_wait(
                task_type=TaskType.FETCH,
                url="https://example.com",
                queue_timeout_sec=30,
                max_run_sec=45,
                client_timeout_sec=60,
                evidence_policy="always",
            )
        self.assertEqual(result["state"], JobState.SUCCEEDED.value)
        self.assertIsNotNone(jobs.spec)
        self.assertEqual(jobs.spec.task_type, TaskType.FETCH)
        self.assertEqual(jobs.spec.egress, Egress.DIRECT)
        self.assertEqual(jobs.spec.profile_mode, ProfileMode.EPHEMERAL)
        self.assertFalse(jobs.spec.allow_egress_fallback)
        self.assertEqual(jobs.spec.retry_policy, "none")

    def test_submit_and_wait_preserves_c3_use_actions(self) -> None:
        jobs = _FakeJobs()
        actions = ({"action": "snapshot", "timeout_ms": 10000},)
        with patch("browser_plane.mcp_adapter._runtime", return_value=(object(), object(), jobs)):
            result = _submit_and_wait(
                task_type=TaskType.USE,
                url="https://example.com",
                profile="authenticated-work",
                profile_mode=ProfileMode.EXCLUSIVE_PERSISTENT,
                queue_timeout_sec=30,
                max_run_sec=90,
                client_timeout_sec=120,
                evidence_policy="always",
                control_mode="use",
                actions=actions,
            )
        self.assertEqual(result["state"], JobState.SUCCEEDED.value)
        self.assertEqual(jobs.spec.task_type, TaskType.USE)
        self.assertEqual(jobs.spec.actions, actions)
        self.assertEqual(jobs.spec.profile, "authenticated-work")
        self.assertEqual(jobs.spec.profile_mode, ProfileMode.EXCLUSIVE_PERSISTENT)


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_in_memory_mcp_capabilities_tool(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("browser_capabilities", {})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["provider_id"], "mac-mm-01")
        self.assertEqual(result.structured_content["local_agent_adapter"]["transport"], "stdio")
        self.assertFalse(result.structured_content["capabilities"]["remote_invocation"])

    async def test_mcp_exposes_only_the_authorized_v0_tools(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        self.assertEqual(
            names,
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
        self.assertNotIn("click", names)
        self.assertNotIn("evaluate_js", names)
        self.assertNotIn("raw_cdp", names)

    async def test_real_stdio_subprocess_surface(self) -> None:
        command = Path(sys.executable).with_name("mac-browser-mcp")
        self.assertTrue(command.exists())
        with tempfile.TemporaryDirectory() as tmp:
            params = StdioServerParameters(
                command=str(command),
                args=[],
                env={"BROWSER_PLANE_HOME": tmp},
            )
            async with Client(params) as client:
                tools = await client.list_tools()
                result = await client.call_tool("browser_capabilities", {})
        self.assertEqual(len(tools.tools), 9)
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["local_agent_adapter"]["transport"], "stdio")


if __name__ == "__main__":
    unittest.main()
