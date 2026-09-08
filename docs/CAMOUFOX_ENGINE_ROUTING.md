# Camoufox Engine Routing v1

Status: implemented optional anti-detection engine slice for Mac Browser Plane.

## Decision

Mac Browser Plane adopts **upstream Camoufox capability**, not the `jo-inc/camofox-browser` server/runtime/MCP architecture.

Production architecture remains:

```text
mac-browser-plane
├─ C0 -> curl
├─ C1 lightweight ephemeral render -> Lightpanda -> safe Chrome fallback
├─ ordinary/persistent/diagnostic browser work -> Chrome
└─ fingerprint-sensitive C1/C3 -> Camoufox (selective only)
```

Camoufox is an internal engine implementation detail. It does not create a new C4 capability and it does not create a second Browser Plane.

## What is inherited

- upstream `camoufox` Python interface;
- upstream Camoufox Firefox build;
- Playwright-compatible page interaction;
- browser-level fingerprint/automation-hiding behavior;
- Firefox-engine diversity for sources where ordinary Chrome/Lightpanda has demonstrated fingerprint-sensitive failure.

## What is deliberately not inherited from jo-inc/camofox-browser

- no REST server on `localhost:9377` or any other port;
- no Camofox MCP server;
- no separate session/tab/state database;
- no OpenClaw plugin surface;
- no arbitrary JavaScript `evaluate` surface;
- no proxy/GeoIP routing layer;
- no VNC/human-takeover subsystem;
- no search/YouTube/plugin macros;
- no Camofox telemetry/reporting service;
- no second worker or daemon.

The external protocol remains the existing `mac-browser-plane` stdio MCP and CLI/JobStore model.

## Runtime adapter

Browser Plane launches a short-lived runtime-owned Python subprocess:

```text
BrowserExecutor
  -> python -m browser_plane.camoufox_runner
      -> upstream camoufox.sync_api.Camoufox
          -> Camoufox Firefox
```

The wrapper process is registered in the existing Browser Process Registry as `C1_CAMOUFOX` or `C3_CAMOUFOX`, holds the existing Control Lease, participates in cancellation, and writes results/evidence through the existing Browser Plane paths. It is not a persistent daemon.

## v1 eligibility

Camoufox v1 is intentionally narrow:

| Capability / condition | Camoufox v1 |
| --- | --- |
| C0 fetch | No; use curl |
| C1 ephemeral render | Yes, selective |
| C1 persistent profile | No |
| C2 read-only inspect | No; Chrome diagnostics remain authoritative |
| C3 ephemeral Browser Use | Yes, selective |
| C3 persistent profile | No |
| autonomous Browser Agent | No |

## Routing policy

`AUTO` does **not** choose Camoufox in v1.

Camoufox is selected only when an internal `JobSpec` explicitly carries `engine=camoufox`. This is the routing hook for two controlled cases:

1. debugging/research validation;
2. a source registry or higher-level provider that has evidence that the source is fingerprint-sensitive and deliberately materializes `engine=camoufox`.

Mac Browser Plane itself does not maintain a domain allowlist and does not infer anti-bot state from a generic HTTP status.

Do not implement rules such as `403 -> Camoufox`: 403 can mean authentication, authorization, region policy, rate limit, account state, or WAF policy rather than browser fingerprinting.

## Fallback semantics

Camoufox is **fail-closed** in v1. There is no automatic Camoufox -> Chrome or Chrome -> Camoufox replay.

This is especially important for C3:

```text
read-only/idempotent work -> fallback may be designed when evidence proves it safe
mutating work + partial_effect_possible -> never automatically replay on another engine
```

The existing Lightpanda -> Chrome fallback remains limited to side-effect-safe ephemeral C1 rendering.

## Dependency and installation

Project dependency:

```text
camoufox==0.5.6
playwright>=1.55,<1.63
```

The Camoufox browser asset is installed separately into the user's Camoufox cache:

```bash
python -m camoufox fetch
```

The first Mac integration on 2026-09-08 installed upstream Camoufox `v152.0.4-beta.30` for macOS arm64.

## Live verification — 2026-09-08

Using an isolated Browser Plane runtime home:

- C1 explicit Camoufox against `https://example.com`: `SUCCEEDED`, HTTP 200, `engine_route.selected=camoufox`, no fallback;
- C3 explicit Camoufox: snapshot -> semantic `role=link,name=Learn more` click -> wait -> snapshot -> screenshot; reached `https://www.iana.org/help/example-domains`, HTTP 200.

Using the installed production runtime and LaunchAgent worker:

- queued C1 explicit Camoufox: `SUCCEEDED`, HTTP 200, `engine_route.selected=camoufox`, no fallback;
- queued C3 explicit Camoufox: snapshot -> semantic click -> wait -> snapshot -> screenshot; reached `https://www.iana.org/help/example-domains`, `SUCCEEDED`, HTTP 200, no fallback;
- post-run `browser_doctor = READY`;
- Browser Process Registry ownership residue: none;
- stale Profile Leases: none;
- production stdio MCP still exposes exactly the original nine Browser Plane tools and no Camoufox/Camofox MCP or REST surface.

## Promotion gate

Camoufox should remain selective/optional until real business sources prove incremental value over Chrome. Promotion to source-level production routing requires a small A/B set showing:

- a reproducible Chrome/Lightpanda fingerprint-sensitive failure;
- Camoufox succeeds materially more often;
- repeated launch/close leaves no process/lease residue;
- screenshot/download/evidence semantics remain truthful;
- cancellation cleanup is reliable;
- no unsafe action replay;
- upstream Camoufox/Playwright version compatibility is pinned and retested.

If real-source A/B shows no meaningful gain, keep Camoufox installed but unused by AUTO routing.
