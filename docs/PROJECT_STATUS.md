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
```

Camoufox has no automatic replay fallback. Lightpanda fallback is restricted to side-effect-safe ephemeral C1.

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