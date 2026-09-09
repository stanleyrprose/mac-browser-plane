# Configuration Reference

Mac Browser Plane intentionally has a small configuration surface. Most runtime policy is code/config-manifest controlled rather than spread across environment variables.

## 1. Runtime root

Environment variable:

```text
BROWSER_PLANE_HOME
```

Default:

```text
~/agent-browser-runtime
```

It controls the runtime root discovered by `RuntimePaths`.

Derived paths:

```text
$BROWSER_PLANE_HOME/
├── state/runtime.db
├── evidence/
├── profiles/
├── auth-state/
├── logs/
└── run/
```

Production installation also uses sibling application/backup/config material under the same runtime root as created by installer scripts.

### Test isolation

Use a temporary/isolated `BROWSER_PLANE_HOME` when a test must not touch production state:

```bash
export BROWSER_PLANE_HOME=/tmp/mac-browser-plane-test
```

Do not point ad-hoc tests at the production home unless the test is explicitly a production health/live-verification action.

## 2. Chrome executable

Environment variable:

```text
BROWSER_PLANE_CHROME
```

Default:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

Use the override only when the intended runtime-owned Chrome executable is installed elsewhere.

Example:

```bash
export BROWSER_PLANE_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

This does not authorize use of the user's Personal Chrome profile. Browser Plane profile isolation remains unchanged.

## 3. Lightpanda executable

Environment variable:

```text
BROWSER_PLANE_LIGHTPANDA
```

When unset, Browser Plane can discover the executable from normal locations including `PATH` and standard Homebrew locations used by the runtime.

Typical Apple Silicon install:

```bash
brew install lightpanda-io/browser/lightpanda
```

Example explicit override:

```bash
export BROWSER_PLANE_LIGHTPANDA=/opt/homebrew/bin/lightpanda
```

If Lightpanda is unavailable, routing follows the documented engine policy; do not expose a separate Lightpanda service as a workaround.

## 4. Camoufox

Camoufox is installed as a Python dependency plus its upstream browser asset. There is currently no Browser Plane environment variable selecting Camoufox for public callers.

Install/fetch the browser asset:

```bash
.venv/bin/python -m camoufox fetch
```

Camoufox routing is selective/internal and remains governed by source evidence and the runtime routing contract.

## 5. Engine routing configuration

Caller-facing engine truth is published in:

```text
src/browser_plane/capabilities.json
```

Current policy:

```text
C0                         -> curl
C1 ephemeral AUTO          -> Lightpanda -> safe Chrome fallback
C1 persistent              -> Chrome
C2                         -> Chrome
C3 AUTO                    -> Chrome
C1/C3 selective            -> Camoufox only with explicit/source evidence
```

There is no supported environment switch that globally forces Browser Plane AUTO traffic to Camoufox.

## 6. Profiles

Runtime-created profiles:

```text
public-research
authenticated-work
development
```

Directory root:

```text
$BROWSER_PLANE_HOME/profiles/
```

Profile directories are private (`0700`).

The local MCP intentionally exposes only:

```text
ephemeral
exclusive-persistent
```

Personal Chrome profile use is forbidden.

## 7. SQLite runtime configuration

These are runtime invariants, not ordinary operator knobs:

```text
journal_mode = WAL
synchronous = FULL
busy_timeout = 5000 ms
```

Do not weaken them through manual database tuning to increase throughput without an explicit state-safety decision.

Primary DB:

```text
$BROWSER_PLANE_HOME/state/runtime.db
```

Use `browserctl backup` rather than raw-copying a live WAL database.

## 8. Filesystem permissions

Expected security boundary:

```text
runtime/profile/evidence directories = 0700
sensitive runtime/evidence files      = 0600
```

Do not solve access problems by widening these permissions. Fix process/user ownership or caller configuration instead.

## 9. launchd runtime configuration

Templates live under:

```text
launchd/
```

Runtime worker template:

```text
com.stanley.mac-browser-plane.plist.in
```

Provider Agent template:

```text
com.stanley.mac-browser-provider.plist.in
```

Install through repository installer scripts rather than editing generated production plist files by hand:

```bash
.venv/bin/python scripts/install_runtime.py
.venv/bin/python scripts/install_launchd.py
```

Provider installation is separate because it requires a reviewed cross-repository contract:

```bash
python3 scripts/install_provider_launchd.py \
  --contract-source /path/to/signalforge/registry/Provider-Invocation-Contract-v1.json
```

## 10. Provider configuration boundary

Provider production configuration is deliberately **not** represented by a broad set of Browser Plane environment variables.

The important controls are:

- dedicated provider SSH identity;
- restricted outbound SSH transport;
- reviewed Provider Invocation Contract;
- source/capability/URL allowlisting;
- local MCP stdio invocation;
- launchd service installation.

Do not replace the dedicated provider identity with an administrative SSH key, and do not open an inbound Browser/MCP/CDP listener as a configuration shortcut.

## 11. Network/egress configuration

Current production Browser egress:

```text
Mac direct Internet only
```

`capabilities.json` reports SEA and China browser egress as disabled.

Although model enums retain future/deferred values, the runtime preflight currently accepts only `auto` or `direct` egress. Do not configure regional egress without a separately approved source/business requirement.

## 12. Configuration source-of-truth rule

Use this precedence when checking effective Browser Plane configuration:

1. current source/runtime behavior;
2. `src/browser_plane/capabilities.json` for public capability/routing truth;
3. installer/launchd template for service wiring;
4. environment variables documented here;
5. current operational docs.

Dated closure documents can contain old point-in-time configuration and should not be treated as current override instructions.