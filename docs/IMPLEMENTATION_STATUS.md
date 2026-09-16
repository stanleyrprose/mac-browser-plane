# Implementation Status — Evidence Ledger

> **Current-status pointer (2026-09-09):** this file is the detailed implementation/evidence ledger accumulated across R1 and later slices. For the current effective production boundary, read `docs/PROJECT_STATUS.md` and `src/browser_plane/capabilities.json` first. Earlier stage statements such as “C3 deferred” or “remote invocation disabled” remain historical facts for that stage and are superseded by later completed slices recorded below.

**Baseline:** Mac-Centric Browser Execution Plane R1 v1.4.1 FROZEN  
**Branch:** `main`  
**R1 baseline status:** **AUTHORIZED R1 OPERATIONAL SCOPE COMPLETE**  
**Current post-R1 production status:** **C0–C3 + semantic targeting + Lightpanda + selective Camoufox + explicit nodriver C1 + local Artifact OCR P0 + PIC v1 Provider production COMPLETE**  
**R1 closure:** `docs/R1-OPERATIONAL-BASELINE-CLOSURE-2026-09-04.md`

## Current verification snapshot — 2026-09-16

- [x] full source regression suite: **87/87 PASS**
- [x] `browserctl doctor = READY`
- [x] SQLite integrity `ok`, WAL enabled, synchronous FULL, busy timeout 5000
- [x] Chrome available
- [x] Lightpanda optional engine installed/ready
- [x] Camoufox optional engine package/browser asset installed/ready
- [x] nodriver `0.50.3` optional engine package installed/ready; explicit ephemeral C1 smoke HTTP 200
- [x] Artifact OCR ready: Tesseract `5.5.3`, runtime-local `tessdata_best`, fixed `mya+eng`
- [x] real MTE evidence MCP smoke: 20 OCR lines, mean confidence `79.22`, expected SHA-256, date/time/tonnage recovered
- [x] stale Profile Leases: `[]`
- [x] Browser Process Registry ownership residue: `[]`

## Implemented R1 foundation

- [x] Independent `mac-browser-plane` repository
- [x] Local runtime directory model
- [x] SQLite runtime DB with WAL / synchronous FULL / busy_timeout=5000
- [x] Job state/version CAS and idempotent submit
- [x] Queue / run / cancel lifecycle
- [x] Single active Runtime Worker via local file lock
- [x] Startup recovery to `RECOVERY_REQUIRED`
- [x] Profile Lease exclusivity and browser-session Control Lease
- [x] Browser Process Registry with PID + macOS start-token ownership verification
- [x] Graceful terminate -> force-kill last-resort ladder for proven-owned processes
- [x] C0 Direct Fetch via macOS system curl with raw private evidence artifact + SHA-256
- [x] Runtime-owned local Google Chrome
- [x] Dynamic loopback CDP port and explicit viewport
- [x] Evidence `result.json`
- [x] `browserctl` lifecycle/doctor/backup/capabilities commands
- [x] Non-editable release runtime under `~/agent-browser-runtime/app/`
- [x] User LaunchAgent installed and verified
- [x] Online SQLite-consistent backup and restore smoke
- [x] Sensitive files `0600`, runtime/profile/evidence directories `0700`
- [x] C2 dedicated read-only Chrome diagnostic session and CDP allowlist

## Local Agent MCP Adapter

- [x] stdio-only `mac-browser-mcp` adapter over the existing JobStore/worker
- [x] no second Browser worker and no network listener
- [x] bounded web URL guard
- [x] no arbitrary JavaScript or raw CDP
- [x] original v0 eight-tool local contract live-verified on 2026-09-05
- [x] later C3 slice extended the same adapter to nine tools; Artifact OCR P0 extends the local surface to **ten tools** without changing C0-C3 semantics

Historical contract/closure:

- `docs/LOCAL_AGENT_MCP_ADAPTER_V0.md`
- `docs/LOCAL_AGENT_MCP_ADAPTER_V0-LIVE-CLOSURE-2026-09-05.md`

## C3 Browser Use / M3B

- [x] deterministic `TaskType.USE`, distinct from deferred autonomous `TaskType.AGENT`
- [x] actions: navigate, click, type, select, press, wait, snapshot, screenshot, download
- [x] `force: true` supported only on the defined click/select escape hatches
- [x] screenshot/download artifacts stay in private runtime evidence
- [x] timeout/failure/cancel preserves `partial_effect_possible` when effects may have occurred
- [x] production stdio MCP exposes ten local tools after Artifact OCR P0; the remote Provider allowlist remains unchanged
- [x] real-business acceptance performed on Myanmar/MPT/MPA/Trade Portal paths during implementation

## C3 Semantic Targeting / M3C

- [x] exactly one target form: CSS selector, ARIA role(+name), label, or visible text
- [x] optional exact matching and fail-closed ambiguous target validation
- [x] bounded body text + bounded Playwright AI-mode ARIA snapshot
- [x] capability manifest advertises semantic targeting and ARIA snapshot
- [x] embedded Browser Agent remains disabled

## Lightpanda C1 fast path

- [x] internal engine values include auto/chrome/lightpanda/camoufox/nodriver
- [x] ephemeral C1 AUTO prefers Lightpanda when runnable
- [x] Lightpanda runs as runtime-owned subprocess with registry/lease/cancellation participation
- [x] safe C1 compatibility/quality failure can fall back to Chrome with `engine_route` evidence
- [x] persistent C1, C2, and ordinary C3 remain Chrome
- [x] no Lightpanda daemon/MCP/native Agent exposed
- [x] live production C1 smoke and residue checks passed

Contract/closure:

- `docs/LIGHTPANDA_ENGINE_ROUTING.md`
- `docs/LIGHTPANDA-C1-PRODUCTION-CLOSURE-2026-09-08.md`

## Camoufox selective engine

- [x] upstream `camoufox==0.5.6` integrated directly
- [x] short-lived Browser Plane-owned subprocess; no `jo-inc/camofox-browser` server/runtime/MCP
- [x] selective ephemeral C1 and C3 only
- [x] C2 and persistent profiles remain unsupported on Camoufox
- [x] AUTO never promotes to Camoufox
- [x] no automatic Camoufox <-> Chrome replay fallback
- [x] production C1/C3 smokes and post-run residue checks passed

Contract:

- `docs/CAMOUFOX_ENGINE_ROUTING.md`

## nodriver selective C1 engine

- [x] upstream `nodriver==0.50.3` integrated directly
- [x] short-lived Browser Plane-owned subprocess using system Chrome; no nodriver daemon/MCP/REST surface
- [x] explicit ephemeral C1 only in v1
- [x] C2, C3 and persistent profiles remain unsupported on nodriver
- [x] AUTO never promotes to nodriver
- [x] no automatic nodriver <-> Chrome replay fallback
- [x] local C1 smoke, doctor readiness and post-run residue checks passed

Contract:

- `docs/NODRIVER_ENGINE_ROUTING.md`

## Artifact OCR P0

- [x] orthogonal `artifact_ocr` local MCP capability; not C4
- [x] runtime-evidence-only path confinement with symlink-safe resolution
- [x] PNG/JPEG only, 25 MB bound, file-signature validation
- [x] networkless Tesseract `mya+eng`; runtime-local `tessdata_best` preferred
- [x] output carries input SHA-256, text, line boxes and confidence
- [x] evidence-enrichment-only semantics; critical identifiers/dates/quantities require source cross-check
- [x] PDF rasterization, automatic source routing and SignalForge remote Provider authorization remain outside P0

## PIC v1 R4 — SignalForge Provider Production

- [x] `production_enabled=true`
- [x] `invocation_mode=pull_ssh_v1`
- [x] `remote_invocation=true`
- [x] Mac Provider Agent initiates restricted outbound SSH polling to Bangkok
- [x] Provider invokes Browser capability only through local MCP stdio
- [x] dedicated provider LaunchAgent and restricted identity
- [x] reviewed Provider Invocation Contract remains source/capability/URL authority
- [x] no inbound Browser/MCP/CDP listener
- [x] backlog drain: completed work can claim next work immediately; NO_WORK uses idle delay
- [x] Mac-offline isolation and unattended recovery live-verified

Closure:

- `docs/PIC-R4-PRODUCTION-CLOSURE-2026-09-08.md`

## Durable production boundaries

- Browser network egress: Mac direct only
- Personal Chrome profile: forbidden
- production app separated from TCC-protected development checkout
- one Browser worker/state authority
- local MCP: stdio only
- Provider: pull-only restricted SSH + local MCP stdio
- C2: read-only Chrome diagnostics
- C3 planning: external caller
- automatic cross-engine replay: only the documented side-effect-safe Lightpanda -> Chrome ephemeral-C1 fallback

## Explicitly deferred

- SEA/VPS Browser egress
- China Browser egress
- separate Chrome DevTools MCP daemon/server
- autonomous embedded Browser Agent / LLM planner
- headed/human takeover

## Cross-project invariant

`vps-worker-plane` Direct HTTP/API/ETL remains a separate/default acquisition path. SignalForge has an explicitly authorized Provider path for contract-allowed sources/capabilities. This does not reintroduce VPS Browser/Crawlee R3.

## Historical evidence policy

The dated R1/MCP/PIC/engine closure files are immutable acceptance evidence unless a factual erratum is required. They intentionally preserve the boundary that existed on their date. Current effective behavior is maintained in `capabilities.json`, `PROJECT_STATUS.md`, current architecture/runbook/security docs, and engine routing contracts.