# Contributing

This is currently a private operational repository. Contributions should optimize for production safety, traceability, and minimal scope rather than feature count.

## Workflow

1. Read `AGENTS.md`, `README.md`, `docs/PROJECT_STATUS.md`, and the affected focused contract/doc.
2. Create a focused branch (`feat/...`, `fix/...`, or `docs/...`).
3. Make the smallest sufficient change.
4. Add the minimal stable regression test for a behavior change or real bug.
5. Update `src/browser_plane/capabilities.json` and current docs when the public contract changes.
6. Run relevant local verification.
7. Commit atomically and open a PR.
8. Require CI PASS for production-affecting changes.
9. Merge before reinstalling the production runtime.
10. Perform proportionate live verification and record closure evidence only for meaningful production milestones.

## Standard verification

```bash
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/browserctl doctor
```

Use the 1000-job soak only when worker/state/lease/process/recovery/concurrency changes justify it.

## Scope rules

Avoid in unrelated changes:

- speculative services/daemons;
- new state stores;
- unrelated refactors;
- broad test/coverage expansion;
- regional egress infrastructure without a real source need;
- autonomous Browser Agent work unless explicitly authorized;
- native Lightpanda/Camoufox MCP/server exposure.

## Security rules

Never commit credentials, SSH private keys, tokens, cookies, auth-state, production profiles, runtime databases, or sensitive evidence.

Do not expose public Browser/MCP/CDP ports, arbitrary JavaScript, or raw CDP as an incidental implementation shortcut.

## Documentation rules

Use `docs/README.md` for document authority. Keep current docs current, and keep dated closure evidence historical. Do not duplicate one durable rule into many files when a pointer is sufficient.

## PR description

A useful PR should state:

- problem/goal;
- scope and explicit non-scope;
- affected capability/security boundary;
- tests run;
- live verification required or not;
- rollback implication if production behavior changes.