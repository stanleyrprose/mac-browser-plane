# Security Model

## 1. Security objective

Mac Browser Plane must allow useful browser automation without turning the Mac into a general remote-control or browser-debugging endpoint.

The core model is **bounded local execution + explicit ownership + private evidence + pull-only remote authorization**.

## 2. Trust boundaries

```text
External websites
      │
      ▼
Browser engines / curl
      │
      ▼
Mac Browser Plane executor
      │
      ├─ SQLite state / leases / process registry
      ├─ private profiles/evidence
      └─ bounded local MCP stdio
                ▲
                │
       authorized local caller

SignalForge/Bangkok
      ▲
      │ restricted SSH claim/report
      │
Mac Provider Agent (outbound initiator)
      │
      └─ local MCP stdio
```

## 3. Network exposure

Current invariants:

- no public Browser API;
- no HTTP/WebSocket MCP listener;
- no public CDP listener;
- Chrome CDP uses dynamic loopback port only;
- Provider Agent initiates outbound restricted SSH polling;
- Lightpanda/Camoufox native server/MCP surfaces are not exposed.

Opening an inbound Browser/MCP/CDP port is an architecture/security change, not an operational workaround.

## 4. Browser/profile isolation

- Personal Chrome profile is forbidden;
- runtime profiles are separate directories;
- persistent profile ownership is exclusive;
- lease expiry alone is not permission to steal/delete state;
- Browser Plane cleans only runtime-owned discovery state under the proper lease;
- broad Chrome process killing is forbidden.

## 5. Process ownership

A browser/wrapper process can be terminated only when runtime ownership is proven through the Browser Process Registry and process identity checks (PID + macOS process-start token, with runtime-owned user-data context when relevant).

Ambiguous ownership fails closed.

## 6. MCP authority

The local MCP intentionally exposes bounded high-level tools rather than arbitrary execution.

Not exposed:

- arbitrary JavaScript;
- raw CDP;
- arbitrary Playwright objects;
- shell execution;
- engine-native MCP/REST servers.

C3 actions are a closed deterministic set advertised in `capabilities.json`.

## 7. C2 read-only boundary

C2 uses a dedicated Chrome diagnostic session and explicit CDP allowlist. Mutating/evaluation methods such as `Runtime.evaluate` are denied.

If a future diagnostic requirement needs mutation, it should be modeled as C3 or a separately reviewed capability, not silently added to C2.

## 8. Remote Provider authorization

SignalForge provider production must preserve all of the following:

- Mac-initiated pull model;
- dedicated restricted SSH identity;
- reviewed Provider Invocation Contract;
- explicit source/capability/URL authorization;
- validation before local MCP execution;
- bounded evidence/result packaging;
- no administrative SSH key reuse;
- no inbound Mac Browser/MCP/CDP listener.

A Direct HTTP failure is not authorization to invoke Browser capability. Source policy decides whether Browser use is allowed.

## 9. Engine routing security

### Lightpanda

Automatic fallback to Chrome exists only for ephemeral C1 where replay is side-effect safe.

### Camoufox

Camoufox must not be triggered from generic signals such as HTTP 403. Selection requires explicit/source evidence. There is no automatic cross-engine replay, especially for C3.

## 10. TLS and URL handling

C0 uses system curl with normal TLS verification. Do not add `-k`/`--insecure` as a normal fix.

The agent-facing web surface rejects obvious non-web/local targets. Authorization and network controls should fail closed rather than broaden target reach on error.

## 11. Files and permissions

Sensitive runtime files (runtime DB, backups, doctor/evidence JSON, screenshots, raw artifacts) are private (`0600`). Runtime/profile/evidence directories are private (`0700`).

Do not loosen permissions to work around caller ownership problems.

## 12. Secrets

Never commit:

- SSH private keys;
- passwords/tokens/API keys;
- cookies/auth-state;
- production browser profiles;
- runtime DB/evidence containing sensitive material.

Provider credentials belong outside Git and are referenced by deployment configuration/contract paths.

## 13. Failure behavior

Security-sensitive uncertainty should fail closed:

- ambiguous process ownership -> no broad kill;
- invalid/expired/tampered provider claim -> reject before MCP;
- unsupported engine/profile combination -> reject;
- mixed/ambiguous C3 targets -> reject;
- C3 partial effects -> do not automatically replay;
- unavailable optional engine -> follow only the documented safe routing rule.

## 14. Accepted host boundary

Because launchd runs in a logged-in user session, a cold reboot/FileVault state may require manual login. This trades unattended cold-boot recovery for a simpler and safer user-session architecture. Changing that trade-off requires an explicit security decision.