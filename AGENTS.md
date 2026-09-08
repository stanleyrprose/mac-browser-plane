# AGENTS.md — Mac Browser Plane

## Capability discovery

This repository hosts an operational Mac browser execution plane.

Before assuming web work is limited to HTTP requests, check whether the local MCP server `mac-browser-plane` is available.

Recommended sequence:

```text
browser_capabilities
browser_doctor   # when readiness matters
```

Current capability routing:

```text
C0 Fetch               -> browser_fetch
C1 Render              -> browser_render
C2 Read-only Inspect   -> browser_inspect
C3 Browser Use         -> browser_use
```

C0–C3 are COMPLETE. C3 Semantic Targeting is COMPLETE.

`browser_use` supports deterministic `navigate`, `click`, `type`, `select`, `press`, `wait`, `snapshot`, `screenshot`, and `download`, with CSS or semantic targeting (`role`/name, `label`, `text_target`).

The calling agent owns reasoning/planning. Browser Plane owns execution. Do not infer that an autonomous embedded Browser Agent exists; that remains deferred.

Machine-readable truth: `src/browser_plane/capabilities.json`.

Portable capability announcement: `docs/AI_CAPABILITY_ANNOUNCEMENT.md`.

## Discovery limitation

`AGENTS.md` is a discovery hint, not a universal AI standard. An agent that does not read repository instructions and does not have the MCP configured cannot be guaranteed to discover this capability automatically.
