# Development Guide

## 1. Engineering principles

Mac Browser Plane follows a minimal-sufficient architecture:

- one Browser execution runtime;
- one SQLite state authority;
- one Runtime Worker;
- thin invocation adapters;
- engine implementations hidden behind the existing runtime;
- no new daemon/service/database unless a concrete requirement cannot be met by the current plane.

Scope is intentionally controlled. A new engine is not a new capability layer; a new caller is not automatically a new network API.

## 2. Repository layout

```text
src/browser_plane/     runtime, CLI, MCP adapter, provider agent, engine adapters
scripts/               install/soak/runtime helper scripts
launchd/               LaunchAgent templates
tests/                 unit/integration/regression tests
examples/              small job fixtures
docs/                  current docs + historical closure evidence
.github/workflows/     CI
pyproject.toml          package/dependency/entry-point metadata
AGENTS.md               agent capability-discovery instructions
```

Generated/cache/runtime content must not become project source. `.venv`, `__pycache__`, pytest cache, runtime DB/evidence, browser profiles, credentials, and provider private keys are not source artifacts.

## 3. Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser,antidetect,agent,dev]'
.venv/bin/browserctl init
.venv/bin/browserctl doctor
```

Chrome is the authoritative persistent/C2/ordinary-C3 browser. Lightpanda and Camoufox are optional engine dependencies with narrower routing rules.

## 4. Change workflow

Preferred workflow:

1. inspect `AGENTS.md`, current status/docs, affected code/tests;
2. create a focused feature/fix/docs branch;
3. implement the smallest sufficient change;
4. add/update the minimal stable regression test for real bugs/contract changes;
5. run tests for the affected path plus the normal suite when appropriate;
6. update `capabilities.json` and current docs in the same change when public capability/routing truth changes;
7. commit atomically and open a PR;
8. require CI PASS before merging production-affecting changes;
9. reinstall the production runtime only after merged/reviewed source is selected;
10. run live verification proportionate to the risk and record a closure document only for meaningful production milestones.

## 5. Public contract changes

Treat these as public-contract changes:

- adding/removing an MCP tool;
- changing C0–C3 semantics;
- changing supported C3 actions/targeting;
- changing remote provider invocation mode;
- changing engine AUTO routing/fallback semantics;
- exposing a network listener;
- changing profile/evidence/security boundaries.

A public-contract change should update at least:

- code/tests;
- `src/browser_plane/capabilities.json`;
- root `README.md`;
- affected current architecture/security/runbook documentation.

## 6. Engine changes

Do not bypass Browser Plane to expose an engine-native service.

### Lightpanda

Keep it an internal ephemeral-C1 fast path unless a separately approved design changes that boundary. Fallback must remain side-effect-safe.

### Camoufox

Keep selection explicit/source-evidence based. Never introduce a generic HTTP-status trigger. No automatic cross-engine replay for C3.

### Chrome

Maintain loopback/dynamic CDP and runtime-owned profile/process semantics.

## 7. MCP changes

The MCP adapter is a protocol surface, not an execution runtime. It must continue to use the existing JobStore/worker. Do not create a second worker or duplicate browser lifecycle ownership inside the adapter.

Do not add arbitrary JavaScript, raw CDP, arbitrary Playwright object access, or public HTTP/WebSocket transport without an explicit architecture/security decision.

## 8. Provider Agent changes

Provider work must preserve:

- pull-only network direction from the Mac;
- dedicated restricted SSH identity;
- reviewed source/capability/URL contract;
- local MCP stdio invocation;
- no administrative-key substitution;
- no inbound Browser/MCP/CDP listener;
- truthful evidence/error classification.

The SignalForge Provider contract is cross-repository authority for what that caller is allowed to request. Browser Plane must not silently broaden it.

## 9. Documentation changes

Use `docs/README.md` to determine the canonical home of a fact.

- current-state docs are maintained continuously;
- dated closure documents are historical evidence and normally immutable;
- one rule/fact should have one canonical home, with other files linking to it;
- avoid copying long, drifting capability tables across many files.

## 10. Dependency policy

Add a dependency only when it solves a current requirement with clear value. Pin or constrain dependencies when upstream compatibility materially affects runtime behavior (as with MCP/Camoufox/Playwright).

Do not add infrastructure for hypothetical future scale.

## 11. Security during development

Never commit:

- SSH private keys;
- tokens/passwords/cookies;
- production profile/auth state;
- runtime databases/evidence containing sensitive data;
- provider secrets.

Use isolated `BROWSER_PLANE_HOME` for tests that should not touch production state.