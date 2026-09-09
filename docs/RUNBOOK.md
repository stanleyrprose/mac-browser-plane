# Mac Browser Plane — Production Runbook

This runbook describes the **current** production state. Dated R1/PIC closure files remain historical acceptance evidence.

## 1. Normal health check

From the development checkout:

```bash
cd /Users/xu/Documents/mcpx-projects/mac-browser-plane
.venv/bin/browserctl doctor
```

Expected status:

```text
READY
```

Important checks include runtime paths, SQLite integrity/WAL/FULL/busy timeout, Chrome, optional Lightpanda/Camoufox readiness, stale Profile Leases, Browser Process Registry ownership, and free disk.

If `doctor` is not READY, classify the failed check before restarting or modifying anything.

## 2. Services

Runtime worker LaunchAgent:

```text
com.stanley.mac-browser-plane
```

Provider Agent LaunchAgent:

```text
com.stanley.mac-browser-provider
```

The Provider Agent is a separate polling/invocation service, not a second Browser worker. It ultimately submits work through the same local MCP/JobStore execution path.

## 3. Runtime locations

```text
Development source:
~/Documents/mcpx-projects/mac-browser-plane/

Production app:
~/agent-browser-runtime/app/

Runtime state:
~/agent-browser-runtime/state/runtime.db

Profiles:
~/agent-browser-runtime/profiles/

Evidence:
~/agent-browser-runtime/evidence/

Logs:
~/agent-browser-runtime/logs/

Run/doctor state:
~/agent-browser-runtime/run/

Backups:
~/agent-browser-runtime/backups/
```

Do not point launchd directly at the checkout under `~/Documents`.

## 4. Production update

After a reviewed source revision is ready:

```bash
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_launchd.py
.venv/bin/browserctl doctor
```

If Provider Agent code/contract needs production installation, use the reviewed contract source:

```bash
python3 scripts/install_provider_launchd.py \
  --contract-source /path/to/signalforge/registry/Provider-Invocation-Contract-v1.json
```

Do not invent or broaden the Provider contract during deployment.

## 5. Local job operations

Synchronous job:

```bash
.venv/bin/browserctl run --file job.json
```

Queue lifecycle:

```bash
.venv/bin/browserctl submit --file job.json
.venv/bin/browserctl status <job-id>
.venv/bin/browserctl wait <job-id> --timeout 30
.venv/bin/browserctl result <job-id>
.venv/bin/browserctl cancel <job-id>
```

Capability discovery:

```bash
.venv/bin/browserctl capabilities
```

## 6. Recovery after crash/reboot

Only one Runtime Worker may own execution. It holds:

```text
~/agent-browser-runtime/run/worker.lock
```

A second worker should fail with `WORKER_ALREADY_RUNNING`.

On unclean startup, allow built-in recovery to reconcile interrupted jobs, owned processes, and leases. Do not manually delete locks/profile state or broadly kill browsers first.

Interrupted work can become `RECOVERY_REQUIRED`. Before replaying a job, determine whether it was read-only/idempotent and whether `partial_effect_possible` is true.

## 7. Browser ownership incident

Never use:

```text
pkill Chrome
killall 'Google Chrome'
```

Browser Plane terminates only processes whose ownership is proven by the Browser Process Registry plus PID/start-token identity.

If ownership is ambiguous, fail closed and inspect rather than killing a potentially personal browser.

## 8. Profile incident

Rules:

- Personal Chrome profile is forbidden;
- runtime profiles are isolated;
- persistent profile ownership is exclusive;
- lease expiry is not permission to delete or steal profile state;
- stale `DevToolsActivePort` cleanup is performed only by runtime logic under the exclusive lease;
- do not delete Chrome SingletonLock/SingletonCookie blindly.

## 9. Engine troubleshooting

### C0 curl

A TLS/client failure does not automatically mean the source requires a browser. Keep TLS verification enabled and classify the failure.

### C1 Lightpanda

Ephemeral C1 AUTO may try Lightpanda then fall back to Chrome only when replay is side-effect safe. Inspect `engine_route` evidence for attempted/selected engine and fallback reason.

### C2 Chrome

C2 depends on Chrome diagnostic semantics and remains Chrome-only.

### C3 Chrome

Ordinary AUTO C3 uses Chrome. Do not replay a failed mutating C3 sequence across engines automatically.

### Camoufox

Camoufox is selective only. It should be chosen from explicit/source evidence, not generic rules such as `403 -> Camoufox`. No automatic cross-engine fallback is allowed.

## 10. Evidence

C0 persists the full raw HTTP response privately with SHA-256. C1/C2/C3 persist bounded result/evidence records; screenshots/downloads stay under the evidence tree when produced.

Do not copy evidence into the Git repository. Evidence may contain sensitive site/session information.

## 11. Backup

Create an online SQLite-consistent backup:

```bash
.venv/bin/browserctl backup
```

The command uses SQLite backup semantics and runs integrity checking. Do not raw-copy a live WAL database as the normal backup method.

Current backup scope is runtime SQLite state only. Authenticated profile/cookie state and evidence are intentionally not copied by this minimal backup path; recovery may require re-authentication.

## 12. Cold power-cycle boundary

The host is configured to restart after power loss, but the Browser Plane Runtime Worker is a user LaunchAgent. FileVault/user-session state means a manual macOS login may be required after a cold boot before Browser Plane returns to READY.

This is an accepted current boundary, not a service bug.

## 13. Provider path incident

Provider production is pull-only from the Mac:

```text
Mac Provider Agent -> restricted outbound SSH -> Bangkok claim/report
                  -> local MCP stdio -> Browser Plane worker
```

If SignalForge provider work stops:

1. verify base `browserctl doctor` first;
2. distinguish local Browser Plane health from Provider transport/contract failure;
3. verify the dedicated provider identity/contract has not been broadened or replaced;
4. do not open an inbound Browser/MCP/CDP port as a workaround;
5. do not use an administrative SSH identity in place of the dedicated provider identity.

## 14. Post-incident verification

Minimum closure:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/browserctl doctor
```

For lifecycle/concurrency/process ownership fixes, add the relevant targeted regression test and, when warranted, the soak harness. Avoid unrelated test expansion.