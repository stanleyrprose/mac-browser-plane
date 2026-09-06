from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from mcp import Client, StdioServerParameters


AUTHORIZED_TOOLS = {
    "browser_capabilities",
    "browser_doctor",
    "browser_fetch",
    "browser_render",
    "browser_inspect",
    "browser_status",
    "browser_result",
    "browser_cancel",
}


def _server_command() -> str:
    """Resolve the installed local stdio MCP server next to this Python runtime."""
    candidate = Path(sys.executable).with_name("mac-browser-mcp")
    if not candidate.exists():
        raise RuntimeError(f"mac-browser-mcp not found next to runtime Python: {candidate}")
    return str(candidate)


def _parse_args_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"args-json must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("args-json must decode to a JSON object")
    return value


async def _list_tools() -> dict[str, Any]:
    params = StdioServerParameters(command=_server_command(), args=[])
    async with Client(params) as client:
        tools = await client.list_tools()
    names = [tool.name for tool in tools.tools]
    unexpected = sorted(set(names) - AUTHORIZED_TOOLS)
    missing = sorted(AUTHORIZED_TOOLS - set(names))
    return {
        "ok": not unexpected and not missing,
        "server": "mac-browser-plane",
        "transport": "stdio",
        "tools": names,
        "unexpected_tools": unexpected,
        "missing_tools": missing,
    }


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in AUTHORIZED_TOOLS:
        raise ValueError(f"tool is not authorized through the CodexPro bridge: {name}")

    params = StdioServerParameters(command=_server_command(), args=[])
    async with Client(params) as client:
        result = await client.call_tool(name, arguments)

    return {
        "ok": not bool(result.is_error),
        "tool": name,
        "is_error": bool(result.is_error),
        "structured_content": result.structured_content,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mac-browser-mcp-call",
        description=(
            "Local-only MCP client for CodexPro/automation bridges. It can call only the "
            "authorized Mac Browser Plane stdio tools."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List and verify the authorized Browser Plane MCP tools")

    call = sub.add_parser("call", help="Call one authorized Browser Plane MCP tool")
    call.add_argument("tool", choices=sorted(AUTHORIZED_TOOLS))
    call.add_argument("--args-json", default="{}", help="JSON object passed as MCP tool arguments")
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "list":
            payload = asyncio.run(_list_tools())
        else:
            payload = asyncio.run(_call_tool(args.tool, _parse_args_json(args.args_json)))
    except Exception as exc:  # CLI boundary: return machine-readable failure without traceback noise.
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if not payload.get("ok", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
