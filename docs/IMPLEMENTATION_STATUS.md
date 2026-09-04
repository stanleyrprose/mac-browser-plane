# Implementation Status — M1 Core Local Runtime

**Baseline:** Mac-Centric Browser Execution Plane R1 v1.4.1 FROZEN
**Branch:** `feat/m1-core-runtime`
**Status:** **M1 COMPLETE / LOCAL PRODUCTION BASELINE PASS**

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
- [x] C0 Direct Fetch
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

## Final verification

- Python compilation: PASS
- Core tests: **11/11 PASS**
- `browserctl init`: PASS
- `browserctl doctor`: **READY**
- Live synchronous C1 local Chrome smoke: PASS
- LaunchAgent queued C1 smoke: PASS
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

## Explicitly deferred

- SEA egress / M2
- China Browser / Gate C
- C2 Chrome DevTools MCP / M3A
- C3 Browser Use / M3B
- headed/human takeover
- SignalForge-to-Mac unattended Provider Invocation Contract

## Cross-project invariant

Existing `vps-worker-plane` Direct HTTP/API/ETL and Bangkok SignalForge remain unchanged. VPS Browser/Crawlee R3 is superseded and must not be implemented.

## M1 freeze statement

> Mac mini now owns the verified local Browser Runtime baseline. The running LaunchAgent consumes Browser Jobs from the local SQLite state store and executes C0/C1 locally. No VPS Browser runtime and no cross-host SignalForge invocation were introduced.
