# Architecture

## 1. Goal

Mac Browser Plane provides one bounded Browser Execution Plane on the Mac mini for local AI clients and explicitly authorized remote provider jobs. It centralizes browser state, lifecycle, ownership, routing, evidence, and recovery while leaving task reasoning/planning outside the runtime.

Design principle: **one Browser Plane, one worker/state authority, multiple bounded invocation surfaces**.

## 2. Non-goals

The runtime is not:

- an autonomous LLM Browser Agent;
- a public browser-as-a-service endpoint;
- a generic arbitrary-JavaScript/Playwright/CDP shell;
- a VPS browser runtime;
- a regional proxy/egress fabric;
- a second state database per browser engine;
- a human-takeover/VNC platform.

## 3. Component model

```text
                           CALLERS
        ┌────────────────────┼─────────────────────┐
        │                    │                     │
   browserctl CLI       MCP stdio clients    SignalForge/BKK
        │                    │                     │
        │              mac-browser-mcp             │
        │                    │                restricted SSH
        │                    │                     ▲
        │                    │              Provider Agent
        └───────────────┬────┴─────────────────────┘
                        │ local bounded calls
                        ▼
                 SQLite JobStore
                        │
              Job state + version CAS
                        │
               launchd Runtime Worker
                        │
       ┌────────────────┼─────────────────┐
       │                │                 │
    leases         process registry    executor/router
       │                │                 │
       │          PID + start token       ├─ C0 curl
       │                                  ├─ Lightpanda
       │                                  ├─ Chrome/Playwright
       │                                  └─ Camoufox wrapper
       │
       └──────── profiles / sessions
                        │
                        ▼
                 evidence artifacts
```

## 4. Invocation paths

### 4.1 Local CLI

`browserctl` is the operator/developer interface for init, submit/run, status/wait/result/cancel, worker, doctor, backup, and capabilities.

### 4.2 Local MCP

`mac-browser-mcp` is stdio-only. The MCP process is an adapter over the existing JobStore/worker and does not become a second Browser worker.

The current local MCP surface contains ten tools: capabilities, doctor, artifact OCR, fetch, render, inspect, browser use, status, result, cancel. `artifact_ocr` is local-only in P0 and is not authorized through the SignalForge Provider contract.

### 4.3 SignalForge Provider Agent

The remote production path is `pull_ssh_v1`:

```text
Mac Provider Agent
  -> outbound SSH using dedicated restricted identity
  -> claim bounded SignalForge work from Bangkok
  -> validate reviewed Provider Invocation Contract
  -> call local mac-browser-mcp over stdio
  -> package/report bounded evidence/result
```

No Browser, MCP, CDP, or Provider API listener is opened on the Mac. Remote authorization is source/capability/URL specific and the Provider contract may intentionally expose a narrower C3 subset than the local MCP.

## 5. Capability layers

### C0 Fetch

- system `/usr/bin/curl`;
- normal TLS validation;
- HTTP/HTTPS only for production web fetch;
- raw response persisted privately with SHA-256;
- bounded text excerpt only for textual content.

### C1 Render

- DOM/JS rendering;
- ephemeral AUTO path prefers Lightpanda;
- safe Lightpanda compatibility/quality failure may fall back to Chrome;
- persistent-profile rendering uses Chrome.

### C2 Read-only Inspect

- dedicated Chrome diagnostic session;
- explicit CDP allowlist;
- console/request/response/navigation/performance/accessibility diagnostics;
- screenshot evidence;
- no `Runtime.evaluate` or mutating CDP surface.

### C3 Browser Use

- deterministic multi-step actions;
- CSS and semantic targets;
- bounded body-text/ARIA snapshots;
- screenshots/downloads remain runtime evidence;
- no embedded planner;
- failure/cancellation can mark `partial_effect_possible` when prior interactions may have had effects.

### Artifact OCR (orthogonal to C0-C3)

- local synchronous processing of an already-acquired runtime evidence artifact;
- P0 accepts PNG/JPEG only and never performs network I/O;
- Tesseract runs fixed `mya+eng` recognition, preferring runtime-local `tessdata_best` weights;
- the input path must resolve inside the Browser Plane evidence directory;
- output includes input SHA-256, reconstructed lines, bounding boxes and confidence;
- OCR output is evidence enrichment only: critical identifiers, dates, quantities and business actions require source-specific cross-checking before canonical use;
- P0 is not exposed through the SignalForge Provider Invocation Contract and is deliberately not named C4.

### Network Trace P1 (internal operator diagnostic)

- optional `mitmdump` subprocess, default OFF;
- explicit host scope and loopback listener only;
- registered in the existing Browser Process Registry for ownership-safe shutdown;
- retains bounded response metadata only; no request/response bodies or query strings;
- no system proxy mutation and no global CA installation;
- not a browser engine, not C4, and not exposed through MCP or the SignalForge Provider contract;
- current P1 proves bounded trace capture with a debug client; automatic Chrome proxy injection remains gated on a real source need.

See `docs/NETWORK_TRACE_P1.md` for the operator contract and limitations.

## 6. Engine routing

`BrowserEngine` is an internal execution choice, not a public MCP-level engine API.

```text
C0                         -> curl
C1 ephemeral AUTO          -> Lightpanda -> Chrome safe fallback
C1 persistent              -> Chrome
C2                          -> Chrome
C3 AUTO                     -> Chrome
C1/C3 fingerprint-sensitive -> Camoufox when explicit/source-evidence selected
```

Camoufox is fail-closed across engines: no automatic Chrome <-> Camoufox replay. This prevents duplicated browser side effects.

## 7. State and concurrency

SQLite is the runtime state authority.

Key invariants:

- WAL mode;
- `synchronous=FULL`;
- `busy_timeout=5000`;
- state/version compare-and-swap transitions;
- idempotent submit;
- one active Runtime Worker enforced by `worker.lock`;
- one exclusive Profile Lease per persistent profile;
- one Control Lease for browser-session mutation/diagnostic ownership.

The runtime does not infer permission to steal a profile from lease expiry alone.

## 8. Browser process ownership

Every owned browser/wrapper process is recorded in the Browser Process Registry. Termination requires proof using the registry, PID, and macOS process-start identity; runtime-owned user-data information is also used when applicable.

Ambiguous ownership fails closed. Broad `pkill Chrome` / `killall` is outside the operating model.

## 9. Recovery

When a worker starts after an unclean interruption it:

1. finds interrupted active jobs;
2. reconciles registered owned processes;
3. terminates only proven-owned processes;
4. records closed/gone processes;
5. transitions interrupted jobs to `RECOVERY_REQUIRED`;
6. releases leases only after safe reconciliation;
7. leaves ambiguous cases for operator review.

This deliberately prioritizes state correctness over automatic replay.

## 10. Runtime and evidence storage

Default runtime root:

```text
~/agent-browser-runtime/
```

Development checkout and production runtime are separate. Production launchd runs from `~/agent-browser-runtime/app/`, not from TCC-protected `~/Documents`.

Sensitive runtime/evidence files use `0600`; runtime/profile/evidence directories use `0700`.

## 11. Host boundary

Browser egress is the Mac mini's direct Internet connection. SEA/VPS and China browser egress are deliberately not part of the current architecture.

The user LaunchAgent requires a logged-in user session. After a cold power cycle/FileVault boot, manual login may be required before Browser Plane returns to READY.

## 12. Cross-project boundary

- `vps-worker-plane`: direct HTTP/API/ETL worker runtime;
- `signalforge`: source/trigger/evidence/canonical/signal/review application logic;
- `mac-browser-plane`: Browser execution runtime.

SignalForge may invoke explicitly authorized Browser capability through the Provider path, but Browser Plane does not absorb SignalForge business/source logic.