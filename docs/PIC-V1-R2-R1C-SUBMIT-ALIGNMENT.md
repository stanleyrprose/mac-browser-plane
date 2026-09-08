# PIC-v1 R2 — R1C Submit Alignment

**Date:** 2026-09-08  
**Status:** FEATURE IMPLEMENTATION / LOCAL TEST PASS

This follow-up aligns the already-merged Mac Provider Agent (`f3af4c3...`) with the Bangkok R1C/R1D protocol.

Changes:

- remote completion now uses `provider-submit-v1` binary framing instead of metadata-only `provider-complete-v1`;
- C0 submits the exact Browser Plane raw response artifact after local SHA/byte verification;
- C1/C2/C3 submit canonical JSON Browser Job evidence because the current runtime does not expose a canonical rendered-DOM artifact for these modes;
- Mac independently validates the request's hashed final-URL policy and the actual Browser result final URL;
- `APPROVED_HOST_PATH` permits bounded same-issuer navigation; default remains `EXACT_REQUESTED`;
- C3 PIC action subset is aligned with the real MCP: `press` is allowed, `scroll` is not; `download` remains outside PIC-v1.1;
- C3 requires explicit boolean `retry_safe`;
- target byte/run limits and the current C0 1,000,000-byte runtime limit are enforced locally;
- SSH transport uses argv-only `/usr/bin/ssh -T`, `BatchMode=yes`, `ClearAllForwardings=yes`, and optional dedicated `IdentityFile`/`IdentitiesOnly=yes`;
- no shell, public listener, second Browser worker, credential creation or provider production enablement is introduced.

Verification:

```text
.venv/bin/python -m pytest tests/test_provider_agent.py -q
8 passed

.venv/bin/python -m pytest -q
42 passed
```
