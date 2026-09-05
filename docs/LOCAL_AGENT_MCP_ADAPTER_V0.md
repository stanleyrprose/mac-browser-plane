# Local Agent MCP Adapter v0

Date: 2026-09-05
Status: LOCAL TEST PASS / MERGE PENDING

## Purpose

Expose the already verified Mac Browser Plane C0/C1/C2 runtime to local MCP-capable agents without adding a network service or a second Browser worker.

```text
Codex / Hermes / local MCP host
        |
        | stdio child process
        v
mac-browser-mcp
        |
        | existing SQLite JobStore
        v
LaunchAgent Browser Worker
        |
        +-- C0 strict-TLS fetch
        +-- C1 deterministic Chrome render
        +-- C2 read-only diagnostics
```

The adapter is an interface slice, not a new execution plane.

## Transport boundary

v0 is **stdio-only**.

```text
network listener = NONE
HTTP MCP server  = NONE
WebSocket        = NONE
public port      = NONE
remote provider  = NONE
```

A local MCP host launches this executable as a child process:

```text
~/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

The MCP process does not become a second Browser worker. Execution tools submit jobs into the existing SQLite queue and wait for the installed LaunchAgent worker to consume them.

## Authorized tools

Exactly eight tools are exposed:

| Tool | Boundary |
|---|---|
| `browser_capabilities` | Read machine-readable capability/security manifest |
| `browser_doctor` | Run existing Browser Plane readiness checks |
| `browser_fetch` | C0 strict-TLS HTTP(S) acquisition + raw evidence |
| `browser_render` | C1 deterministic Chrome render/read only |
| `browser_inspect` | C2 read-only diagnostics + screenshot evidence |
| `browser_status` | Read one job lifecycle state |
| `browser_result` | Read one job result/failure payload |
| `browser_cancel` | Request cancellation of queued/running job |

Not exposed:

```text
click
type
select
upload
download
arbitrary JavaScript
Runtime.evaluate
raw CDP
arbitrary Playwright code
Browser Agent / C3
headed human takeover
```

## Agent-facing URL guard

The CLI runtime is unchanged. The MCP interface adds a narrower model-controlled input boundary:

- only absolute `http://` and `https://` URLs;
- reject `file:`, `data:`, `javascript:` and other schemes;
- reject `localhost`, `.localhost`, `.local` and non-global literal IP addresses;
- R1 remains direct Mac egress only;
- TLS verification remains mandatory.

This guard is deliberately small. It prevents obvious local-machine/internal-literal targets but is not represented as a general network sandbox or DNS-rebinding defense.

## Profiles

The adapter exposes only the existing named runtime profiles:

```text
public-research
authenticated-work
development
```

For C1 render, v0 permits:

```text
ephemeral
exclusive-persistent
```

`storage-state` cloning remains deferred.

## Dependency decision

The adapter uses the official MCP Python SDK and pins the deployed adapter dependency to:

```text
mcp==2.1.1
```

The dependency is installed through the `agent` optional extra. The production runtime installer installs:

```text
[browser,agent]
```

so the installed release contains both:

```text
browserctl
mac-browser-mcp
```

No separate Node runtime or Chrome DevTools MCP daemon is introduced.

## Development install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser,agent,dev]'
```

## Production install path

The existing release installer remains authoritative:

```bash
.venv/bin/python scripts/install_runtime.py
```

Expected installed executable:

```text
/Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

The LaunchAgent remains the existing Browser worker; no second launchd service is added for MCP because the MCP host owns the stdio child-process lifecycle.

## Host configuration contract

Any local MCP host only needs the absolute command:

```text
/Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

No args are required for the default runtime home. If an isolated runtime is intentionally needed, the host may pass:

```text
BROWSER_PLANE_HOME=/path/to/runtime
```

The adapter must never be configured as a public or remote HTTP endpoint.

## Verification gates

Before production installation, require:

1. official SDK installs on the supported runtime Python;
2. all Browser Plane core + adapter tests pass;
3. in-memory MCP client can call `browser_capabilities`;
4. real stdio subprocess client lists exactly eight authorized tools;
5. install-runtime smoke creates both executables;
6. existing C0 mini soak remains PASS;
7. `browserctl doctor` remains READY after production installation;
8. a real local MCP `browser_fetch` against a public URL succeeds through the installed LaunchAgent worker;
9. no new listening TCP socket/process is introduced by the adapter.

## Reopen rule

Do not add interaction tools merely because MCP exists.

Only add the smallest interaction capability after a real local-agent workflow proves:

```text
C0 insufficient
AND
C1 render/read insufficient
AND
C2 diagnostics prove a deterministic interaction is required
```

C3 autonomous Browser Agent remains a separate future decision.
