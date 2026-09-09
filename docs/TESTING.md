# Testing Strategy

## 1. Objective

Testing protects the Browser Plane invariants most likely to cause data loss, duplicated browser effects, profile corruption, unsafe process termination, or misleading evidence.

The project follows minimal-sufficient testing: test affected paths deeply enough to protect the contract, but do not grow broad suites merely for coverage percentage.

## 2. Standard local verification

```bash
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/browserctl doctor
```

Latest local verification on **2026-09-09**: **56/56 tests PASS** and `browserctl doctor = READY`.

## 3. CI

GitHub Actions workflow: `.github/workflows/ci.yml`.

Current CI runs on `macos-14` with Python 3.12 and performs:

1. checkout;
2. install `.[browser,agent,dev]`;
3. Python compile check;
4. full unittest discovery;
5. 100-job C0 mini soak with four submitters.

CI intentionally does not require optional Camoufox browser assets or a production SignalForge/SSH environment.

## 4. What the suite protects

Current regression coverage includes:

- capability manifest boundary;
- SQLite WAL/FULL/busy-timeout and CAS transitions;
- idempotent submit/cancel;
- online backup consistency/restore;
- C0 curl/raw-artifact behavior;
- engine routing and fallback rules;
- C2 mutating-CDP denial;
- C3 action/semantic target validation and evidence;
- Profile/Control Lease exclusivity;
- process ownership verification and safe termination;
- startup recovery and worker lock exclusivity;
- MCP bounded tool surface and real stdio subprocess handshake;
- provider package/validation/polling behavior;
- provider restricted SSH argv/shell boundary;
- provider LaunchAgent pull-only contract.

## 5. Soak testing

Full lifecycle soak:

```bash
.venv/bin/python scripts/soak_m1.py --jobs 1000 --browser-jobs 5 --submitters 8
```

Run the full soak when changes touch:

- worker lifecycle/locking;
- SQLite concurrency/state transitions;
- lease semantics;
- process registry/recovery;
- high-volume queue behavior;
- installation changes that could alter the running worker.

Do not require a 1000-job soak for documentation-only or narrowly isolated pure-validation changes.

## 6. Real-browser live verification

Use live browser tests when changes touch rendering, interaction, engine adapters, evidence capture, cancellation, or production installation.

A live acceptance should verify only the impacted behavior plus residue:

- expected job result/status;
- selected engine/fallback evidence where relevant;
- screenshot/download/raw artifact when relevant;
- `browserctl doctor = READY` after the run;
- no stale profile leases;
- no Browser Process Registry residue.

## 7. Regression rule for bugs

For a real production/reproducible bug:

1. identify the smallest stable reproduction;
2. add one regression test for the failure mechanism;
3. fix the implementation;
4. run affected tests plus the normal suite;
5. add live verification only if the bug depends on real browser/OS/site behavior.

Avoid unrelated refactors or test expansion in the same fix.

## 8. Cross-engine safety tests

Any routing/fallback change must prove:

- side-effect safety before automatic replay;
- Camoufox is not promoted by generic status codes;
- AUTO does not silently change C3 to another engine;
- persistent profiles do not route to unsupported engines;
- failures preserve truthful `partial_effect_possible` semantics.

## 9. Provider tests

Provider changes should separately test:

- claim/contract validation before MCP execution;
- capability-to-tool mapping;
- bounded evidence packaging;
- expired/tampered/unauthorized claims fail closed;
- no shell invocation through SSH transport;
- idle/backlog polling behavior;
- local MCP failure classification;
- launchd remains pull-only.

Live Bangkok/Mac end-to-end verification is a production acceptance step, not a default unit-test prerequisite.