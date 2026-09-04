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

If a job is left `RUNNING`, `WAITING_HUMAN`, or `CANCEL_REQUESTED` after an unclean shutdown:

1. run `browserctl doctor`;
2. inspect Browser Process Registry and lease state;
3. do not delete Chrome SingletonLock files blindly;
4. do not re-run irreversible work unless idempotency is known;
5. ambiguous work remains `RECOVERY_REQUIRED` for operator review.

M1 does not automatically claim that every abandoned job is safe to retry.

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

SQLite backup must be SQLite-consistent (`sqlite3 .backup` / backup API), not a raw main-file copy while WAL is active.

Authenticated profile/session backups are sensitive and may be omitted in favor of re-authentication after disaster recovery.

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
