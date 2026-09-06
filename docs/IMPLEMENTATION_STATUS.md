# Implementation Status — R1 Authorized Operational Baseline

**Baseline:** Mac-Centric Browser Execution Plane R1 v1.4.1 FROZEN
**Branch:** `main`
**Status:** **AUTHORIZED R1 OPERATIONAL SCOPE COMPLETE**
**Closure:** `docs/R1-OPERATIONAL-BASELINE-CLOSURE-2026-09-04.md`

## Implemented

- [x] Independent `mac-browser-plane` repository
- [x] Local runtime directory model
- [x] SQLite runtime DB
- [x] WAL / synchronous FULL / busy_timeout=5000
- [x] Job state/version CAS
- [x] Idempotent submit
- [x] Queued cancel and running cancel finalization
- [x] Profile Lease exclusivity
- [x] Browser-session Control Lease
- [x] Lease heartbeat primitives
- [x] Browser Process Registry
- [x] PID + macOS start-token ownership verification
- [x] Graceful terminate → force-kill last-resort ladder
- [x] C0 Direct Fetch via macOS system curl for HTTP/HTTPS; full raw response preserved as private evidence artifact with SHA-256; textual responses also expose a bounded `text_excerpt`; local `data:` fixture path retained only for tests
- [x] C1 Playwright Direct
- [x] Runtime-owned local Google Chrome
- [x] Dynamic loopback CDP port
- [x] Explicit viewport
- [x] Persistent-profile stale `DevToolsActivePort` cleanup under exclusive lease
- [x] Evidence result file
- [x] `browserctl init/submit/run/status/result/wait/cancel/worker/doctor`
- [x] Non-editable release runtime installed under `~/agent-browser-runtime/app/`
- [x] User LaunchAgent installed and verified
- [x] Unit/integration test suite
- [x] M1 1000-job soak harness
- [x] Explicit SQLite read-connection lifecycle (`RuntimeDB.connection()`)
- [x] Single active Runtime Worker via local file lock
- [x] Startup recovery to `RECOVERY_REQUIRED`
- [x] Safe owned-process reconciliation before lease release
- [x] Online SQLite-consistent `browserctl backup`
- [x] Backup integrity check + restore smoke
- [x] Runtime/state/evidence/backup sensitive files hardened to `0600`; runtime/profile/evidence directories to `0700`
- [x] C2 `task_type=inspect`
- [x] Dedicated diagnostic Browser Session
- [x] `DEVTOOLS_READ` Control Lease owner
- [x] Explicit CDP allowlist with mutating methods denied
- [x] Console / request / response diagnostic capture
- [x] Navigation history / performance metrics / accessibility-tree diagnostics
- [x] Diagnostic screenshot evidence

## Post-R1 interface slice — Local Agent MCP Adapter v0

This does **not** reopen or expand the completed R1 Browser execution baseline. It adds only a local stdio protocol adapter over the existing C0/C1/C2 JobStore/LaunchAgent execution path.

- [x] official Python MCP SDK pinned as `mcp==2.1.1` under the `agent` optional dependency;
- [x] installed `mac-browser-mcp` stdio entry point;
- [x] exactly eight tools: capabilities / doctor / fetch / render / inspect / status / result / cancel;
- [x] execution tools submit to the existing SQLite JobStore and never start a second Browser worker;
- [x] agent-facing HTTP(S)-only URL guard rejects obvious local/non-global literal targets;
- [x] no HTTP/WebSocket MCP listener, public port, extra launchd service, arbitrary JavaScript, raw CDP, click/type, or C3 Browser Agent surface;
- [x] capability manifest records the local adapter separately while cross-host `production_enabled=false`, `invocation_mode=local_cli_only`, and `remote_invocation=false` remain unchanged.

Detailed contract: `docs/LOCAL_AGENT_MCP_ADAPTER_V0.md`.
Live closure: `docs/LOCAL_AGENT_MCP_ADAPTER_V0-LIVE-CLOSURE-2026-09-05.md`.

Post-R1 adapter production-local verification:

- [x] PR #14 merged to `main` at `ad697b9`; feature and merged-main CI PASS;
- [x] isolated Python 3.13 test suite **26/26 PASS**;
- [x] real stdio subprocess MCP handshake lists exactly eight authorized tools;
- [x] production installer creates both `browserctl` and `mac-browser-mcp`;
- [x] installed adapter live C0/C1/C2 calls against `https://example.com` all `SUCCEEDED / HTTP 200`;
- [x] post-install `browserctl doctor = READY`;
- [x] no residual `mac-browser-mcp` process and no additional MCP launchd service;
- [x] local Codex registered `mac-browser-plane` as enabled stdio MCP;
- [x] local Hermes registered `mac-browser-plane` as enabled stdio MCP and `hermes mcp test` discovered 8/8 tools;
- [x] Browser engine returns to frozen/evidence-triggered status after adapter closure.

## Post-R1 interface slice — C3 Browser Use / M3B

M3B adds deterministic multi-step browser interaction on top of the same runtime. It does not add a second Browser worker, network listener, LLM planner, or human-takeover subsystem.

- [x] `TaskType.USE` is distinct from the still-deferred autonomous `TaskType.AGENT`;
- [x] C3 reuses the existing SQLite JobStore, LaunchAgent worker, Profile Lease, Control Lease, Browser Process Registry, heartbeat, cancellation, and recovery path;
- [x] MCP adds a ninth tool, `browser_use`;
- [x] supported actions: `navigate`, `click`, `type`, `select`, `press`, `wait`, `snapshot`, `screenshot`, `download`; `click` and `select` support explicit `force: true` for known overlay/interception or hidden-native-control cases;
- [x] screenshot/download artifacts remain under the runtime evidence tree with `0700` directories and `0600` files;
- [x] timeout/failure/cancel semantics mark `partial_effect_possible=true` for C3 jobs when an interaction may already have occurred;
- [x] arbitrary JavaScript and raw CDP remain outside the C3 action contract;
- [x] production runtime reinstall + real stdio **9/9** tool verification;
- [x] live C3 action smoke through the installed LaunchAgent worker: `https://example.com` -> click -> `https://www.iana.org/help/example-domains`, snapshot + screenshot, job `21623dd9-4cee-421b-a54f-f86bca7073fa`, `SUCCEEDED`;
- [x] Cloud ChatGPT -> CodexPro -> `browser_use` live verification;
- [x] post-live `browserctl doctor = READY`; SQLite integrity `ok`, no stale profile leases, no Browser Process Registry ownership residue;
- [x] installed-runtime source test suite **33/33 PASS**;
- [x] real-business acceptance on MPT reproduced a carousel overlay intercepting normal clicks; `force: true` regression path was added and live-verified without changing the default click behavior;
- [x] real-business acceptance on MPA: C3 opened the tender list, clicked the latest 2026-08-21 tender into its detail page, C2 identified the embedded `Ctnr22Unit-Tender-2026.pdf`, and C0 preserved the raw 99,797-byte PDF with HTTP 200 and SHA-256 evidence;
- [x] real-business acceptance on Myanmar National Trade Portal: a Materialize CSS hidden native `<select>` reproduced the default visibility timeout; `select force: true` was added and live-verified with `type -> select(force) -> press -> wait -> snapshot -> screenshot`, job `27672825-e1ad-4a0d-91b9-3df560867131`, `SUCCEEDED`;
- [x] current multi-client verification: Cloud ChatGPT C3 via CodexPro PASS; OpenClaw direct stdio discovery **9 tools** and C3 live PASS; Hermes direct stdio discovery **9 tools** and C3 live PASS; Codex direct stdio registration points at the production runtime and is enabled, while the latest agent live recheck was blocked before tool execution by provider usage quota rather than MCP transport.

## Final verification

- Python compilation: PASS
- Core tests: **19/19 PASS** with `ResourceWarning` promoted to error
- Startup recovery owned-process/lease test: PASS
- Worker lock exclusivity test: PASS
- `browserctl init`: PASS
- `browserctl doctor`: **READY**
- Live synchronous C1 local Chrome smoke: PASS
- LaunchAgent queued C1 smoke: PASS
- Live synchronous C2 read-only inspect smoke: PASS
- LaunchAgent queued C2 inspect smoke: PASS
- Post-C2 doctor: READY
- Installed LaunchAgent holds `worker.lock`; second worker returns `WORKER_ALREADY_RUNNING`: PASS
- Recovery-hardening 1000-job soak: **1000/1000 SUCCEEDED**
- Online SQLite backup while LaunchAgent running: PASS (`integrity=ok`)
- Backup restore smoke into a fresh runtime DB: PASS
- Live C2 security smoke: runtime DB, `result.json`, and `screenshot.png` are `0600`: PASS
- Real-site MPT Tender validation: original Python-urllib C0 failed strict TLS chain validation; C1/C2 both returned HTTP 200
- C0 switched to macOS `/usr/bin/curl` without TLS bypass; same MPT Tender URL then returned HTTP 200 with ~80 KB HTML: PASS
- Real-site MPA Tender list: C0 HTTP 200 / ~252 KB HTML; full `response.html` contains current tender dates/titles: PASS
- Real-site Ministry of Commerce 2026 Notifications: C0 HTTP 200 / ~108 KB HTML with notification list present in static HTML: PASS
- Real MPA tender PDF: C0 HTTP 200 / 78,480 bytes; raw `response.pdf` preserved with SHA-256 and mode `0600`: PASS
- Ministry of Border Affairs tender pagination: C0 page 0/page 1 both HTTP 200 with different content; visible `Load More` resolves to ordinary `?page=N` links: PASS
- Myanmar National Trade Portal legal filtering/pagination: server-rendered result list, ordinary `?page=N` pagination, GET-based filter; direct keyword filter returned exactly 1/1 target result: PASS
- Host readiness audit: AC system sleep disabled (`sleep=0`), power-failure restart enabled (`autorestart=1`), WindowServer/user session healthy, LaunchAgent running: PASS
- Cold power-cycle boundary: no automatic login configured; after auto-restart one manual macOS login is required before the user LaunchAgent can return Browser Plane to READY: ACCEPTED R1 BOUNDARY
- Persistent profile run #1: PASS
- Persistent profile run #2 using same profile: PASS
- 1000-job soak: **1000/1000 SUCCEEDED**
  - concurrent submitters: 8
  - C0 jobs: 995
  - real C1 Chrome/Playwright jobs: 5
  - SQLite integrity: `ok`
  - remaining Profile Leases: 0
  - remaining Control Leases: 0
  - Browser Process Registry `RUNNING`: 0
- Post-soak doctor: READY

## Deployment finding fixed during M1

The first LaunchAgent implementation executed an editable virtualenv from a checkout under `~/Documents`. The LaunchAgent process remained alive but Python initialization stalled before entering application code.

The deployment was corrected to separate development source from the installed runtime:

```text
~/Documents/mcpx-projects/mac-browser-plane
= development checkout

~/agent-browser-runtime/app/venv
= non-editable installed runtime used by launchd
```

This avoids relying on background-process access to macOS TCC-protected `Documents` and prevents an in-progress source checkout from directly becoming the running service.

## Persistent profile finding fixed during M1

A second consecutive run against the same persistent Chrome profile initially failed with `ECONNREFUSED` because the old random `DevToolsActivePort` discovery file remained in the profile directory.

The runtime now removes only this runtime-owned discovery file while holding the exclusive Profile Lease before spawning the next owned Chrome process. It does **not** delete Chrome SingletonLock/SingletonCookie, cookies, or profile content.

## R1 network simplification decision

Browser traffic uses the **Mac mini direct Internet connection only**. Websites therefore see the Mac mini's current public egress IP.

The previously planned SEA/VPS egress path was intentionally dropped before merge because it added SSH tunnel, proxy, edge-health and routing state without a current business need.

Current rule:

```text
R1 Browser egress = direct only
```

Any future regional egress requirement must be proposed separately with a concrete source/business need before implementation.

## M3A simplification decision

M3A implements the required read-only diagnostic behavior directly through the existing Playwright CDP session instead of installing a separate `chrome-devtools-mcp` server now.

Reason:

```text
same diagnostic capability needed now
+
zero additional daemon / Node runtime / MCP lifecycle
```

If Hermes/Codex later needs an MCP protocol surface, add a thin adapter around this already-tested diagnostic boundary rather than rebuilding the runtime.

## Explicitly deferred

- SEA/VPS Browser egress
- China Browser egress
- separate Chrome DevTools MCP adapter/server
- autonomous Browser Agent / LLM planner
- headed/human takeover
- SignalForge-to-Mac unattended Provider Invocation Contract

## Cross-project invariant

Existing `vps-worker-plane` Direct HTTP/API/ETL and Bangkok SignalForge remain unchanged. VPS Browser/Crawlee R3 is superseded and must not be implemented.

## M1 freeze statement

> Mac mini now owns the verified local Browser Runtime baseline. The running LaunchAgent consumes Browser Jobs from the local SQLite state store and executes C0/C1 plus dedicated read-only C2 diagnostics locally. No VPS Browser runtime, regional egress layer, extra DevTools daemon, or cross-host SignalForge invocation was introduced.
