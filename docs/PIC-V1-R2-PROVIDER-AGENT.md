# PIC-v1 R2 Mac Provider Agent

**Date:** 2026-09-08  
**Status:** FEATURE IMPLEMENTATION / LOCAL TEST PASS

## Purpose

Add the thin Mac-side client for SignalForge Provider Invocation Contract v1.1 without creating a second Browser worker or any Mac network listener.

```text
restricted SSH claim from Bangkok
-> local contract revalidation
-> existing mac-browser-mcp stdio tool
-> existing Browser Plane JobStore / LaunchAgent worker
-> package result evidence
-> restricted SSH submit to Bangkok
```

## Capability mapping

```text
C0_FETCH        -> browser_fetch
C1_RENDER       -> browser_render
C2_INSPECT      -> browser_inspect
C3_BROWSER_USE  -> browser_use
```

The agent does not auto-escalate capabilities.

## Double validation

The Mac agent independently validates the locally installed provider authorization projection before MCP execution:

- provider/transport identity;
- ProviderRequest SHA-256;
- source policy version;
- source capability allowlist;
- target-role capability allowlist;
- HTTPS exact URL or host/path boundary;
- query/fragment policy;
- run/byte limits;
- current C0 hard limit of 1,000,000 bytes;
- C3 `READ_ONLY_NAVIGATION` and explicit `retry_safe`;
- C3 actions limited to the PIC subset that the real MCP supports.

PIC C3 subset for R2:

```text
snapshot
navigate
click
wait
type
select
press
screenshot
```

`scroll` is not exposed by the current MCP and therefore is not accepted. `download` exists in the local MCP but is deliberately outside PIC-v1.1 because provider-download artifact/side-effect semantics are not yet defined. Arbitrary JavaScript/shell/command execution is rejected.

## Evidence packaging

C0 already produces a raw strict-TLS response artifact. R2 verifies Browser Plane SHA/byte count and sends the raw bytes.

C1/C2/C3 do not currently expose a canonical rendered-DOM raw artifact. R2 therefore sends a canonical JSON evidence artifact containing the exact successful Browser Job identity/state/result returned by the existing MCP. It does not silently add DOM extraction or mutate Browser Plane execution semantics.

## SSH transport

`SshProviderTransport` executes `/usr/bin/ssh` as an argv array with no shell:

```text
-T
BatchMode=yes
ClearAllForwardings=yes
ConnectTimeout=<bounded>
[optional dedicated -i identity with IdentitiesOnly=yes]
<restricted host alias>
<one fixed provider command>
```

The actual dedicated key/user/authorized_keys forced-command installation remains a deployment Hard Stop and is not performed by R2 code.

## Verification

```text
.venv/bin/python -m pytest tests/test_provider_agent.py -q
11 passed

.venv/bin/python -m pytest -q
45 passed
```

No production runtime reinstall, LaunchAgent installation, credential creation, or provider enable flag occurs in this feature slice.
