# Mac Host Readiness — Observed R1 State

**Observed on:** 2026-09-04  
**Host role:** Mac Browser Plane primary Browser Runtime  
**Change policy:** observation only; no power/security/login setting was modified during this audit.

## Current verdict

```text
Logged-in operating state = READY
Cold power-cycle state     = AUTO-POWER-ON / MANUAL-LOGIN-REQUIRED
```

This is an accepted simple R1 operating boundary. R1 does not add a LaunchDaemon, automatic-login configuration, pre-login Browser Runtime, or other system-level workaround.

## Observed host state

### System sleep / power recovery

`pmset -g custom` reports:

```text
sleep                0
autorestart          1
displaysleep         20
powernap             1
womp                 1
tcpkeepalive         1
```

Interpretation:

- system idle sleep is disabled on AC power;
- the Mac is configured to restart after power failure;
- display sleep remains enabled and is acceptable for current headless C0/C1/C2 operation;
- no additional sleep-prevention daemon is needed.

### FileVault

Observed:

```text
FileVault is Off.
```

Implication:

- there is no FileVault pre-boot unlock boundary on the current host;
- this does **not** mean FileVault should be disabled as a Browser Plane requirement;
- any future FileVault enable/disable decision is a host-security decision and is outside automatic Browser Plane changes.

### Login boundary

No `autoLoginUser` is configured in `/Library/Preferences/com.apple.loginwindow`.

The current Browser worker is a user `LaunchAgent`, so after a cold boot:

```text
power returns
→ Mac auto-restarts
→ macOS login screen
→ Browser Plane waits
→ user logs in
→ LaunchAgent starts
→ Browser Plane returns READY
```

R1 deliberately accepts this human-login recovery step rather than adding automatic login or a system LaunchDaemon.

### GUI / WindowServer

Observed:

```text
console user = logged-in runtime owner
WindowServer = running
```

The attached display reports:

```text
Resolution: 2560 x 1600
UI Looks like: 1280 x 800 @ 60 Hz
Online: Yes
Display Asleep: Yes
```

Display sleep does not block current headless Browser jobs. Headed/human-takeover behavior remains deferred until a real workflow requires it.

### Browser Plane LaunchAgent

Observed service:

```text
com.stanley.mac-browser-plane
state = running
KeepAlive = enabled
RunAtLoad = enabled
working directory = ~/agent-browser-runtime
program = ~/agent-browser-runtime/app/venv/bin/browserctl worker --max-jobs 0
```

The service is running from the installed release runtime, not the TCC-protected development checkout under `~/Documents`.

## Recovery semantics

### Normal user session

```text
worker crash
→ launchd restarts worker
→ startup reconciliation
→ owned Browser processes / leases reconciled
→ interrupted Jobs become RECOVERY_REQUIRED where needed
```

### Power loss

Current simple R1 behavior:

```text
power loss
→ Mac off
→ power returns
→ autorestart=1 boots macOS
→ manual user login required
→ LaunchAgent starts
→ startup recovery runs
```

This is not unattended HA. It is an explicit R1 operational playbook.

## What R1 intentionally does not add

- automatic-login password configuration;
- LaunchDaemon Browser execution before user login;
- disabling/enabling FileVault automatically;
- forced WindowServer restart;
- extra sleep-prevention daemon;
- HDMI dummy requirement for current headless workloads;
- remote GUI/session bootstrap hacks.

## Future trigger for revisiting this boundary

Only revisit cold-boot automation if a real business requirement proves that the manual-login recovery step causes unacceptable service loss.

If that happens, evaluate the smallest acceptable option with its security trade-off before changing the host.

## Final Host Readiness statement

> The current Mac mini is ready for R1 Browser Plane operation while a user session is logged in. It already avoids system sleep and automatically powers back on after power loss. Full unattended post-power-loss Browser recovery is intentionally not implemented; one manual macOS login remains the accepted recovery boundary.
