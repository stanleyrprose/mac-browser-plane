# Lightpanda C1 Production Closure — 2026-09-08

## Status

**PASS — production rollout complete.**

Lightpanda is now an internal Mac Browser Plane execution engine for eligible ephemeral C1 `browser_render` jobs. The existing external MCP contract remains unchanged.

Implementation PR: **#33 — `feat: add Lightpanda C1 engine routing`**  
Merged main commit: **`027ec9e2e828038887e5cb3cc8ad64cc299fc14f`**

## Production routing contract

```text
C0 browser_fetch
  -> macOS system curl

C1 browser_render + ephemeral profile
  -> Lightpanda first
  -> Chrome fallback only on safe C1 execution/compatibility/quality failure

C1 browser_render + persistent profile
  -> Chrome

C2 browser_inspect
  -> Chrome

C3 browser_use
  -> Chrome
```

Routing remains capability-based rather than source-domain-based. Callers do not choose engines through MCP.

## Preserved boundaries

The rollout did **not** add:

- a tenth MCP tool;
- Lightpanda MCP exposure;
- Lightpanda native Agent exposure;
- a persistent Lightpanda daemon;
- a second Browser worker;
- a public Browser/CDP/MCP listener;
- Lightpanda persistent profiles;
- Lightpanda C2 or C3;
- autonomous Browser planning;
- source-domain routing rules.

The calling agent still owns reasoning/planning. Mac Browser Plane still owns deterministic execution, lifecycle, evidence, leases, and cleanup.

## Implementation verification

Before merge:

- source `compileall`: PASS;
- source full test suite: **54/54 PASS**;
- native Lightpanda C1 live smoke against `https://example.com`: PASS;
- Lightpanda installed from Homebrew as `1.0.0-nightly.9268+909108e29`.

GitHub PR #33 checks:

- `test`: **SUCCESS**;
- PR merge state before merge: `clean`;
- merge method: squash.

After merge, local checkout was reset to `origin/main` and verified clean. The merged-main source suite again passed **54/54**.

## Production deployment

The non-editable runtime was rebuilt from merged `main` using `scripts/install_runtime.py`, recreating:

```text
~/agent-browser-runtime/app/venv
```

The Browser Plane LaunchAgent was reinstalled/reloaded with `scripts/install_launchd.py`.

The Provider Agent was explicitly kickstarted after the runtime rebuild so it also runs against the rebuilt runtime path. Both LaunchAgents were verified `state = running`:

- `com.stanley.mac-browser-plane`;
- `com.stanley.mac-browser-provider`.

## Installed capability verification

Installed `browserctl capabilities` reported:

- `lightpanda_engine = true`;
- `engine_auto_routing = true`;
- `engine_routing.policy = auto_v1`;
- ephemeral C1 = `lightpanda_then_chrome_fallback`;
- persistent C1 = `chrome`;
- C2 = `chrome`;
- C3 = `chrome`;
- Lightpanda native MCP/Agent exposure = false.

Installed `browserctl doctor` reported **READY**, including:

```text
lightpanda_optional.installed = true
lightpanda_optional.path = /opt/homebrew/bin/lightpanda
sqlite_integrity = ok
stale_profile_leases = []
browser_process_ownership = []
```

## Real production MCP acceptance

The installed runtime's real stdio MCP handshake returned exactly the authorized **9/9 tools** with no missing or unexpected tools.

### C1 Lightpanda fast path

Real installed-MCP call:

```text
browser_render(https://example.com, profile_mode=ephemeral)
```

Result:

```text
job_id          = 6740b229-0b4d-4267-89ea-83d57de0c531
state           = SUCCEEDED
HTTP            = 200
engine          = c1-lightpanda
browser_engine  = lightpanda
selected        = lightpanda
attempted       = [lightpanda]
fallback        = null
route_reason    = auto_lightpanda_eligible
elapsed_ms      = 380
```

This proves the production MCP -> JobStore -> LaunchAgent worker -> internal engine router -> Lightpanda path is live, rather than only a source-level or direct-binary smoke.

### C3 Chrome compatibility path

Real installed-MCP call:

```text
browser_use(https://example.com, actions=[snapshot])
```

Result:

```text
job_id          = 98a18adc-3538-4cf8-a009-b72104579cb7
state           = SUCCEEDED
HTTP            = 200
engine          = c3-browser-use
browser_engine  = chrome
selected        = chrome
attempted       = [chrome]
fallback        = null
route_reason    = c3_requires_chrome_v1
```

This proves the Lightpanda rollout did not accidentally move C3 off the Chrome compatibility path.

## Post-live residue check

After both production MCP smokes:

```text
SQLite integrity        = ok
Control Leases          = 0
Profile Leases          = 0
RUNNING browser process = 0
browserctl doctor       = READY
```

No persistent Lightpanda process or additional listener was introduced.

## Closure decision

The Lightpanda C1 engine slice is accepted as a production Browser Plane capability.

The authoritative v1 rule remains:

> Use Lightpanda automatically for eligible ephemeral C1 DOM/JS rendering; keep Chrome as the persistent-profile, diagnostic, interaction, and compatibility engine. Only C1 may automatically fall back from Lightpanda to Chrome because that replay is side-effect safe.

Any future Lightpanda expansion into C2 or C3 requires a separate promotion gate under `docs/LIGHTPANDA_ENGINE_ROUTING.md`; this closure does not authorize that expansion.
