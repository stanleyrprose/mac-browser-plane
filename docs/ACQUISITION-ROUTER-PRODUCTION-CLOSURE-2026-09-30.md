# Public Read Acquisition Router Production Closure — 2026-09-30

## Scope

Close production rollout of the local high-level `browser_acquire` capability introduced by PR #60.

The accepted abstraction is:

```text
caller
  -> browser_acquire(public URL)
       -> C0_FETCH
            -> system curl
            -> bounded curl_cffi when C0 transport evidence requires it
       -> conservative content classification
       -> at most one ephemeral C1_RENDER when evidence requires rendering
```

`browser_fetch` remains C0-only. `browser_acquire` never authorizes C2 or C3.

## Reviewed revision and CI

- PR: `#60` — `feat: add public read acquisition router`
- merged revision: `252383bbeda354b49dcf5c47b1af41ce08301019`
- pre-merge push CI: `36694184250` — PASS
- pre-merge pull-request CI: `36694192547` — PASS
- post-merge main CI: `36694360126` — PASS
- post-merge full repository regression: **122/122 PASS**
- C0 mini soak: PASS
- local targeted contract regression before merge: **21/21 PASS**
- current-source real stdio smoke before merge exposed 12 tools and selected C0 for `https://example.com`.

## Authorization boundary

`browser_acquire` is authorized for:

- local MCP;
- CodexPro/cloud-chat bridge.

It is not authorized by the SignalForge Provider Invocation Contract in this rollout.

Router v1 does not authorize:

- C2 Inspect;
- C3 Browser Use;
- proxy or regional egress;
- arbitrary JavaScript;
- interaction such as click/type/download;
- generic retry escalation for auth, rate-limit, network, or certificate failures.

## Routing policy

C1 is considered only when the explicit `browser_acquire` call is present and one of these conservative conditions is observed:

- unresolved supported anti-bot challenge;
- successful HTML acquisition with an empty body;
- low-content shell explicitly requiring JavaScript;
- low-visible-text SPA shell with script/runtime evidence.

These are explicitly non-triggers:

- plain 401/403;
- plain 429;
- generic 5xx;
- DNS failure;
- connection failure;
- timeout;
- TLS certificate verification failure;
- non-HTML response.

A successful `curl_cffi` recovery stays in C0 and does not render again.

## Production deployment

Before replacement:

- production source state corresponded to the prior reviewed `b1ef7ce` main state;
- local MCP surface: 11 tools;
- production Doctor: `READY`;
- SQLite integrity: `ok`;
- pre-deployment SQLite backup:
  `~/agent-browser-runtime/backups/runtime-20260930T091118423625Z.db`;
- backup integrity: `ok`.

Deployment used the existing reviewed path:

```text
scripts/install_runtime.py
scripts/install_launchd.py
browserctl doctor
```

After deployment:

- production code revision: `252383bbeda354b49dcf5c47b1af41ce08301019`;
- production source path: `/Users/xu/Documents/mcpx-projects/mac-browser-plane-acquisition-router-deploy`;
- production local MCP surface: exactly 12 tools;
- `browser_acquire` present in `mac-browser-mcp-call list`;
- `browser_capabilities.discovery.primary_acquisition_tool = browser_acquire`;
- acquisition policy: `public_read_auto_v1`;
- `signalforge_provider_authorized = false`;
- C2/C3 authorization flags: false.

## Production verification

### Real local MCP public-read smoke

Production job: `fcc07bc0-fb61-431e-a205-90059310a70a`

Target: `https://example.com`

Observed:

```text
state=SUCCEEDED
acquisition_outcome=CONTENT_RETURNED
selected_capability=C0_FETCH
http_status=200
transport=system_curl
render_fallback_attempted=false
c2_authorized=false
c3_authorized=false
```

This verifies the normal low-cost path: a caller used only `browser_acquire`, while Browser Plane selected and completed C0 without exposing transport choice to the caller.

### Installed-code controlled C0 -> C1 route

The installed production package was also exercised with controlled internal job results: a C0 HTML SPA shell containing `<div id="root">` plus a script marker triggered `spa_shell_low_text` and selected exactly one ephemeral `C1_RENDER`. The controlled check asserted C0 first, C1 second, `public-research` + ephemeral profile, and C2/C3 authorization remained false.

This is a deterministic routing verification, not a claim that an external live website required C1 during the smoke.

## Final health

- `browserctl doctor`: `READY`;
- SQLite integrity: `ok`;
- `curl_cffi_c0b`: ready;
- stale profile leases: none;
- Browser Process Registry ownership residue: none.

## Rollback

No database schema migration and no SignalForge Provider contract change were introduced.

If rollback is required:

1. reinstall the prior reviewed main state `b1ef7ce361e57c6ab9f3197b18a85b42cda4e3d1` through the standard runtime installer;
2. reinstall/restart the Browser Plane LaunchAgent;
3. run `browserctl doctor`;
4. if runtime state restoration is independently necessary, the pre-deployment SQLite backup above is available.

Normal code rollback does not require database restoration because this change did not alter the schema.

## Closure

Production state: **VERIFIED / CLOSED**.

For local/CodexPro callers, `browser_acquire` is now the preferred interface for “read this public URL reliably.” Lower-level `browser_fetch` and `browser_render` remain available when the caller explicitly needs C0-only or C1-only behavior. SignalForge remains on its narrower reviewed Provider contract until a separate remote-authorization review is performed.
