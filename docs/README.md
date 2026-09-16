# Documentation Index

This directory separates **current operational truth** from **historical acceptance evidence**.

## Source-of-truth order

For current behavior, use this order:

1. `src/browser_plane/capabilities.json` — machine-readable capability/routing truth;
2. root `README.md` — current product entry point and boundaries;
3. `docs/PROJECT_STATUS.md` — current completion/deferred status;
4. `docs/ARCHITECTURE.md` — current architecture;
5. `docs/INTERFACE_REFERENCE.md` / `docs/CONFIGURATION.md` — current caller and configuration reference;
6. `docs/RUNBOOK.md` / `docs/DEPLOYMENT.md` / `docs/SECURITY.md` — current operations;
7. engine-specific current contracts (`LIGHTPANDA_ENGINE_ROUTING.md`, `CAMOUFOX_ENGINE_ROUTING.md`);
8. dated closure documents — evidence for the state that was accepted on that date.

`AGENTS.md` is a capability-discovery hint for agents; it does not override the machine-readable contract.

## Current operational documents

| Document | Purpose |
| --- | --- |
| `../README.md` | project overview, quick start, current boundary |
| `PROJECT_STATUS.md` | current implemented/deferred status and verification snapshot |
| `ARCHITECTURE.md` | runtime components, execution paths, state/lease model |
| `INTERFACE_REFERENCE.md` | current 9-tool MCP, C3 action schemas, CLI and JobSpec reference |
| `CONFIGURATION.md` | environment variables, runtime paths, profiles, launchd/config boundary |
| `RUNBOOK.md` | health, recovery, backup, troubleshooting, incident actions |
| `DEPLOYMENT.md` | development install, production install, Provider Agent, rollback |
| `DEVELOPMENT.md` | repository layout and engineering workflow |
| `TESTING.md` | local tests, CI, soak criteria, regression policy |
| `SECURITY.md` | threat model, security invariants, secret/profile boundaries |
| `DECISIONS.md` | decision index and rationale pointers |
| `AI_CAPABILITY_ANNOUNCEMENT.md` | portable capability announcement for AI callers |
| `SOURCE_CAPABILITY_MATRIX.md` | source/capability observations |
| `C3_BROWSER_FAILURE_CORPUS.md` | local/private C3 failure evidence and replay-gate workflow |
| `HOST_READINESS.md` | Mac host/power/login readiness boundary |

## Interface and engine contracts

Current general interface reference is `INTERFACE_REFERENCE.md`.

Historical/narrow focused contracts:

- `LOCAL_AGENT_MCP_ADAPTER_V0.md`
- `LIGHTPANDA_ENGINE_ROUTING.md`
- `CAMOUFOX_ENGINE_ROUTING.md`
- `CODEXPRO_CLOUD_CHAT_BRIDGE.md`
- `PIC-V1-R2-PROVIDER-AGENT.md`
- `PIC-V1-R2-MAC-PROVIDER-AGENT-2026-09-08.md`

These documents explain narrower contracts. Where an older document describes a deliberately limited earlier stage (for example the original 8-tool local adapter), later current-state documents and `capabilities.json` describe the effective present surface.

## Historical acceptance / closure evidence

Examples:

- `R1-OPERATIONAL-BASELINE-CLOSURE-2026-09-04.md`
- `LOCAL_AGENT_MCP_ADAPTER_V0-LIVE-CLOSURE-2026-09-05.md`
- `PIC-R4-PRODUCTION-CLOSURE-2026-09-08.md`
- `LIGHTPANDA-C1-PRODUCTION-CLOSURE-2026-09-08.md`
- `ARTIFACT-OCR-P0-PRODUCTION-CLOSURE-2026-09-11.md`

Dated closure files should remain immutable except for factual errata. They document what was accepted at that time; they are not a place to continuously rewrite current state.

## Documentation maintenance rule

When behavior changes:

1. change code/tests and `capabilities.json` together when the public capability contract changes;
2. update current-state docs in the same PR;
3. add a dated closure/evidence document only for a meaningful production acceptance milestone;
4. do not rewrite old closure evidence merely to make it look current;
5. record architectural policy changes in `DECISIONS.md` or the relevant focused routing/contract document.

This keeps one canonical home for each kind of truth and prevents historical stage constraints from being mistaken for current production behavior.