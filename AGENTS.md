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
Artifact OCR           -> artifact_ocr
```

C0–C3 are COMPLETE. C3 Semantic Targeting is COMPLETE. `artifact_ocr` is an orthogonal local artifact-processing capability, not C4: P0 accepts only runtime-owned PNG/JPEG evidence, runs fixed Burmese+English OCR without network access, and returns evidence enrichment that must be source-cross-checked before critical business fields are trusted. It is not enabled in the SignalForge remote Provider contract.

Internal engine routing is transparent to callers: C0 uses system `curl`; ephemeral C1 prefers Lightpanda when installed and safely falls back to Chrome; persistent-profile C1, all C2 diagnostics, and ordinary AUTO C3 Browser Use remain Chrome. Camoufox is the fourth optional anti-detection engine for selective ephemeral C1/C3 jobs only; AUTO never promotes to Camoufox without explicit/source evidence, and Camoufox has no automatic cross-engine replay fallback. Do not bypass `mac-browser-plane` to call Lightpanda or Camoufox MCP/server surfaces directly. Machine-readable routing truth is in `src/browser_plane/capabilities.json`; rationale is in `docs/LIGHTPANDA_ENGINE_ROUTING.md` and `docs/CAMOUFOX_ENGINE_ROUTING.md`.

`browser_use` supports deterministic `navigate`, `click`, `type`, `select`, `press`, `wait`, `snapshot`, `screenshot`, and `download`, with CSS or semantic targeting (`role`/name, `label`, `text_target`).

The calling agent owns reasoning/planning. Browser Plane owns execution. Do not infer that an autonomous embedded Browser Agent exists; that remains deferred.

Machine-readable truth: `src/browser_plane/capabilities.json`.

Portable capability announcement: `docs/AI_CAPABILITY_ANNOUNCEMENT.md`.

## Discovery limitation

`AGENTS.md` is a discovery hint, not a universal AI standard. An agent that does not read repository instructions and does not have the MCP configured cannot be guaranteed to discover this capability automatically.
