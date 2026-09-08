# Mac Browser Plane

Mac-centric local Browser Execution Plane implementing the frozen R1 v1.4.1 architecture.

**Current state:** Authorized R1 Operational Scope = **COMPLETE**. See `docs/R1-OPERATIONAL-BASELINE-CLOSURE-2026-09-04.md` for the implemented baseline, accepted operating boundaries, explicit deferrals, and evidence-based reopen rules.

## AI / Agent capability discovery

**Mac Browser Plane C0–C3 is operational.** Authorized agents should treat this Mac as an available browser execution plane rather than assuming only HTTP fetch is available.

Current capability status:

```text
C0 Fetch               COMPLETE
C1 Render              COMPLETE
C2 Read-only Inspect   COMPLETE
C3 Browser Use         COMPLETE
C3 Semantic Targeting  COMPLETE
Autonomous Browser Agent / embedded LLM planner  DEFERRED
```

Primary local MCP:

```text
mac-browser-plane
transport = stdio
```

Recommended discovery sequence for an MCP-capable caller:

```text
1. discover/connect mac-browser-plane
2. call browser_capabilities
3. call browser_doctor when readiness matters
4. choose:
   C0 -> browser_fetch
   C1 -> browser_render
   C2 -> browser_inspect
   C3 -> browser_use
```

`browser_use` is the operational C3 interaction surface. It supports deterministic multi-step browser work including `navigate`, `click`, `type`, `select`, `press`, `wait`, `snapshot`, `screenshot`, and `download`, plus CSS and semantic targeting (`role`/accessible `name`, `label`, `text_target`). The caller owns reasoning/planning; Browser Plane owns reliable execution.

See `docs/AI_CAPABILITY_ANNOUNCEMENT.md` for the portable announcement intended for ChatGPT/Codex/OpenClaw/Hermes/other agents, and `src/browser_plane/capabilities.json` for the machine-readable capability manifest.

**Discovery limitation:** no repository or MCP can guarantee that every possible AI agent will discover a capability automatically. Discovery requires that the caller can see this repository, receives `AGENTS.md`/README context, or has the `mac-browser-plane` MCP configured. The project therefore publishes the same truth through multiple discovery surfaces.

## Boundary

```text
Mac mini
= Browser Router / Runtime / State / Profiles / Evidence

R1 network egress
= Mac mini direct Internet connection only
```

This repository does **not** replace `vps-worker-plane` or Bangkok SignalForge. Existing VPS Direct HTTP/API/ETL stays in the VPS Worker Runtime. The old future VPS Browser/Crawlee R3 direction is superseded by this project.

SignalForge-to-Mac unattended production invocation is intentionally not implemented in R1.

## M1 scope

Implemented in the first milestone:

- local `browserctl` CLI;
- SQLite runtime state with WAL, `synchronous=FULL`, `busy_timeout=5000`;
- Job state/version CAS;
- idempotent submit;
- queue / run / cancel lifecycle;
- single active Runtime Worker enforced by local `worker.lock`;
- startup recovery for interrupted active Jobs / owned Browser processes / leases;
- Profile Lease and browser-session Control Lease;
- Browser Process Registry using PID + macOS process-start token;
- C0 Direct Fetch using macOS `/usr/bin/curl` for HTTP/HTTPS with normal TLS verification; every HTTP response is preserved as a private raw artifact with SHA-256, with `text_excerpt` added only for textual content;
- C1 Playwright attached to runtime-owned local Google Chrome;
- dynamic loopback CDP port (`--remote-debugging-port=0`);
- explicit 1440×900 Browser viewport;
- Evidence `result.json`;
- `browserctl doctor`;
- launchd worker template;
- M1 1000-job soak harness.

Network simplification for R1:

- Browser traffic uses the Mac mini direct Internet connection;
- no SEA/VPS browser egress routing;
- no China Browser egress.

M3A simplified C2 is now implemented:

- `task_type=inspect` launches a dedicated diagnostic Chrome session;
- read-only CDP allowlist only;
- captures console, request/response summaries, navigation history, performance metrics, accessibility-tree count, and screenshot;
- no `Runtime.evaluate`, navigation/input mutation, cookie/storage mutation, or request mocking through the diagnostic CDP surface;
- no separate `chrome-devtools-mcp` daemon/server.

A post-R1 **Local Agent MCP Adapter v0** now provides a thin stdio-only protocol surface over the same verified runtime for local Codex/Hermes-class callers. It does not add a second Browser worker or expand C0/C1/C2 semantics. See `docs/LOCAL_AGENT_MCP_ADAPTER_V0.md`.

Still deferred:

- autonomous C3 Browser Agent / embedded LLM planner;
- headed/human takeover;
- SignalForge remote provider invocation.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser,agent,dev]'
.venv/bin/browserctl init
.venv/bin/browserctl doctor
```

The runtime reuses the installed macOS Google Chrome at:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

Override only when necessary:

```bash
export BROWSER_PLANE_CHROME=/path/to/Chrome
```

No Playwright-managed Chromium download is required.

## Runtime state

Default:

```text
~/agent-browser-runtime/
├── state/runtime.db
├── profiles/
├── auth-state/
├── evidence/
├── logs/
└── run/
```

Set `BROWSER_PLANE_HOME` to override for tests/isolated deployments.

## CLI

Initialize:

```bash
.venv/bin/browserctl init
```

Synchronous local job:

```bash
.venv/bin/browserctl run --file examples/c1-smoke.json
```

Read-only diagnostic job:

```bash
.venv/bin/browserctl run --file examples/c2-smoke.json
```

Queue:

```bash
.venv/bin/browserctl submit --file job.json
.venv/bin/browserctl status <job-id>
.venv/bin/browserctl wait <job-id> --timeout 30
.venv/bin/browserctl result <job-id>
.venv/bin/browserctl cancel <job-id>
```

Worker:

```bash
.venv/bin/browserctl worker
```

Doctor:

```bash
.venv/bin/browserctl doctor
```

Machine-readable capability manifest:

```bash
.venv/bin/browserctl capabilities
```

This reports the authorized R1 boundary plus post-R1 interface slices: direct-only network egress, C0/C1/C2, deterministic C3 Browser Use, and PIC-v1 `pull_ssh_v1` production invocation for explicitly allowlisted SignalForge sources. The Mac still exposes no public Browser/MCP/CDP listener.

## Local Agent MCP Adapter

For local MCP-capable agents, the installed runtime also provides a stdio-only executable:

```text
/Users/xu/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

It exposes nine tools: capabilities, doctor, C0 fetch, C1 render, C2 inspect, C3 `browser_use`, job status, job result, and job cancel. `browser_use` executes a deterministic action sequence (`navigate`, `click`, `type`, `select`, `press`, `wait`, `snapshot`, `screenshot`, `download`) through the existing JobStore/LaunchAgent/Chrome path. Targeted actions accept either a CSS `selector` or one semantic target form: ARIA `role` (optionally with accessible `name`), `label`, or visible `text_target`; semantic targets may request `exact: true`. `snapshot` returns both a bounded body-text excerpt and a bounded Playwright AI-mode ARIA snapshot so an external agent can inspect an unfamiliar UI without receiving arbitrary DOM/JavaScript authority. `click` and `select` still accept optional `force: true` for known overlay/interception or hidden-native-control cases while ordinary interaction remains the default. It still does **not** expose arbitrary JavaScript, raw CDP, arbitrary Playwright objects, or an embedded/autonomous Browser Agent. The MCP host owns the child-process lifecycle; there is no MCP HTTP listener or second launchd service.

The original eight-tool v0 adapter contract is documented in `docs/LOCAL_AGENT_MCP_ADAPTER_V0.md`; C3/M3B extends that same stdio surface without adding another Browser runtime. Cross-host SignalForge production is a separate pull-only Provider Agent service which reuses this same local MCP stdio surface.

## SignalForge Provider Agent

PIC v1 production uses a dedicated launchd service which **pulls** bounded requests from Bangkok over restricted SSH and invokes `mac-browser-mcp` locally over stdio. It does not listen on any Mac TCP port and does not reuse an administrative SSH key. Install it from the reviewed production contract with:

```bash
python3 scripts/install_provider_launchd.py \
  --contract-source /path/to/signalforge/registry/Provider-Invocation-Contract-v1.json
```

The installer copies the reviewed contract to the runtime config tree and binds the service to the dedicated provider SSH identity. Production source authorization remains source/URL/capability specific; there is no automatic Direct HTTP failure -> Browser fallback.

SQLite-consistent runtime backup:

```bash
.venv/bin/browserctl backup
```

By default the snapshot is written under `~/agent-browser-runtime/backups/`. This backs up runtime SQLite state only; it does not copy authenticated Chrome profiles/cookies.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/soak_m1.py --jobs 1000 --browser-jobs 5 --submitters 8
```

## launchd

Do **not** run the LaunchAgent directly from a checkout under `~/Documents`. On macOS, `Documents` is TCC-protected; Terminal/Codex may have access while a background LaunchAgent does not. Production runtime is therefore installed separately under `~/agent-browser-runtime/app/`.

Install the release runtime, then the LaunchAgent:

```bash
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_launchd.py
```

The release venv is non-editable and independent from the development checkout. Updating source does not update the running release until `install_runtime.py` is run again.

Remove:

```bash
.venv/bin/python scripts/uninstall_launchd.py
```

The LaunchAgent requires a logged-in user session. Current host power/login behavior is recorded in `docs/HOST_READINESS.md`; R1 accepts manual macOS login after a cold power cycle rather than adding automatic login or a system LaunchDaemon.

## Security invariants

- never use the user's Personal Chrome profile;
- CDP stays loopback-only and dynamically allocated;
- no public `0.0.0.0:9222`;
- no TLS verification bypass;
- ambiguous Browser process ownership fails closed;
- browser/session mutation has one control owner;
- runtime state, backup, doctor/evidence JSON, and diagnostic screenshots are written `0600`; runtime/profile/evidence directories are `0700`;
- R1 has no cross-host Browser API;
- Local Agent MCP is stdio-only and starts no network listener;
- Local Agent MCP does not expose generic interaction, arbitrary JavaScript, or raw CDP;
- R1 does not install Browser runtime on VPS nodes.
