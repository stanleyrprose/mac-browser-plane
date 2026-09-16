# nodriver Engine Routing v1

Status: implemented optional direct-CDP Chromium engine slice for Mac Browser Plane.

## Decision

Mac Browser Plane adopts upstream `ultrafunkamsterdam/nodriver` as a **selective Chromium C1 engine**, not as a replacement for Chrome/Playwright and not as a second Browser Plane.

Production routing remains:

```text
C0                         -> curl
C1 ephemeral AUTO          -> Lightpanda -> safe Chrome fallback
C1 persistent              -> Chrome
C2                         -> Chrome
C3 AUTO                    -> Chrome
C1/C3 selective            -> Camoufox when explicitly/source-evidence selected
C1 selective Chromium      -> nodriver when explicitly selected
```

## Why nodriver exists in the plane

nodriver communicates directly with Chromium through Chrome DevTools Protocol (CDP) and does not require Selenium or ChromeDriver. Its value is therefore different from Camoufox:

- nodriver: real Chromium + direct CDP + no WebDriver layer;
- Camoufox: Firefox-engine diversity + upstream fingerprint modifications.

This makes nodriver useful for controlled A/B validation when a source appears specifically sensitive to WebDriver-style automation or when a Chromium-compatible path is required.

## v1 eligibility

| Capability / condition | nodriver v1 |
| --- | --- |
| C0 fetch | No |
| C1 ephemeral render | Yes, explicit only |
| C1 persistent profile | No |
| C2 read-only inspect | No |
| C3 Browser Use | No |
| autonomous Browser Agent | No |

v1 deliberately does not duplicate the existing C3 semantic-targeting contract. C3 promotion requires complete parity for targeting, snapshot, screenshot, download, cancellation and evidence semantics before it is allowed.

## Routing policy

`AUTO` never chooses nodriver in v1.

Selection requires `JobSpec.engine=nodriver`. Browser Plane does not infer nodriver eligibility from a generic HTTP status and must not implement rules such as `403 -> nodriver` because 403 can represent authentication, authorization, rate limiting, region policy, account state or WAF policy rather than automation fingerprinting.

## Fallback semantics

nodriver is **fail-closed** in v1:

- no Chrome -> nodriver replay;
- no nodriver -> Chrome replay;
- no automatic retry on another engine.

The only automatic engine replay retained by Browser Plane is the existing side-effect-safe ephemeral C1 Lightpanda -> Chrome fallback.

## Runtime adapter

```text
BrowserExecutor
  -> python -m browser_plane.nodriver_runner
      -> nodriver 0.50.3
          -> system Google Chrome
```

The wrapper is a short-lived runtime-owned subprocess. It is registered in the existing Browser Process Registry as `C1_NODRIVER`, holds the existing Control Lease, participates in cancellation/timeout cleanup, and persists rendered HTML through the existing evidence path.

No nodriver daemon, MCP server, REST listener, raw CDP endpoint or arbitrary JavaScript surface is exposed to callers.

## Dependency and license boundary

Pinned dependency:

```text
nodriver==0.50.3
```

nodriver is licensed under GNU AGPL-3.0. Current use is internal/local. Any future external hosted service or distribution that embeds or modifies nodriver requires a separate license/compliance review before promotion.

## Live verification — 2026-09-16

On the Mac mini development runtime:

- explicit ephemeral C1 against `https://example.com` succeeded;
- result reported `browser_engine=nodriver` and `engine_route.selected=nodriver`;
- HTTP status recovered as `200`;
- rendered HTML evidence was persisted with SHA-256;
- elapsed browser work was approximately `680 ms`;
- no fallback occurred;
- post-run `browserctl doctor` returned `READY`;
- stale profile leases: none;
- Browser Process Registry ownership residue: none.

This proves basic runtime compatibility with the current Python/Chrome environment. It does not prove material anti-bot advantage over Chrome or Camoufox.

## Promotion gate

Do not add nodriver to AUTO routing or C3 until a real-source A/B set demonstrates incremental value. Promotion requires:

- reproducible failure or material degradation on the normal route;
- nodriver succeeds materially more often on the same source and network conditions;
- repeated runs leave no process/lease residue;
- rendered evidence remains truthful;
- cancellation and timeout cleanup remain reliable;
- pinned nodriver/Chrome compatibility is retested after browser upgrades;
- any C3 promotion implements the full existing C3 contract rather than a reduced parallel API.

If A/B evidence shows no meaningful incremental value, keep nodriver installed but explicit-only.
