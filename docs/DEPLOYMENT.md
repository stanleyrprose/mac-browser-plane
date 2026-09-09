# Deployment and Rollback

## 1. Deployment model

Development source and production runtime are deliberately separate:

```text
~/Documents/mcpx-projects/mac-browser-plane/
  = Git development checkout

~/agent-browser-runtime/app/
  = non-editable installed production application
```

Reason: macOS TCC can block background LaunchAgents from `~/Documents`, and an in-progress editable checkout must not automatically mutate the running service.

## 2. Prerequisites

- macOS user session;
- Python 3.12+ for development/install tooling;
- Google Chrome installed at the normal application path (or explicit `BROWSER_PLANE_CHROME` override);
- optional Lightpanda binary for ephemeral C1 fast path;
- optional Camoufox package/browser asset for selective engine use.

## 3. Development install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser,antidetect,agent,dev]'
.venv/bin/browserctl init
.venv/bin/browserctl doctor
```

## 4. Production runtime install/update

From a reviewed source revision:

```bash
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_launchd.py
.venv/bin/browserctl doctor
```

`install_runtime.py` builds/installs the release runtime separately from the editable development venv. Updating Git source alone does not update the running production service.

## 5. Optional engines

Lightpanda:

```bash
brew install lightpanda-io/browser/lightpanda
```

Camoufox asset:

```bash
.venv/bin/python -m camoufox fetch
```

Their presence does not alter the caller-facing MCP contract. Routing remains controlled by `capabilities.json` and the engine routing documents.

## 6. SignalForge Provider production

Provider production requires the reviewed cross-repository contract and a dedicated restricted provider SSH identity.

```bash
python3 scripts/install_provider_launchd.py \
  --contract-source /path/to/signalforge/registry/Provider-Invocation-Contract-v1.json
```

Deployment must preserve:

- outbound/pull-only SSH from the Mac;
- local MCP stdio invocation;
- no inbound Mac Browser/MCP/CDP listener;
- dedicated provider identity rather than an administrative key;
- source/capability/URL allowlisting from the reviewed contract.

## 7. Pre-deployment checks

For code changes, require the smallest relevant set plus normal regression:

```bash
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m unittest discover -s tests -v
```

Run the full soak only when lifecycle/concurrency/recovery behavior warrants it.

## 8. Post-deployment checks

At minimum:

```bash
.venv/bin/browserctl doctor
```

For behavior changes, perform one bounded live smoke for the affected capability/engine and verify no process/lease residue afterward.

For Provider changes, verify the Provider Agent can remain idle without work and complete one explicitly authorized end-to-end claim when production acceptance is required.

## 9. Rollback

Rollback is source-revision based; there is currently no separate binary release channel.

Safe rollback procedure:

1. select a known-good Git revision that was previously accepted;
2. ensure the checkout/worktree contains exactly that reviewed source;
3. run its relevant regression tests;
4. rerun `scripts/install_runtime.py`;
5. rerun `scripts/install_launchd.py`;
6. if Provider code/contract is part of the rollback, reinstall it only with the intended reviewed Provider contract;
7. run `browserctl doctor`;
8. run one bounded live smoke for the restored critical path.

Do not restore runtime SQLite by raw-copying a live WAL database. Use `browserctl backup` snapshots for state recovery.

## 10. Runtime state backup

```bash
.venv/bin/browserctl backup
```

Default destination:

```text
~/agent-browser-runtime/backups/runtime-<timestamp>.db
```

The backup covers runtime SQLite state, not authenticated profiles/cookies or evidence.

## 11. Boot/restart boundary

The Runtime Worker is a user LaunchAgent. The Mac may auto-restart after power loss, but FileVault/user-session constraints can require manual login before the LaunchAgent returns to service.

Do not change this to automatic login or a system LaunchDaemon merely to eliminate the boundary without a separate security/operations decision.