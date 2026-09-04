# Implementation Status — M1 Core + M3A Read-only Diagnostics

**Baseline:** Mac-Centric Browser Execution Plane R1 v1.4.1 FROZEN
**Branch:** `main`
**Status:** **M1 COMPLETE / M3A PASS / RECOVERY + BACKUP + SECURITY HARDENED / REAL-SITE C0 VALIDATED**

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
- [x] C0 Direct Fetch via macOS system curl for HTTP/HTTPS; local `data:` fixture path retained only for tests
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

## Final verification

- Python compilation: PASS
- Core tests: **18/18 PASS** with `ResourceWarning` promoted to error
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
- C3 Browser Use / M3B
- headed/human takeover
- SignalForge-to-Mac unattended Provider Invocation Contract

## Cross-project invariant

Existing `vps-worker-plane` Direct HTTP/API/ETL and Bangkok SignalForge remain unchanged. VPS Browser/Crawlee R3 is superseded and must not be implemented.

## M1 freeze statement

> Mac mini now owns the verified local Browser Runtime baseline. The running LaunchAgent consumes Browser Jobs from the local SQLite state store and executes C0/C1 plus dedicated read-only C2 diagnostics locally. No VPS Browser runtime, regional egress layer, extra DevTools daemon, or cross-host SignalForge invocation was introduced.
