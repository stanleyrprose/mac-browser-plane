# Mac Browser Plane

Mac-centric local Browser Execution Plane implementing the frozen R1 v1.4.1 architecture.

**Current state:** Authorized R1 Operational Scope = **COMPLETE**. See `docs/R1-OPERATIONAL-BASELINE-CLOSURE-2026-09-04.md` for the implemented baseline, accepted operating boundaries, explicit deferrals, and evidence-based reopen rules.

## Boundary

```text
Mac mini
= Browser Router / Runtime / State / Profiles / Evidence

R1 network egress
= Mac mini direct Internet connection only
```

This repository does **not** replace `vps-worker-plane` or Bangkok SignalForge. Existing VPS Direct HTTP/API/ETL stays in the VPS Worker Runtime. The old future VPS Browser/Crawlee R3 direction is superseded by this project.

SignalForge-to-Mac unattended production invocation is intentionally not implemented in R1.

## M1 scope

Implemented in the first milestone:

- local `browserctl` CLI;
- SQLite runtime state with WAL, `synchronous=FULL`, `busy_timeout=5000`;
- Job state/version CAS;
- idempotent submit;
- queue / run / cancel lifecycle;
- single active Runtime Worker enforced by local `worker.lock`;
- startup recovery for interrupted active Jobs / owned Browser processes / leases;
- Profile Lease and browser-session Control Lease;
- Browser Process Registry using PID + macOS process-start token;
- C0 Direct Fetch using macOS `/usr/bin/curl` for HTTP/HTTPS with normal TLS verification; every HTTP response is preserved as a private raw artifact with SHA-256, with `text_excerpt` added only for textual content;
- C1 Playwright attached to runtime-owned local Google Chrome;
- dynamic loopback CDP port (`--remote-debugging-port=0`);
- explicit 1440×900 Browser viewport;
- Evidence `result.json`;
- `browserctl doctor`;
- launchd worker template;
- M1 1000-job soak harness.

Network simplification for R1:

- Browser traffic uses the Mac mini direct Internet connection;
- no SEA/VPS browser egress routing;
- no China Browser egress.

M3A simplified C2 is now implemented:

- `task_type=inspect` launches a dedicated diagnostic Chrome session;
- read-only CDP allowlist only;
- captures console, request/response summaries, navigation history, performance metrics, accessibility-tree count, and screenshot;
- no `Runtime.evaluate`, navigation/input mutation, cookie/storage mutation, or request mocking through the diagnostic CDP surface;
- no separate `chrome-devtools-mcp` server yet. Add an MCP adapter only when a real caller needs that protocol surface.

Still deferred:

- Browser Use C3;
- headed/human takeover;
- SignalForge remote provider invocation.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser,dev]'
.venv/bin/browserctl init
.venv/bin/browserctl doctor
```

The runtime reuses the installed macOS Google Chrome at:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

Override only when necessary:

```bash
export BROWSER_PLANE_CHROME=/path/to/Chrome
```

No Playwright-managed Chromium download is required.

## Runtime state

Default:

```text
~/agent-browser-runtime/
├── state/runtime.db
├── profiles/
├── auth-state/
├── evidence/
├── logs/
└── run/
```

Set `BROWSER_PLANE_HOME` to override for tests/isolated deployments.

## CLI

Initialize:

```bash
.venv/bin/browserctl init
```

Synchronous local job:

```bash
.venv/bin/browserctl run --file examples/c1-smoke.json
```

Read-only diagnostic job:

```bash
.venv/bin/browserctl run --file examples/c2-smoke.json
```

Queue:

```bash
.venv/bin/browserctl submit --file job.json
.venv/bin/browserctl status <job-id>
.venv/bin/browserctl wait <job-id> --timeout 30
.venv/bin/browserctl result <job-id>
.venv/bin/browserctl cancel <job-id>
```

Worker:

```bash
.venv/bin/browserctl worker
```

Doctor:

```bash
.venv/bin/browserctl doctor
```

SQLite-consistent runtime backup:

```bash
.venv/bin/browserctl backup
```

By default the snapshot is written under `~/agent-browser-runtime/backups/`. This backs up runtime SQLite state only; it does not copy authenticated Chrome profiles/cookies.

## Tests

```bash
.venv/bin/python -m unittest -v tests.test_core
.venv/bin/python scripts/soak_m1.py --jobs 1000 --browser-jobs 5 --submitters 8
```

## launchd

Do **not** run the LaunchAgent directly from a checkout under `~/Documents`. On macOS, `Documents` is TCC-protected; Terminal/Codex may have access while a background LaunchAgent does not. Production runtime is therefore installed separately under `~/agent-browser-runtime/app/`.

Install the release runtime, then the LaunchAgent:

```bash
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_launchd.py
```

The release venv is non-editable and independent from the development checkout. Updating source does not update the running release until `install_runtime.py` is run again.

Remove:

```bash
.venv/bin/python scripts/uninstall_launchd.py
```

The LaunchAgent requires a logged-in user session. Current host power/login behavior is recorded in `docs/HOST_READINESS.md`; R1 accepts manual macOS login after a cold power cycle rather than adding automatic login or a system LaunchDaemon.

## Security invariants

- never use the user's Personal Chrome profile;
- CDP stays loopback-only and dynamically allocated;
- no public `0.0.0.0:9222`;
- no TLS verification bypass;
- ambiguous Browser process ownership fails closed;
- browser/session mutation has one control owner;
- runtime state, backup, doctor/evidence JSON, and diagnostic screenshots are written `0600`; runtime/profile/evidence directories are `0700`;
- R1 has no cross-host Browser API;
- R1 does not install Browser runtime on VPS nodes.
