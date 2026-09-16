# Browser Use Integration Gate — 2026-09-16

## Decision

**Do not integrate upstream `browser-use` into the Mac Browser Plane production runtime at this time. Keep D-005 unchanged.**

Upstream Browser Use 0.13.10 is technically compatible with the Plane's ownership model when it is treated as a subordinate CDP client: it can attach to the exact runtime-owned Chrome CDP endpoint, it does not need to launch or own a second Chrome, and it can operate while the existing Browser Plane Control Lease remains authoritative. Its incremental Python runtime overhead was bounded on this Mac mini.

However, the gate did **not** demonstrate a material execution capability that the existing deterministic C3 surface lacks. The current C3 path already handled the same asynchronously hydrated semantic target using `role` + accessible name, waited for visibility, clicked it, and returned an ARIA snapshot. Adding Browser Use would therefore add a second browser semantic/runtime layer and a large dependency graph without clearing the project's existing reopen condition for an embedded/extra Browser Agent layer.

This is an experimental result only. No production executor, MCP surface, capability manifest, routing rule, durable architecture decision, or production installation was changed.

## Scope and authoritative constraint

The current durable architecture decision remains:

- D-005: C3 is deterministic execution, not an embedded Browser Agent.
- Planning/reasoning remains with the external caller.
- Browser Plane remains authoritative for browser lifecycle, leases, process ownership, egress/routing, evidence, cancellation, and recovery.

The gate therefore tested upstream Browser Use only as a possible **subordinate semantic/CDP execution layer**, not as an autonomous planner and not as a replacement runtime.

## Test setup

Gate script:

```text
scripts/browser_use_integration_gate.py
```

Upstream package under test:

```text
browser-use 0.13.10
cdp-use 1.4.5
```

The script uses:

1. an isolated temporary Browser Plane home and SQLite database;
2. a loopback-only local HTTP fixture;
3. one runtime-owned headless Chrome launched with `--remote-debugging-port=0`;
4. the real `BrowserProcessRegistry` and `LeaseManager`;
5. a dynamic page that adds a semantically labelled button after 180 ms;
6. the current deterministic C3 implementation as the baseline;
7. upstream Browser Use attached to the existing CDP endpoint;
8. telemetry disabled before importing Browser Use.

Telemetry/logging environment for the Browser Use probe:

```text
ANONYMIZED_TELEMETRY=False
BROWSER_USE_TELEMETRY=false
BROWSER_USE_SETUP_LOGGING=false
BROWSER_USE_LOGGING_LEVEL=critical
```

No Browser Use Cloud, paid service, API key, LLM call, autonomous Agent, daemon, or external website was used.

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| G1 — reuse Plane-owned Chrome/CDP | **PASS** | Browser Use attached to the same loopback CDP port; HTTP discovery endpoint resolved to the same host/port WebSocket endpoint; debug Chrome root process delta was `0`; Plane-owned Chrome remained alive after `BrowserSession.stop()`; semantic target was exposed and clicked successfully. |
| G2 — preserve Plane lease authority | **PASS** | The gate acquired the real Browser Plane Control Lease before Browser Use attached; a competing owner for the same `browser_session_id` was denied on every run. Browser Use itself is not lease-aware, so this PASS is conditional on invoking it only *inside* the Plane-owned lease boundary. |
| G3 — bounded runtime overhead | **PASS, with dependency-cost warning** | Three repeated runs showed about 63.3–63.7 MiB Python RSS increase on Browser Use import plus 10.3–11.2 MiB for attach/state/action. No second Chrome root process appeared. This is acceptable on the current Mac mini as an occasional execution layer, but package/dependency cost is substantial. |
| G4 — material capability gain over deterministic C3 | **FAIL** | On the identical dynamic fixture, current C3 already waited for the semantic `role=button` + accessible name, clicked it, observed the activated state, and returned an ARIA snapshot. Browser Use succeeded too, but did not demonstrate a workload capability that current C3 could not perform. |

Overall promotion decision:

```text
G1 PASS
G2 PASS
G3 PASS (dependency warning)
G4 FAIL
------------------------------
PROMOTE TO PRODUCTION: NO
```

## Repeated measurements

Three clean repetitions produced the same gate outcome:

| Run | Import RSS | Attach/action RSS | Attach | DOM state | Click | Current C3 end-to-end | Chrome root delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 63.3 MiB | 11.2 MiB | 191 ms | 29 ms | 700 ms | 3764 ms | 0 |
| 2 | 63.7 MiB | 10.6 MiB | 197 ms | 13 ms | 700 ms | 3839 ms | 0 |
| 3 | 63.5 MiB | 10.3 MiB | 191 ms | 17 ms | 700 ms | 3825 ms | 0 |

The C3 number includes its complete managed Chrome lifecycle and is **not** a like-for-like microbenchmark against Browser Use attach time. It is included only to show that the existing production path completed the same functional workload. The gate does not claim Browser Use is faster or slower from these numbers.

A separate successful run resolved:

```text
Browser Plane CDP discovery: http://127.0.0.1:64445
Browser Use resolved CDP:    ws://127.0.0.1:64445/devtools/browser/...
```

The host/port identity proves Browser Use used the Plane-owned browser endpoint rather than starting another browser.

## Functional comparison

### Existing deterministic C3

The baseline used only the current public C3 action model:

```text
wait(role="button", name="Activate semantic target", state="visible")
click(role="button", name="Activate semantic target")
snapshot()
```

Observed:

```text
job_state = SUCCEEDED
engine = c3-browser-use
browser_engine = chrome
activated = true
aria_snapshot_present = true
```

### Upstream Browser Use

The upstream layer:

- attached to the already-running CDP endpoint;
- built its model-facing DOM state;
- exposed one interactive selector entry for the dynamic semantic button;
- mapped the selector to its CDP-backed node;
- clicked successfully;
- rebuilt state and observed `activated`;
- detached without killing the runtime-owned Chrome.

This confirms Browser Use's semantic DOM/grounding layer works with the Plane. It does **not** by itself justify adding the layer because the current C3 semantic surface already solved this test case.

## Lease boundary: important limitation

Browser Use does not know about Browser Plane leases. Compatibility comes from architecture, not from upstream enforcement:

```text
Caller / external planner
        |
        v
Browser Plane authorization + job state
        |
        v
Control Lease acquired  <--- authoritative boundary
        |
        v
(optional Browser Use subordinate client)
        |
        v
Plane-owned CDP endpoint
        |
        v
Plane-owned Chrome
```

Therefore the following would be **wrong** even though upstream Browser Use supports them:

- exposing Browser Use's native MCP server beside Mac Browser Plane;
- letting Browser Use launch its own persistent Chrome/profile;
- letting an autonomous Browser Use Agent bypass the JobStore/Control Lease;
- using Browser Use Cloud as an implicit alternate runtime;
- giving Browser Use a separate lifecycle/process authority.

If Browser Use is revisited, it must remain behind the existing job, lease, process-registry, and routing boundaries.

## Dependency and packaging cost

`browser-use==0.13.10` reports **61 direct requirement entries** in package metadata and pulls in multiple model/provider and support stacks, including `cdp-use`, `bubus`, `browser-harness`, `browser-use-sdk`, PostHog, OpenAI, Anthropic, Google GenAI/API packages, Groq, PDF/document tooling, and others.

Installing it into the development `.venv` also replaced several already-installed versions during the experiment, including:

```text
websockets      17.1   -> 15.0.1
typing-extensions 4.16.0 -> 4.15.0
requests         2.34.2 -> 2.33.0
click            8.5.0 -> 8.3.3
anyio            4.15.1 -> 4.12.1
rich             15.0.0 -> 14.3.3
```

`pip check` reported no broken requirements after installation and the Browser Plane regression suite remained green, so this did not create an observed functional regression. It is nevertheless a significant dependency-collision surface compared with keeping the production Plane dependency-light.

There is also a naming ambiguity: this project already exposes a deterministic capability named `browser_use`, while the upstream package/product is named Browser Use. Any future integration would need explicit names such as `browser_use_upstream_semantic` internally to prevent confusing the production C3 capability with the third-party framework.

### Development-environment cleanup

Because the adoption gate failed, the experiment did not leave Browser Use installed in the project development environment. After measurements, the explicitly introduced Browser Use packages and provider/support dependencies were removed, the six pre-existing package versions listed above were restored, and `google-genai` was removed after it exposed a transient `websockets<17` conflict with the Plane's restored `websockets==17.1`. Final cleanup verification returned:

```text
browser-use installed = no
pip check = No broken requirements found.
93/93 tests = PASS
browserctl doctor = READY
```

The production runtime under `~/agent-browser-runtime/app/` was never modified. The gate script remains as a reproducible experiment artifact; rerunning it requires an intentionally isolated environment with `browser-use==0.13.10` installed. Browser Use is deliberately **not** added to `pyproject.toml`.

## Validation

Gate command:

```bash
env \
  ANONYMIZED_TELEMETRY=False \
  BROWSER_USE_TELEMETRY=false \
  BROWSER_USE_SETUP_LOGGING=false \
  BROWSER_USE_LOGGING_LEVEL=critical \
  .venv/bin/python scripts/browser_use_integration_gate.py --json
```

Three repetitions returned:

```text
G1 PASS
G2 PASS
G3 PASS
G4 FAIL
```

Regression suite after Browser Use installation:

```text
python -m unittest discover -s tests -v
Ran 93 tests
OK
```

Dependency consistency:

```text
python -m pip check
No broken requirements found.
```

Runtime health:

```text
browserctl doctor
status = READY
sqlite_integrity = ok
stale_profile_leases = []
browser_process_ownership = []
```

The experiment did not leave Browser Plane lease/process ownership residue.

## Exploratory import observation

During early exploratory Codex subprocesses, an unconfigured `import browser_use` exited with code 134 in some shells. The failure was **not reproducible** after explicitly applying the gate environment shown above; repeated configured gate runs succeeded. Root cause is unknown and no causal claim is made. This is recorded as an integration-risk observation rather than a gate failure.

## Recommendation and reopen condition

Keep the present architecture:

```text
static/simple acquisition
        -> C0 / Lightpanda / current routing

deterministic browser interaction
        -> current C3 semantic action surface

reasoning/planning
        -> external caller

Browser Plane
        -> lifecycle + leases + process ownership + evidence + routing
```

Do **not** add upstream Browser Use to production `pyproject.toml`, MCP, routing, or the installed runtime based on this gate.

Reopen this decision only with a real workload corpus demonstrating repeated failures that current C3 cannot solve economically, for example where Browser Use's richer DOM grounding, iframe/target handling, stale-state recovery, or model-facing element indexing produces a meaningful success-rate gain. A future gate should compare success rate across those failed real workloads rather than use general framework feature breadth as justification.

If that reopen condition is met, the preferred next experiment is still a thin subordinate semantic adapter behind the existing Control Lease—not an embedded autonomous Browser Use Agent.
