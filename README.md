# Mac Browser Plane

Mac Browser Plane is the browser execution runtime on the Mac mini. It gives authorized local or bridged AI callers a bounded C0–C3 browser capability surface while keeping browser lifecycle, state, profiles, leases, evidence, and engine routing inside one runtime.

## Current production status

**Status: OPERATIONAL / READY**

As of **2026-09-09**, the current checkout passed the full source regression suite (**56/56 tests**) and `browserctl doctor` returned `READY` with SQLite integrity `ok`, Chrome/Lightpanda/Camoufox available, no stale profile leases, and no Browser Process Registry ownership residue.

The current machine-readable contract is `src/browser_plane/capabilities.json`.

| Capability | Status | Primary surface |
| --- | --- | --- |
| C0 Fetch | COMPLETE | `browser_fetch` |
| C1 Render | COMPLETE | `browser_render` |
| C2 Read-only Inspect | COMPLETE | `browser_inspect` |
| C3 Browser Use | COMPLETE | `browser_use` |
| C3 Semantic Targeting / ARIA Snapshot | COMPLETE | `browser_use` |
| Local MCP adapter | OPERATIONAL | stdio `mac-browser-plane` |
| SignalForge remote provider invocation | OPERATIONAL | `pull_ssh_v1` |
| Autonomous embedded Browser Agent / LLM planner | DEFERRED | planning stays with caller |
| Headed human takeover | DEFERRED | not exposed |

## What this project is

```text
Authorized caller
  ├─ local CLI (`browserctl`)
  ├─ local MCP client (Codex / Hermes / OpenClaw / ChatGPT bridge)
  │    └─ stdio `mac-browser-plane`
  └─ SignalForge provider path
       └─ Mac Provider Agent -> outbound restricted SSH pull -> local MCP stdio

                         Mac Browser Plane
                                │
                      SQLite JobStore + leases
                                │
                         launchd Runtime Worker
                                │
             ┌──────────────────┼───────────────────┐
             │                  │                   │
          C0 curl         C1/C2/C3 Chrome      optional engines
                                               ├─ Lightpanda
                                               └─ Camoufox
                                │
                     private evidence artifacts
```

The caller owns task reasoning and planning. Browser Plane owns deterministic execution, lifecycle control, safety boundaries, and evidence.

## Engine routing

Engine choice is normally internal to Browser Plane.

| Work type | Current route |
| --- | --- |
| C0 HTTP/HTTPS fetch | macOS `/usr/bin/curl` |
| C1 ephemeral JS/DOM render | Lightpanda first, then safe Chrome fallback |
| C1 persistent profile | Chrome |
| C2 read-only inspect | Chrome |
| ordinary AUTO C3 Browser Use | Chrome |
| fingerprint-sensitive ephemeral C1/C3 | Camoufox only when explicitly/source-evidence selected |

Important fallback boundary: automatic Lightpanda -> Chrome fallback is limited to side-effect-safe ephemeral C1 work. Camoufox has no automatic cross-engine replay fallback.

See `docs/LIGHTPANDA_ENGINE_ROUTING.md` and `docs/CAMOUFOX_ENGINE_ROUTING.md`.

## C3 Browser Use

`browser_use` supports deterministic action sequences:

```text
navigate
click
type
select
press
wait
snapshot
screenshot
download
```

Targets may use CSS `selector`, ARIA `role` with optional accessible `name`, `label`, or visible `text_target`. Snapshot can include a bounded body-text excerpt and bounded ARIA snapshot for external planning.

Arbitrary JavaScript and raw CDP are not exposed.

## Quick start for development

Requirements:

- macOS;
- Python 3.12+;
- installed Google Chrome for the Chrome engine.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser,antidetect,agent,dev]'
.venv/bin/browserctl init
.venv/bin/browserctl doctor
```

Optional Lightpanda fast path:

```bash
brew install lightpanda-io/browser/lightpanda
```

Optional Camoufox browser asset:

```bash
.venv/bin/python -m camoufox fetch
```

## Production installation

Do not run the production LaunchAgent directly from the development checkout under `~/Documents`; macOS TCC can deny background access. Production code is copied into a separate non-editable runtime tree.

```bash
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_launchd.py
```

Production runtime root:

```text
~/agent-browser-runtime/
├── app/
├── state/runtime.db
├── profiles/
├── auth-state/
├── evidence/
├── logs/
├── backups/
└── run/
```

SignalForge provider production is installed separately from a reviewed Provider Invocation Contract:

```bash
python3 scripts/install_provider_launchd.py \
  --contract-source /path/to/signalforge/registry/Provider-Invocation-Contract-v1.json
```

The Provider Agent opens no Browser/MCP/CDP listener on the Mac. It polls Bangkok with a dedicated restricted SSH identity and invokes Browser Plane locally through MCP stdio.

## Local MCP

Production executable:

```text
~/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

The current MCP exposes ten tools: capabilities, doctor, artifact OCR, fetch, render, inspect, browser use, job status, job result, and job cancel. It is stdio-only and does not start a network listener. `artifact_ocr` is an orthogonal, networkless evidence-processing capability rather than a C4 browser level; P0 accepts only runtime-owned PNG/JPEG evidence and treats OCR output as enrichment, not authoritative business truth.

Recommended discovery sequence:

```text
browser_capabilities
browser_doctor      # when readiness matters
artifact_ocr        # orthogonal local evidence OCR (PNG/JPEG, mya+eng)
browser_fetch       # C0
browser_render      # C1
browser_inspect     # C2
browser_use         # C3
```

## Verification

Normal regression:

```bash
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/browserctl doctor
```

Lifecycle/race changes may additionally require the soak harness:

```bash
.venv/bin/python scripts/soak_m1.py --jobs 1000 --browser-jobs 5 --submitters 8
```

Do not run expensive browser/soak validation for documentation-only changes unless a deployment or runtime invariant is also being changed.

## Security invariants

- never use the user's Personal Chrome profile;
- CDP is loopback-only with a dynamic port;
- no public Browser/MCP/CDP listener;
- TLS verification remains enabled;
- ambiguous Browser process ownership fails closed;
- Browser processes are owned through registry + PID + macOS process-start identity;
- runtime/profile/evidence directories are `0700` and sensitive artifacts are `0600`;
- local MCP exposes no arbitrary JavaScript or raw CDP;
- cross-host SignalForge access is pull-only from the Mac with a dedicated restricted SSH identity and source/capability contract;
- no automatic Direct HTTP failure -> Browser replay policy exists.

See `docs/SECURITY.md`.

## Documentation map

Start with `docs/README.md`.

Current-state documentation:

- `docs/ARCHITECTURE.md` — component and execution architecture;
- `docs/PROJECT_STATUS.md` — current completion/deferred status;
- `docs/RUNBOOK.md` — operations and incident handling;
- `docs/DEPLOYMENT.md` — development vs production installation and rollback;
- `docs/DEVELOPMENT.md` — engineering workflow;
- `docs/TESTING.md` — test strategy and CI;
- `docs/SECURITY.md` — security model and invariants;
- `docs/DECISIONS.md` — architecture decision index;
- `docs/AI_CAPABILITY_ANNOUNCEMENT.md` — portable agent discovery contract.

Dated `*-CLOSURE-YYYY-MM-DD.md` files are historical acceptance evidence. They must not be interpreted as the current capability boundary when later current-state documents or `capabilities.json` supersede them.

## Project boundaries

Mac Browser Plane does not replace `vps-worker-plane` or SignalForge. Direct HTTP/API/ETL remains a separate acquisition path. The old VPS Browser/Crawlee runtime direction is superseded: Browser execution lives on the Mac mini.

Current deliberate deferrals include:

- autonomous embedded Browser Agent / LLM planner;
- headed/human takeover;
- SEA/VPS browser egress;
- China browser egress;
- a separate Chrome DevTools MCP daemon;
- Lightpanda or Camoufox native MCP/server surfaces.

New scope should be introduced only when a concrete source/business need justifies it.