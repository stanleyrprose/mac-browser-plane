# C3 Browser Failure Corpus

## Purpose

The C3 Browser Failure Corpus records **real deterministic C3 action failures** so future engine or semantic-layer decisions are based on observed gaps rather than feature lists.

It does not add an autonomous Browser Agent and does not change C3 action semantics, routing, leases, lifecycle ownership, or retry behavior.

## Runtime location

The corpus is local to the Browser Plane runtime:

```text
$BROWSER_PLANE_HOME/state/c3-failure-corpus.jsonl
```

The file is append-only JSONL and is created with mode `0600`. The runtime `state/` directory remains `0700`.

The corpus is runtime evidence and must not be committed to this public repository.

## What is captured

A record is written only when a valid C3 action reaches execution and raises a non-`CapabilityError` exception.

Each record contains:

- schema version and unique `failure_id`;
- timestamp and Browser Plane `job_id`;
- actual browser engine (`chrome` or `camoufox`);
- action step and sanitized action shape;
- observed failure class;
- exception type and bounded message;
- page host, credential/query/fragment-free URL, and bounded title;
- profile/profile-mode metadata when the job spec is available;
- bounded page text and ARIA context only for the ephemeral `public-research` profile.

The recorder intentionally does **not** persist typed input text or selected values. URL query strings and fragments are removed.

For authenticated/persistent profiles, page content is not captured; records are metadata-only.

Failure capture is best-effort. A recorder error must never replace or hide the original C3 execution error.

## Observed failure classes

Classification is intentionally conservative and based only on the exception observed at execution time:

- `ACTION_TIMEOUT`
- `TARGET_AMBIGUOUS`
- `FRAME_DETACHED`
- `DETACHED_OR_STALE`
- `DOWNLOAD_FAILED`
- `NAVIGATION_FAILED`
- `ACTION_ERROR`

These are observations, not root-cause claims. For example, the corpus must not label a failure as OOPIF/SPA/rerender-related unless later evidence establishes that cause.

## Operator commands

Summary:

```bash
browserctl corpus summary
```

Recent records:

```bash
browserctl corpus list --limit 20
```

The summary reports total failures plus counts by observed failure class, action kind, and host.

## Promotion workflow

The corpus exists to answer one question: **does another execution layer solve real C3 failures that current deterministic C3 cannot?**

Do not promote Browser Use, nodriver, Vision/Computer Use, or another Browser Agent merely because it has broader features.

After approximately 5–10 real, reproducible C3 failures have accumulated:

1. verify that each case represents an actual task failure rather than an invalid action specification;
2. confirm manually whether the task can be completed in a browser;
3. create a sanitized/reproducible fixture where practical;
4. replay the same cases against current C3 and candidate alternatives;
5. compare task success, recovery quality, runtime/resource cost, and security/lifecycle fit;
6. only then revisit the integration gate.

No production fallback is added by this corpus. C3 remains deterministic and fail-closed.

## Current boundary

This first version deliberately does not add automatic replay, cloud upload, screenshots-on-failure, DOM dumps, LLM labeling, or automatic Browser Agent fallback. Those would increase privacy, dependency, and failure-surface costs before the corpus demonstrates a need for them.
