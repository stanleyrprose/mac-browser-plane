# PIC-v1 R2 Mac Provider Agent — 2026-09-08

**Status:** IMPLEMENTED ON FEATURE BRANCH / CI GATE PENDING

## Scope

R2 adds the unattended Mac-side executor for the SignalForge Provider Invocation Contract without adding any public Browser/MCP/CDP listener.

Execution path:

```text
Bangkok provider queue
  -> restricted SSH dispatcher claim
  -> Mac Provider Agent
  -> local request/source/URL/C3 validation
  -> mac-browser-mcp stdio
  -> C0/C1/C2/C3 Browser job
  -> completion/failure acknowledgement
```

## Implemented boundaries

- provider identity pinned to `mac-mm-01`;
- C0/C1/C2/C3 capability-to-MCP mapping is fixed in code;
- request SHA-256 and claim/request correlation revalidated on Mac;
- request + claim expiry checked before execution;
- source policy and target-role capability checked again on Mac;
- HTTPS authority / exact target / host+path policy checked again on Mac;
- C3 remains deterministic `READ_ONLY_NAVIGATION`, not an autonomous browser agent;
- C3 request actions are limited to the subset implemented by the local runtime contract;
- arbitrary shell / JavaScript / command fields rejected;
- browser profile fixed to `public-research` + ephemeral for unattended rendered/interactive work;
- SSH destination is operator configuration, never request-controlled;
- remote dispatcher verb is an internal fixed allowlist;
- local execution continues through `mac-browser-mcp` stdio via the existing MCP client.

## CLI

```text
mac-browser-provider-agent --contract <local-contract.json> --ssh-host <configured-host> --once
mac-browser-provider-agent --contract <local-contract.json> --ssh-host <configured-host> --interval-sec 5
```

The live production contract file and dedicated least-privilege SSH identity are intentionally not installed by this code slice.

## Verification

```text
.venv/bin/python -m pytest tests/test_provider_agent.py tests/test_mcp_call.py -q
# 9 passed

.venv/bin/python -m pytest -q
# 39 passed
```

## Remaining before R3

SignalForge R1B currently accepts completion metadata/hash only. R3 requires the submit/evidence boundary to carry and validate the result envelope/artifact integrity before BKK-origin C0+C1+C2+C3 can be declared end-to-end PASS.

Dedicated Mac->Bangkok least-privilege SSH identity/forced-command installation remains a host-level Hard Stop under the approved PRD.
