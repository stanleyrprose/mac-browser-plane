# Local Agent MCP Adapter v0 — Live Closure

Date: 2026-09-05
Status: PRODUCTION LOCAL PASS / BROWSER ENGINE REMAINS FROZEN

## Scope

This closure covers the post-R1 Local Agent MCP Adapter v0 only. It does not reopen the completed Mac Browser Plane R1 execution baseline.

The adapter remains a thin local interface over the already verified runtime:

```text
Local MCP host
-> stdio child process
-> mac-browser-mcp
-> existing SQLite JobStore
-> existing LaunchAgent worker
-> C0 / C1 / C2
```

No second Browser worker, network listener, HTTP MCP service, WebSocket endpoint, public port, or cross-host provider contract was introduced.

## Merged implementation

PR #14 merged to `main`.

Merged main SHA:

```text
ad697b9
```

GitHub feature and merged-main CI both PASS.

The implementation pins the official Python MCP SDK:

```text
mcp==2.1.1
```

The installed runtime now contains both:

```text
/Users/xu/agent-browser-runtime/app/venv/bin/browserctl
/Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

## Authorized MCP surface

Exactly eight tools are exposed:

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

Still not exposed:

```text
click / type / select / upload
arbitrary JavaScript
raw CDP
arbitrary Playwright code
C3 Browser Agent
headed human takeover
```

The agent-facing URL surface is also narrower than the raw CLI contract: absolute HTTP(S) only, with obvious localhost / `.local` / non-global literal IP targets rejected.

## Test and install verification

Local isolated Python 3.13 environment:

```text
26 / 26 tests PASS
compile PASS
100-job C0 mini soak = 100 / 100 SUCCEEDED
SQLite integrity = ok
remaining Profile Leases = 0
remaining Control Leases = 0
remaining Browser processes = 0
```

A real stdio subprocess MCP client successfully started `mac-browser-mcp`, listed exactly eight tools, called `browser_capabilities`, and exited with no residual adapter process.

The production installer was smoke-tested in an isolated runtime and created both `browserctl` and `mac-browser-mcp`.

## Production local installation

The merged main was installed through the existing non-editable runtime installer and the existing user LaunchAgent was reloaded using the normal `bootout -> bootstrap -> kickstart -k` path.

No root command or system-setting change was required.

Post-install `browserctl doctor`:

```text
status = READY
SQLite integrity = ok
WAL = enabled
synchronous = FULL
busy_timeout = 5000
Chrome = healthy
Playwright = healthy
stale profile leases = none
owned process ambiguity = none
```

## Installed MCP live smoke

The production-installed MCP executable was used through a real stdio client against `https://example.com`.

```text
browser_fetch
job_id = 095ed99d-3803-4d0a-95bc-631a762cd20a
state = SUCCEEDED
engine = c0-fetch
HTTP = 200

browser_render
job_id = 0803e211-bda1-4c58-bc4f-17f02bd75c3b
state = SUCCEEDED
engine = c1-playwright
HTTP = 200

browser_inspect
job_id = 811e44a6-f59b-44fe-94fd-9923d85119ef
state = SUCCEEDED
engine = c2-readonly-inspect
HTTP = 200
```

This proves the actual execution chain:

```text
MCP client
-> installed mac-browser-mcp
-> existing runtime queue
-> existing LaunchAgent worker
-> C0 / C1 / C2
```

The adapter did not execute Browser work in a parallel worker.

## Process / service boundary

After the MCP client exited:

```text
pgrep mac-browser-mcp -> no residual process
```

The only Browser Plane LaunchAgent remains:

```text
com.stanley.mac-browser-plane
```

There is no dedicated MCP LaunchAgent or daemon.

## Codex integration

Local Codex CLI natively supports stdio MCP. The adapter is registered globally as:

```text
name      = mac-browser-plane
enabled   = true
transport = stdio
command   = /Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

Rollback is explicit and local:

```text
codex mcp remove mac-browser-plane
```

## Hermes integration

The installed local Hermes version natively supports stdio MCP via `hermes mcp add/list/test`.

A direct connection probe discovered all eight tools. Because `hermes mcp add` requires an interactive final tool-selection prompt and the controlled shell is non-interactive, the same installed Hermes implementation was used to run its own validation, discovery, and `_save_mcp_server` path without hand-writing the YAML schema.

Public verification then returned:

```text
hermes mcp list
mac-browser-plane = enabled

hermes mcp test mac-browser-plane
transport = stdio
connected = PASS
connection time = 488 ms
tools discovered = 8
```

No LLM turn was sent merely to prove tool discovery, avoiding unnecessary inference usage.

Hermes rollback remains:

```text
hermes mcp remove mac-browser-plane
```

## Frozen boundaries after closure

The following remain unchanged:

```text
R1 egress = Mac direct only
C0 = strict-TLS acquisition
C1 = deterministic render/read
C2 = read-only diagnostics
C1 generic interaction = false
C3 Browser Agent = false
remote invocation = false
production_enabled for cross-host use = false
public Browser API = none
```

Codex/Hermes local MCP registration does not authorize SignalForge remote invocation and does not change the provider contract.

## Default next action

Do not add more Browser infrastructure by default.

Operate the local adapter with real Codex/Hermes tasks and collect evidence about:

1. C0 / C1 / C2 usage mix;
2. real failure classes;
3. whether any workflow repeatedly proves `INTERACTION_REQUIRED`;
4. evidence/disk growth;
5. whether the accepted manual-login cold-boot boundary causes real outages.

Only reopen the Browser engine when measured use proves a concrete need.

> Local Agent MCP Adapter v0 is production-local live verified. The Mac Browser Plane can now be consumed by local MCP-capable agents without adding a network service or expanding Browser execution authority. Browser engine development returns to frozen/evidence-triggered status.
