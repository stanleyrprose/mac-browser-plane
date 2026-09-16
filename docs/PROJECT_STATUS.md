# Project Status

**Project:** Mac Browser Plane  
**Current package version:** `0.1.0`  
**Status date:** 2026-09-16
**Production state:** **OPERATIONAL / READY**

## 1. Current capability status

| Area | Status |
| --- | --- |
| C0 Fetch + raw artifact | COMPLETE |
| C1 Render | COMPLETE |
| C2 Read-only Inspect | COMPLETE |
| C3 deterministic Browser Use | COMPLETE |
| C3 semantic targeting | COMPLETE |
| C3 bounded ARIA snapshot | COMPLETE |
| Persistent runtime profiles | COMPLETE |
| SQLite/leases/process ownership/recovery | COMPLETE |
| Local MCP stdio adapter | COMPLETE / OPERATIONAL |
| Artifact OCR (`mya+eng`) | P0 COMPLETE / LOCAL + CODEXPRO |
| Network Trace (`mitmdump`) | P1 COMPLETE / LOCAL OPERATOR DIAGNOSTIC / DEFAULT OFF |
| Lightpanda ephemeral C1 fast path | COMPLETE / OPTIONAL ENGINE |
| Camoufox selective ephemeral C1/C3 | COMPLETE / OPTIONAL ENGINE |
| nodriver explicit ephemeral C1 | COMPLETE / OPTIONAL ENGINE |
| SignalForge Provider `pull_ssh_v1` | COMPLETE / PRODUCTION ENABLED |
| Autonomous embedded Browser Agent | DEFERRED |
| Headed human takeover | DEFERRED |
| SEA/VPS browser egress | DEFERRED / NOT CURRENT NEED |
| China browser egress | DEFERRED / NOT CURRENT NEED |

## 2. Fresh verification — 2026-09-11

Local source/runtime verification after Artifact OCR P0 implementation:

- full source regression: **65/65 PASS**;
- `browserctl doctor`: **READY**;
- SQLite integrity: `ok`;
- SQLite WAL: enabled;
- SQLite synchronous: FULL (`2`);
- SQLite busy timeout: `5000`;
- Chrome: available;
- Lightpanda: installed at `/opt/homebrew/bin/lightpanda`;
- Camoufox Python/browser asset: available, browser `152.0.4-beta.30`;
- Artifact OCR: Tesseract `5.5.3`, runtime-local `tessdata_best`, fixed `mya+eng`, ready;
- real MTE official-image MCP smoke: expected SHA-256, `20` OCR lines, mean confidence `79.22`, date `2026-09-15`, time `08:30`, and approximately `6243` tons recovered;
- local/CodexPro OCR invocation enabled; SignalForge Provider OCR authorization remains disabled;
- stale Profile Leases: none;
- Browser Process Registry ownership residue: none.

This is a health snapshot, not a guarantee that every external website is reachable or unchanged.

### 2.1 Network Trace P1 verification — 2026-09-16

- Homebrew `mitmproxy` 12.2.3 installed; `mitmdump` available at `/opt/homebrew/bin/mitmdump`;
- `browserctl trace doctor`: READY, default OFF, loopback only;
- bounded smoke used explicit host `httpbin.org` and loopback proxy `127.0.0.1:18080`;
- `GET http://httpbin.org/json` returned HTTP 200 / `application/json`;
- trace summary recorded exactly one flow and classified it `api_like=true`;
- retained metadata excluded request/response bodies, query strings, and request headers;
- trace process stopped through the existing Browser Process Registry ownership check;
- no system proxy setting or CA trust store was changed;
- full repo regression after P1: **79/79 PASS** using the project `.venv`.

### 2.2 C2 API discovery verification — 2026-09-16

Real-source checks established the escalation boundary before adding more mitmproxy integration:

- Ministry of Industry S38 detail and listing pages expose business data directly in server-rendered HTML; no business-data API was observed, so Network Trace escalation is not justified for S38;
- ATOM's JavaScript-heavy media UI exposed `GET /api/v1/medias?locale=en&year=2026&page=1` as same-origin XHR / HTTP 200 / `application/json` through ordinary C2 Inspect;
- C2 now derives bounded `api_candidates` from XHR/fetch metadata and excludes obvious analytics/captcha noise;
- the ATOM smoke produced exactly one candidate, the official media API, with score `9`;
- this establishes C2 as the default API-discovery layer and keeps mitmproxy as a deeper second-stage diagnostic only when C2 evidence is insufficient;
- full repository regression after the C2 enhancement: **83/83 PASS** using the project `.venv`;
- PR `#47` was squash-merged as `cdc6066463f66515d73e680f10007ce24207baa5` and installed into `~/agent-browser-runtime/app` using the reviewed production install/update path;
- the user LaunchAgent was reinstalled/restarted successfully and production `browserctl doctor` returned **READY**;
- production manifest reports `c2_api_candidates=true`, and production job `05ca8819-8d71-4dfe-ba73-daffefd3b8a4` returned exactly the ATOM media API candidate with HTTP `200`, `application/json`, score `9`;
- post-smoke doctor reported no stale profile leases and no Browser Process Registry ownership residue;
- production `browserctl trace doctor` remains **READY / default OFF / loopback only**.

### 2.3 nodriver C1 verification — 2026-09-16

- pinned `nodriver==0.50.3` installed in the development runtime;
- explicit ephemeral C1 smoke against `https://example.com` returned HTTP 200 with `engine_route.selected=nodriver` and no fallback;
- rendered HTML evidence and SHA-256 were persisted through the existing evidence path;
- browser work completed in approximately 680 ms on the verification run;
- post-run `browserctl doctor` returned **READY** and reported `nodriver_optional` ready;
- stale profile leases: none; Browser Process Registry ownership residue: none;
- full repository regression after integration: **87/87 PASS**;
- v1 remains explicit C1 only: no AUTO promotion, persistent profile, C2, C3, or automatic cross-engine replay.

### 2.4 nodriver real-source A/B and hydration hardening — 2026-09-16

- production-runtime A/B covered ATOM Media, Mytel, and MPT Tenders across AUTO/Lightpanda, Chrome, nodriver, and Camoufox;
- the first nodriver pass returned HTTP 200 but empty body text on all three sources because the original fixed 0.5-second wait could finish before client-side hydration;
- ATOM demonstrated the failure mode clearly: the early nodriver DOM was about 6.9 KB while Lightpanda/Chrome were about 92 KB and contained the current press-release content;
- nodriver now polls for non-empty rendered body text at 0.5-second intervals for at most 5 seconds and fails closed if useful body content never appears;
- the result records `content_ready_wait_ms` for evidence/debugging;
- post-fix real-source helper verification recovered useful text on ATOM, Mytel, and MPT; ATOM recovered the current `Bright Futures` press-release content after about 1.56 seconds;
- targeted regression: **36/36 PASS**; full repository regression: **90/90 PASS**;
- routing decision is unchanged: no evidence yet justifies nodriver AUTO promotion; normal AUTO/Lightpanda remains preferred.

### 2.5 unified C1 content-quality gate — 2026-09-16

- real SignalForge-source A/B exposed false-success cases where an engine could report HTTP/navigation success with an empty rendered body: S21 Myanma Railways returned a 15-byte Lightpanda shell with zero text, S16 YCDC returned an 85-byte Lightpanda shell on one run, and S41 MYTEL/Viettel returned HTTP 200 with zero Camoufox body text on one run;
- C1 now requires non-empty rendered body text through one source-independent gate (`nonempty_rendered_body_v1`) before success is reported;
- Lightpanda validates its rendered text immediately; under AUTO an empty-body quality failure uses the existing side-effect-safe Chrome fallback, while explicit Lightpanda fails closed;
- Chrome and Camoufox poll for useful rendered body text for at most 5 seconds after `DOMContentLoaded`; nodriver retains its bounded hydration poll but now reports the same quality metadata contract;
- the gate does **not** classify non-empty stopped-site, login, access-denied, or challenge pages as business success; it only guarantees that Browser Plane returns truthful non-empty rendered content for the caller/source policy to classify;
- fresh S21 explicit-Lightpanda verification now fails with `C1ContentQualityError` instead of false success; AUTO then attempts Chrome and truthfully fails on the same source's current network timeout;
- fresh S16 verification returned a real 84 KB body through Lightpanda and passed the gate without unnecessary fallback, proving the gate preserves the fast path when content is actually present;
- fresh S41 Camoufox verification waited about 1.56 seconds and recovered the real JSON body instead of the previous empty-body HTTP 200;
- targeted regression: **40/40 PASS**; full repository regression: **94/94 PASS**;
- no AUTO promotion, new engine, source-specific rule, provider-contract change, or TLS weakening was introduced.

## 3. Production invocation modes

### Local

- `browserctl` CLI;
- stdio MCP server `mac-browser-plane`;
- external caller owns reasoning/planning.

### SignalForge

Production is enabled using `pull_ssh_v1`:

- Provider Agent runs on Mac;
- Mac initiates outbound restricted SSH polling to Bangkok;
- requests are validated against the reviewed Provider Invocation Contract;
- Browser capability is invoked through local MCP stdio;
- no inbound Browser/MCP/CDP listener exists on the Mac.

## 4. Current engine policy

```text
C0                         curl
C1 ephemeral AUTO          Lightpanda -> Chrome safe fallback
C1 persistent              Chrome
C2                         Chrome
C3 AUTO                    Chrome
C1/C3 selective            Camoufox with explicit/source evidence
C1 selective Chromium      nodriver explicit only (ephemeral v1)
```

Camoufox and nodriver have no automatic replay fallback. Lightpanda fallback is restricted to side-effect-safe ephemeral C1.

## 5. Accepted production boundaries

- Browser egress is Mac direct Internet only;
- Personal Chrome profile is never used;
- production runtime is installed outside `~/Documents`;
- Runtime Worker is a user LaunchAgent;
- manual macOS login may be required after a cold power cycle/FileVault boot;
- no separate Chrome DevTools MCP daemon;
- no autonomous LLM planner inside Browser Plane.

## 6. Historical milestones

- 2026-09-04: R1 operational baseline closure;
- 2026-09-05: local Agent MCP Adapter v0 live closure;
- 2026-09-08: PIC R4 SignalForge Provider production closure;
- 2026-09-08: Lightpanda C1 production closure;
- 2026-09-08: Camoufox selective engine production verification recorded;
- 2026-09-11: Artifact OCR P0 local/CodexPro production acceptance completed.

See dated closure documents for evidence from each stage.

## 7. Documentation consistency note

Earlier R1 documents can truthfully say that C3 or remote provider invocation was deferred **at that stage**. Those statements are historical, not current. Current status is defined by this file plus `src/browser_plane/capabilities.json` and current architecture/engine contracts.

## 8. Reopen gates / future work

Do not expand the architecture merely because a capability could be added. Reopen a deferred area only with concrete evidence/business need, for example:

- real source requires regional egress that direct Mac egress cannot meet;
- real source A/B proves Camoufox materially improves reliability;
- a caller requires a new capability not expressible through the current 10-tool MCP surface;
- human takeover becomes a real operational requirement;
- autonomous Browser planning provides material value that cannot remain in the caller.

Future work should preserve the current one-runtime/one-worker/state-authority model unless evidence shows it is insufficient.