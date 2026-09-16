# Changelog

This changelog summarizes material product/runtime milestones. Detailed acceptance evidence remains in dated closure documents under `docs/`.

## Unreleased

### Added

- Added pinned `nodriver==0.50.3` as an explicit-only, ephemeral C1 direct-CDP Chromium engine.
- Reused the existing Browser Process Registry, Control Lease, cancellation/timeout cleanup, and evidence paths; no new daemon, listener, MCP surface, or state authority was introduced.
- Added `nodriver_optional` doctor visibility and a live C1 smoke fixture.

### Safety / architecture

- Kept nodriver out of AUTO routing with no automatic cross-engine replay.
- Kept persistent profiles, C2 diagnostics, and C3 Browser Use unsupported on nodriver v1 pending real-source A/B evidence and full C3 contract parity.

### Documentation

- Established a software-project documentation baseline with canonical architecture, development, testing, deployment, security, operations, project-status, and decision-index documents.
- Separated current operational truth from historical stage/closure evidence.
- Updated the project entry documentation to reflect C0–C3, semantic targeting, Lightpanda, Camoufox, and production SignalForge Provider invocation.

## 2026-09-08

### Added

- Production SignalForge Provider Agent path using Mac-initiated restricted SSH pull and local MCP stdio invocation (`pull_ssh_v1`).
- Lightpanda as the internal ephemeral-C1 fast path with side-effect-safe Chrome fallback.
- Upstream Camoufox as a selective optional anti-detection engine for ephemeral C1/C3 work.
- Portable AI capability-discovery documentation/contracts.

### Safety / architecture

- Preserved the existing nine-tool Browser Plane MCP surface while adding engines internally.
- Kept C2 Chrome-only and ordinary AUTO C3 on Chrome.
- Kept Camoufox out of AUTO routing and disabled automatic cross-engine replay.
- Kept the Mac free of inbound Browser/MCP/CDP Provider listeners.

## 2026-09-05

### Added

- Local Agent MCP Adapter v0 over the existing JobStore/LaunchAgent runtime.
- Local Codex/Hermes-class stdio MCP integration and live verification.

The original v0 closure recorded the narrower interface available at that stage; later C3 work extended the same adapter rather than creating a second runtime.

## 2026-09-04

### Completed

- R1 operational baseline: SQLite state, worker locking, leases, Browser Process Registry, startup recovery, C0 fetch, C1 Chrome rendering, C2 read-only diagnostics, evidence, backup, launchd deployment, and soak verification.
- Production/development split with runtime installed under `~/agent-browser-runtime/app/`.
- Direct Mac Internet egress chosen as the R1 network boundary.

## Historical note

Dated closure documents are the evidence record for their point-in-time states. Current capability truth is `src/browser_plane/capabilities.json` plus the current-state documentation.