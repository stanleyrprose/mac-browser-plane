# Mac Browser Plane R1 — Runtime Runbook

## 1. Health

```bash
cd /Users/xu/Documents/mcpx-projects/mac-browser-plane
.venv/bin/browserctl doctor
```

`READY` is required before normal M1 use.

## 2. Runtime home

```text
~/agent-browser-runtime/
```

Key paths:

```text
state/runtime.db
evidence/
profiles/
auth-state/
logs/
run/doctor.json
```

## 3. Worker service

LaunchAgent label:

```text
com.stanley.mac-browser-plane
```

Install:

```bash
.venv/bin/python scripts/install_launchd.py
```

Remove:

```bash
.venv/bin/python scripts/uninstall_launchd.py
```

FileVault/user-login is a real boot boundary: after a cold reboot/power cycle, Browser Plane may not become available until the user session is unlocked.

## 4. Job recovery

Only one Runtime Worker may execute Jobs at a time. The worker holds:

```text
~/agent-browser-runtime/run/worker.lock
```

A second worker exits with `WORKER_ALREADY_RUNNING`.

When a new Worker acquires the lock after an unclean shutdown, startup recovery:

1. finds Jobs left `RUNNING`, `PAUSED_FOR_INSPECTION`, `WAITING_HUMAN`, or `CANCEL_REQUESTED`;
2. reconciles registered Browser processes using PID + process-start identity + runtime-owned userDataDir when present;
3. gracefully terminates only processes whose ownership is proven;
4. marks gone owned processes closed;
5. moves interrupted Jobs to `RECOVERY_REQUIRED`;
6. releases Profile/Control leases only when process reconciliation is safe;
7. leaves ambiguous ownership fail-closed for operator review.

Do not delete Chrome SingletonLock files blindly, and do not re-run irreversible work unless idempotency is known.

## 5. Browser ownership

Never use broad commands such as:

```text
pkill Chrome
killall 'Google Chrome'
```

Browser Plane only terminates a process when runtime ownership is confirmed by its registry and macOS process-start token.

## 6. Profile rules

- Personal Chrome profile is never used.
- `public-research`, `authenticated-work`, and `development` are separate runtime directories.
- persistent profile ownership is exclusive;
- lease expiry alone is not permission to steal or delete profile state.

Runtime/private file permissions:

```text
runtime/profile/evidence directories = 0700
runtime.db / backups / doctor.json / result.json / screenshots = 0600
```

Do not loosen these permissions to solve an access problem; fix the caller/runtime ownership instead.

## 7. CDP / C2 read-only diagnostics

C1/C2 Chrome uses:

```text
--remote-debugging-port=0
```

The runtime reads the dynamically allocated local port from `DevToolsActivePort` and connects over loopback only.

C2 `task_type=inspect` runs in a dedicated diagnostic Browser Session and may only use the explicit diagnostic allowlist. Current CDP methods are limited to navigation-history, performance instrumentation/read, and accessibility-tree reads. `Runtime.evaluate` and other state-changing CDP methods are denied.

Run a diagnostic job:

```bash
.venv/bin/browserctl run --file examples/c2-smoke.json
```

Evidence includes `result.json` plus `screenshot.png`.

Never expose CDP publicly.

## 8. Backup

Git is canonical for source/config/docs.

Create an online SQLite-consistent runtime backup with:

```bash
browserctl backup
```

Default destination:

```text
~/agent-browser-runtime/backups/runtime-<timestamp>.db
```

The command uses SQLite's backup API and immediately runs `PRAGMA integrity_check`; it does not raw-copy the WAL database and does not require stopping the LaunchAgent.

This R1 backup intentionally covers runtime SQLite state only. Authenticated Chrome profiles/cookies are sensitive and are **not** copied automatically; disaster recovery may require re-authentication. Evidence is also not included in this minimal backup path.

## 9. Verification

```bash
.venv/bin/python -m unittest -v tests.test_core
.venv/bin/python scripts/soak_m1.py --jobs 1000 --browser-jobs 5 --submitters 8
.venv/bin/browserctl run --file examples/c2-smoke.json
.venv/bin/browserctl doctor
```

## 10. Scope boundary

R1 currently has no:

- SEA/VPS Browser egress;
- China Browser route;
- separate `chrome-devtools-mcp` server/adapter;
- Browser Use C3;
- SignalForge remote invocation.

Existing VPS Worker Runtime / SignalForge Direct HTTP remains a separate execution path.
