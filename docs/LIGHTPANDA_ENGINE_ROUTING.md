# Lightpanda Engine Routing v1

Status: implementation contract for Mac Browser Plane.

## Goal

Add Lightpanda as an internal Browser Plane execution engine without changing the existing nine-tool MCP surface, JobStore, worker, lease, process-registry, evidence, cancellation, or remote-provider boundaries.

Lightpanda is an engine implementation detail. Callers continue to use `browser_fetch`, `browser_render`, `browser_inspect`, and `browser_use`; callers do not select Lightpanda directly through MCP.

## v1 routing policy

| Capability / condition | Engine | Fallback |
| --- | --- | --- |
| C0 `browser_fetch` | macOS system `curl` | existing C0 behavior |
| C1 `browser_render`, ephemeral profile | Lightpanda when installed | Chrome on Lightpanda execution/compatibility/quality failure |
| C1 persistent profile | Chrome | none |
| C2 `browser_inspect` | Chrome | none |
| C3 `browser_use` | Chrome | none |

The policy is capability-based, not source-domain based. New sources do not require a Lightpanda allowlist.

## Why v1 is C1-only

Lightpanda native `fetch --json --dump html` is a reliable, low-overhead path for JavaScript-executed DOM acquisition on this Mac. During the 2026-09-08 integration, the installed Lightpanda nightly loaded `https://example.com` successfully through native `fetch`, while the same binary driven through the current Python Playwright `connect_over_cdp` path timed out during `page.goto`, including `commit` and `domcontentloaded` waits.

C2 also requires real Chrome diagnostics and screenshot evidence. C3 may create side effects; retrying an uncertain Lightpanda interaction in Chrome could duplicate a click, form submission, or other mutation. Therefore C2 and all C3 remain Chrome in v1.

## Lightpanda trigger

AUTO selects Lightpanda only when all of the following are true:

1. `task_type == automate` (C1);
2. `profile_mode == ephemeral`;
3. a runnable Lightpanda binary is present (`BROWSER_PLANE_LIGHTPANDA`, `PATH`, `/opt/homebrew/bin/lightpanda`, or `/usr/local/bin/lightpanda`).

Otherwise AUTO selects Chrome before execution.

## Lightpanda execution contract

Lightpanda runs as one runtime-owned native `fetch` subprocess per eligible C1 job. It is not a daemon and no Lightpanda network, MCP, or Agent surface is exposed.

The process:

- is registered in Browser Process Registry as `C1_LIGHTPANDA`;
- holds a Browser Plane Control Lease (`LIGHTPANDA_FETCH`);
- participates in Browser Plane cancellation and ownership cleanup;
- runs with `LIGHTPANDA_DISABLE_TELEMETRY=true`;
- runs with `LIGHTPANDA_DISABLE_CORE_DUMP=1`;
- returns bounded rendered DOM-derived text plus URL/title/status/content type;
- leaves JobStore/evidence semantics owned by Browser Plane.

## Safe Chrome fallback

AUTO Lightpanda C1 may fall back to Chrome because C1 performs only navigation/rendering and no user interaction is replayed.

Fallback is triggered by execution or compatibility failure, invalid/empty Lightpanda output, HTTP 401/403/429, or HTTP 5xx. The final result records `engine_route`, including requested policy, attempted engines, selected engine, route reason, and bounded fallback error.

Explicit internal `engine=lightpanda` is fail-closed: it does not silently fall back to Chrome. The public MCP surface does not currently expose an engine selector.

## Non-goals

v1 does not add:

- Lightpanda MCP;
- Lightpanda native Agent;
- a second Browser worker;
- a persistent Lightpanda daemon;
- Lightpanda persistent profiles;
- Lightpanda C2;
- Lightpanda C3;
- domain-specific routing rules.

## Future promotion gate

Lightpanda may expand beyond C1 only after a separate change proves all affected semantics on real production sources. At minimum:

- Playwright/CDP navigation is stable with the pinned Lightpanda build;
- semantic targeting and required C3 actions have parity tests;
- no automatic fallback can replay an action with uncertain side effects;
- screenshot/download/diagnostic evidence requirements remain truthful;
- source success/evidence parity meets the agreed production acceptance threshold;
- Chrome fallback and rollback remain intact.

Until that gate is explicitly passed, `capabilities.json` is authoritative: C2 and C3 are Chrome-only.
