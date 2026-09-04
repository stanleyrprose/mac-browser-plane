# R1 Operational Baseline Closure — 2026-09-04

## Status

```text
Mac Browser Plane R1
Authorized Operational Scope = COMPLETE
```

This does **not** mean every future-capability section from the frozen architecture document has been implemented.

It means the current authorized R1 scope has been implemented, live-verified, and bounded by explicit defer decisions. Deferred items are not unfinished production work unless real implementation evidence or a concrete business requirement reopens them.

## Implemented operational baseline

### Local execution

- independent `mac-browser-plane` repository;
- local `browserctl` CLI;
- SQLite runtime state with WAL / `synchronous=FULL` / busy timeout;
- Job lifecycle, CAS state transitions, idempotency and cancellation;
- single active Runtime Worker enforced by `worker.lock`;
- user LaunchAgent running an installed release under `~/agent-browser-runtime/app/`;
- startup reconciliation and `RECOVERY_REQUIRED` handling;
- Profile Lease / browser-session Control Lease;
- Browser Process Registry with PID + macOS start-token ownership verification.

### Acquisition capabilities

```text
C0 = macOS system curl, strict TLS, full raw response artifact + SHA-256
C1 = deterministic Playwright attached to runtime-owned local Google Chrome
C2 = dedicated read-only diagnostic Browser session
```

C2 uses the existing Playwright CDP connection and an explicit read-only allowlist rather than a separate Chrome DevTools MCP daemon.

### Evidence and security

- raw C0 HTTP/HTTPS response artifacts preserved;
- binary evidence such as PDF is stored without lossy text decoding;
- textual responses also expose only a bounded `text_excerpt`;
- runtime/state/evidence/backup sensitive files are `0600`;
- runtime/profile/evidence directories are `0700`;
- CDP stays loopback-only with dynamic port allocation;
- no personal Chrome profile reuse;
- no TLS bypass;
- no public Browser API.

### Reliability

- 1000-job soak: 1000/1000 succeeded;
- SQLite integrity: `ok`;
- no residual Profile Lease / Control Lease / running Browser process after soak;
- consistent online SQLite backup + restore smoke;
- repeated persistent-profile execution verified;
- display-sleep headless C1 execution verified;
- `browserctl doctor = READY` in the installed runtime.

## Real-source acceptance evidence

Five Myanmar public business/regulatory source families were validated from the Mac direct network path:

- MPT Tender;
- Myanma Port Authority Tenders + real tender PDF;
- Ministry of Commerce Notifications;
- Ministry of Border Affairs Tenders;
- Myanmar National Trade Portal Legal Documents.

Observed lesson:

```text
visible pagination / Load More / filtering
!= automatically Browser-required
```

MOBA pagination and Trade Portal filtering both reduce to deterministic C0 URLs/query parameters.

No real source tested so far proves a production need for C3 Browser Agent.

Source evidence is recorded in `docs/SOURCE_CAPABILITY_MATRIX.md`.

## Cross-project integration closure

The following architecture remains frozen:

```text
SignalForge
= business/source/canonical truth

VPS Worker Runtime
= generic Linux Direct HTTP/API/ETL/batch execution

Mac Browser Plane
= local Browser execution capability
```

VPS Browser/Crawlee R3 is superseded by the Mac Browser Plane and must not be implemented.

The SignalForge re-audit also proved an important environment split:

```text
MPA / MOBA
Mac direct C0      = GREEN
Bangkok strict TLS = RED
```

That is a provider/environment-specific TLS difference, not a Browser requirement.

Therefore current production behavior remains:

- MPT / Commerce continue Bangkok Direct HTTP where already active;
- MPA remains deferred from SignalForge production;
- MOBA is a deferred candidate;
- no TLS bypass;
- no VPS Browser fallback;
- no SignalForge→Mac unattended remote invocation.

## Host readiness boundary

Observed Mac host state:

```text
system sleep on AC = disabled
autorestart after power failure = enabled
LaunchAgent = running
WindowServer/user session = healthy
```

Current accepted cold-power-cycle behavior:

```text
power returns
→ Mac auto-restarts
→ manual macOS login once
→ user LaunchAgent starts
→ Browser Plane returns READY
```

R1 intentionally does not add automatic login, Browser LaunchDaemon execution before login, or GUI/session bootstrap hacks.

## Explicitly deferred — not current backlog

The following items are intentionally **not** part of the current authorized implementation scope:

- SEA/VPS Browser egress;
- China Browser egress;
- separate Chrome DevTools MCP adapter/server;
- C3 Browser Use / autonomous Browser Agent;
- headed/human takeover;
- storageState cloning workflow;
- automated `PROFILE_CORRUPT` repair;
- Resource Governor beyond current doctor/host checks;
- automatic Evidence TTL/quota deletion service;
- SignalForge→Mac unattended Provider Invocation Contract;
- automatic-login / pre-login unattended cold-boot Browser recovery.

These are not implementation defects.

## Reopen rule

R1 should be reopened only when there is concrete evidence such as:

1. a real production source whose required business content cannot be obtained by C0 and cannot be maintained deterministically by C1;
2. a real workflow requiring Browser Agent reasoning beyond deterministic Playwright;
3. a real SignalForge production source whose business value justifies a reviewed cross-host Mac Provider Contract;
4. measured resource pressure that current worker/doctor behavior cannot safely handle;
5. repeated evidence growth creating a real disk-management problem;
6. an unacceptable outage caused by the manual-login cold-boot boundary;
7. a correctness/recovery/security failure in the current runtime model.

Hypothetical edge cases, additional paper architecture reviews, or the existence of unused future PRD sections are not sufficient reasons to reopen R1.

## Default next action

```text
Do not build more Browser infrastructure by default.

Operate R1
→ onboard/validate real business sources
→ classify failures
→ add only the smallest capability proven necessary by evidence
```

## Final closure statement

> Mac Browser Plane R1 is now an operationally verified local Browser Computer with C0/C1/C2, safe lifecycle ownership, recovery, evidence preservation, backup, and a documented host boundary. The current authorized scope is complete. Future capabilities remain evidence-triggered rather than backlog-driven.
