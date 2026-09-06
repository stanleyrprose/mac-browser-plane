# Cloud ChatGPT via CodexPro — Mac Browser Plane MCP Bridge

Date: 2026-09-06
Status: IMPLEMENTED / LIVE VERIFICATION PENDING

## Purpose

Allow a cloud ChatGPT conversation that already has the CodexPro plugin to invoke the existing local Mac Browser Plane MCP without exposing the MCP server on the network.

The path is:

```text
ChatGPT Web
-> CodexPro controlled Mac bridge
-> mac-browser-mcp-call
-> local stdio
-> mac-browser-mcp
-> existing SQLite JobStore
-> existing LaunchAgent worker
-> C0 / C1 / C2
```

## Why this path

CodexPro already provides the authenticated, allowlisted bridge from cloud ChatGPT to this Mac. Therefore ChatGPT does not need a public MCP URL, Secure MCP Tunnel, HTTP listener, reverse tunnel, VPN, or new daemon merely to use Browser Plane from this chat surface.

The local MCP remains stdio-only.

## Bridge command

Installed entry point:

```text
/Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp-call
```

Supported forms:

```bash
mac-browser-mcp-call list

mac-browser-mcp-call call browser_fetch \
  --args-json '{"url":"https://example.com"}'
```

The bridge is intentionally not a generic MCP launcher. It resolves only the `mac-browser-mcp` executable in the same runtime environment and permits only the eight frozen Browser Plane MCP tools:

```text
browser_capabilities
browser_doctor
browser_fetch
browser_render
browser_inspect
browser_status
browser_result
browser_cancel
```

If the MCP server later exposes an unexpected tool, `mac-browser-mcp-call list` reports the contract mismatch instead of silently broadening cloud-chat authority.

## Security boundary

This does not change Browser Plane authority:

```text
C0 strict-TLS acquisition       enabled
C1 deterministic render/read    enabled
C2 read-only diagnostics        enabled
C1 generic interaction          disabled
C3 Browser Agent                disabled
remote Browser API              none
public MCP port                 none
remote_invocation capability    false
```

`mac-browser-mcp-call` is only a local MCP client. CodexPro remains the remote access/control boundary.

## Other local agents

Codex, Hermes, and OpenClaw continue to connect directly to `mac-browser-mcp` over local stdio. They do not need this CodexPro bridge CLI.

```text
Codex / Hermes / OpenClaw
-> mac-browser-mcp (stdio)

ChatGPT Web
-> CodexPro
-> mac-browser-mcp-call
-> mac-browser-mcp (stdio)
```

One Browser Runtime and one MCP contract are reused by all clients.
