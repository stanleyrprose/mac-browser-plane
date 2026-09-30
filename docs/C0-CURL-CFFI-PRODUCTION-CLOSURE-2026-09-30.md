# C0 curl_cffi Production Closure — 2026-09-30

## Scope

Close production rollout of the bounded C0 browser-impersonated HTTP fallback introduced by PR #58.

The accepted routing remains:

```text
browser_fetch
  -> system /usr/bin/curl
  -> one bounded curl_cffi Chrome-impersonated retry only on:
       - explicit supported anti-bot challenge evidence, or
       - selected TLS/HTTP-client compatibility curl errors
```

This does not authorize C1/C2/C3, proxy/egress changes, JavaScript execution, CAPTCHA solving, or a Provider contract expansion.

## Reviewed revision and CI

- PR: `#58` — `feat: add bounded curl_cffi C0 fallback`
- merged revision: `28c41998dddd449da7bc47a9a62666d6b5252b96`
- pre-merge push CI: `36683062312` — PASS
- pre-merge pull-request CI: `36683068898` — PASS
- post-merge main CI: `36683202339` — PASS
- local targeted C0 regression before merge: **8/8 PASS**
- local full repository regression before merge: **111/111 PASS**
- compileall: PASS

GitHub CI included the repository C0 mini soak.

## Production deployment

Before replacement:

- production Doctor: `READY`
- previous source revision: `1d3e066c4c30d590b073de20218738543862e0ba`
- `curl_cffi`: not installed in the production venv
- SQLite backup created:
  `~/agent-browser-runtime/backups/runtime-20260930T072207514467Z.db`
- backup integrity: `ok`

Deployment used the existing reviewed path:

```text
scripts/install_runtime.py
scripts/install_launchd.py
browserctl doctor
```

After deployment:

- production source revision: `28c41998dddd449da7bc47a9a62666d6b5252b96`
- installed `curl_cffi`: `0.16.3`
- `c0_impersonated_fetch=true`
- C0 rule: `c0_transport_router`
- Doctor: `READY`
- `curl_cffi_c0b`: ready
- stale profile leases: none
- Browser Process Registry ownership residue: none

## Production live verification

A bounded loopback fixture was used only through the local operator CLI. It returned a normal 200 for the direct case and returned an explicit Cloudflare-style challenge only to the Browser Plane system-curl User-Agent.

### Direct case

Job: `b3e8982a-5f85-4eb2-ac0e-0f267c1c0f89`

Observed:

```text
state=SUCCEEDED
status=200
transport=system_curl
fallback_attempted=false
body=direct-path-ok
```

### Challenge case

Job: `6bf829e5-0079-4445-86fc-2957cd1cdada`

Observed:

```text
direct_status=403
trigger=cloudflare_challenge
fallback_attempted=true
selected=curl_cffi
status=200
state=SUCCEEDED
body=impersonated-path-ok
```

This proves the production runtime keeps the cheap direct path by default and selects the impersonated transport only when the bounded trigger is present.

## Rollback

No database schema migration or Provider contract change was introduced.

If rollback is required:

1. reinstall the previous reviewed revision `1d3e066c4c30d590b073de20218738543862e0ba` using the same runtime installer;
2. reinstall/restart the Browser Plane LaunchAgent;
3. run `browserctl doctor`;
4. the pre-deployment SQLite backup above is available if state restoration is independently required.

Normal code rollback does not require restoring the database because this change did not alter the schema.

## Closure

Production state: **VERIFIED / CLOSED**.

The integration is intentionally limited to C0 transport selection. Any future expansion to generic WAF routing, proxy rotation, regional egress, JavaScript challenge handling, or automatic Browser escalation requires separate source evidence and a new reviewed decision.
