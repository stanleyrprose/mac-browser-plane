# Cloud ChatGPT via CodexPro — Mac Browser Plane MCP Bridge

Date: 2026-09-06
Status: PRODUCTION LOCAL PASS / CLOUD CHAT VIA CODEXPRO LIVE VERIFIED

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
-> C0 / C1 / C2 / C3 / local Artifact OCR
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

The bridge is intentionally not a generic MCP launcher. It resolves only the `mac-browser-mcp` executable in the same runtime environment and permits the current ten-tool Browser Plane MCP contract:

```text
browser_capabilities
browser_doctor
artifact_ocr
browser_fetch
browser_render
browser_use
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
C3 Browser Use                  enabled
C3 autonomous Browser Agent     disabled
remote Browser API              none
public MCP port                 none
SignalForge pull-SSH invocation enabled, source/URL/capability allowlisted
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

### Current client verification matrix

| Client | Path | Current discovery | C3 live status |
| --- | --- | --- | --- |
| Cloud ChatGPT | `ChatGPT -> CodexPro -> mac-browser-mcp-call -> mac-browser-mcp` | current **10-tool** local contract | **PASS** (`browser_use` and `artifact_ocr` live verified) |
| OpenClaw | direct local stdio to `mac-browser-mcp` | current MCP exposes **10 tools**; prior client probe recorded 9 before OCR P0 | **PASS** (`browser_use` live verified to IANA; OCR available by MCP discovery) |
| Hermes | direct local stdio to `mac-browser-mcp` | current MCP exposes **10 tools**; prior client test recorded 9 before OCR P0 | **PASS** (`browser_use` one-shot live verified to IANA; OCR available by MCP discovery) |
| Codex CLI/Desktop config | direct local stdio to `mac-browser-mcp` | enabled and points at the production runtime | **CONFIG READY**; the latest agent-run recheck was blocked before tool execution by the Codex provider usage quota, not by MCP transport |

The historical 8-tool verification records below remain valid for the pre-C3 baseline, and the later 9-tool records remain valid for the pre-OCR C3 baseline. The current local production contract is 10 tools because Artifact OCR P0 added `artifact_ocr`; the SignalForge Provider contract remains narrower and does not authorize OCR yet.

## Initial bridge live verification — C0-C2 baseline

PR #16 merged to `main` and merged-main CI passed.

The production runtime was reinstalled and the existing user LaunchAgent reloaded. From a cloud ChatGPT conversation using the CodexPro plugin, the bridge was invoked on the Mac and successfully traversed the real local MCP path:

```text
ChatGPT Web
-> CodexPro
-> /Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp-call
-> mac-browser-mcp (stdio)
-> Browser Plane worker
-> C0 fetch
```

Tool-surface verification:

```text
mac-browser-mcp-call list
ok = true
tools = 8 / 8
missing_tools = []
unexpected_tools = []
```

Real cloud-chat browser job:

```text
URL        = https://mpt.com.mm/en/about-home/tenders/
job_id     = c5f46294-440c-471f-9cf7-b6e577b5468b
state      = SUCCEEDED
engine     = c0-fetch
HTTP       = 200
body_bytes = 80,226
elapsed_ms = 541
```

Post-verification `browserctl doctor` returned `READY`, SQLite integrity `ok`, no stale profile leases, and no browser-process ownership ambiguity.

This proves that cloud ChatGPT can consume the existing Mac Browser Plane MCP through CodexPro without making the MCP remotely network-addressable.

## M3B / C3 Browser Use bridge extension — 2026-09-06

The installed production runtime was reinstalled from `feat/m3b-browser-use` and the LaunchAgent reloaded. From this cloud ChatGPT conversation, CodexPro invoked the installed bridge and verified the expanded surface:

```text
mac-browser-mcp-call list
ok = true
tools = 9 / 9
missing_tools = []
unexpected_tools = []
```

A real C3 interaction job was then executed through the same path:

```text
ChatGPT Web
-> CodexPro
-> mac-browser-mcp-call call browser_use
-> mac-browser-mcp (stdio)
-> SQLite JobStore
-> existing LaunchAgent worker
-> runtime-owned Chrome / Playwright
```

Live job:

```text
start_url   = https://example.com
interaction = snapshot -> click(a) -> wait(body) -> snapshot -> screenshot
final_url   = https://www.iana.org/help/example-domains
job_id      = 21623dd9-4cee-421b-a54f-f86bca7073fa
state       = SUCCEEDED
engine      = c3-browser-use
HTTP        = 200
```

Post-live `browserctl doctor` returned `READY`, SQLite integrity `ok`, stale profile leases `[]`, Browser Process Registry ownership residue `[]`, and the installed-runtime source suite passed **33/33** tests.

## M3C / C3 Semantic Targeting bridge extension — 2026-09-08

PR #22 merged to `main` at `55836c3`, with both GitHub Actions `test` checks passing. The merged runtime was reinstalled and the LaunchAgent reloaded without changing the MCP transport or tool count.

The capability manifest now advertises:

```text
c3_browser_use        = true
c3_semantic_targeting = true
c3_aria_snapshot      = true
c3_browser_agent      = false
```

A cloud ChatGPT live job then exercised semantic targeting rather than a CSS selector:

```text
ChatGPT Web
-> CodexPro
-> mac-browser-mcp-call call browser_use
-> mac-browser-mcp (stdio)
-> existing LaunchAgent worker
-> runtime-owned Chrome / Playwright

start_url   = https://example.com
interaction = snapshot -> click(role=link) -> wait(body) -> snapshot -> screenshot
final_url   = https://www.iana.org/help/example-domains
job_id      = ce164bea-3e32-4741-aebf-323d8e182f73
state       = SUCCEEDED
engine      = c3-browser-use
HTTP        = 200
```

Both live snapshots returned bounded Playwright AI-mode ARIA trees, including the `Learn more` link on the first page and the `Example Domains` heading after navigation. The smoke did not require a CSS selector for the click and did not expose arbitrary JavaScript, raw CDP, or an embedded LLM planner.

Post-live `browser_doctor` returned `READY`, SQLite integrity `ok`, stale Profile Leases `[]`, Browser Process Registry ownership residue `[]`, and the post-install source suite passed **34/34** tests.
