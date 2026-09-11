# Mac Browser Plane — AI Capability Announcement

**Status:** OPERATIONAL  
**Audience:** ChatGPT, Codex, OpenClaw, Hermes, MCP-capable agents, engineering agents, and future callers.

## Capability truth

Mac mini hosts an operational **Mac Browser Plane**.

```text
C0 Fetch               COMPLETE
C1 Render              COMPLETE
C2 Read-only Inspect   COMPLETE
C3 Browser Use         COMPLETE
C3 Semantic Targeting  COMPLETE
Artifact OCR           P0 COMPLETE (local-only)
```

The primary browser interaction tool is:

```text
browser_use
```

The local MCP server is:

```text
mac-browser-plane
transport = stdio
```

## What C3 can do

`browser_use` executes deterministic multi-step interaction through the existing Browser Plane JobStore, LaunchAgent worker, runtime-owned Chrome, and Playwright path.

Supported actions:

```text
navigate
click
type
select
press
wait
snapshot
screenshot
download
```

Targeting supports:

- CSS `selector`
- ARIA `role` with optional accessible `name`
- `label`
- visible `text_target`
- semantic `exact: true` where supported

`snapshot` provides bounded page text and bounded ARIA accessibility information so an external AI can inspect an unfamiliar UI before choosing the next action.

## Recommended discovery flow

An authorized agent that can see the MCP should:

```text
browser_capabilities
        ↓
browser_doctor          # when readiness matters
        ↓
select capability
        ↓
C0 -> browser_fetch
C1 -> browser_render
C2 -> browser_inspect
C3 -> browser_use
Artifact evidence OCR -> artifact_ocr
```

Do not assume a web task is limited to plain HTTP acquisition when `mac-browser-plane` is available.

## Architecture semantics

```text
AI / Agent
   ↓ reasoning + planning
mac-browser-plane MCP
   ↓ deterministic command
Browser Plane
   ↓
JobStore / LaunchAgent Worker / runtime-owned Chrome
```

Browser Plane is an **execution plane**, not an embedded autonomous planner.

The calling AI remains responsible for:

- understanding the user's goal;
- deciding whether C0/C1/C2/C3 is appropriate;
- interpreting snapshots/results;
- deciding the next action.

Browser Plane is responsible for controlled browser execution and evidence.

## Security boundary

Current Browser Plane intentionally keeps these boundaries:

- local MCP is stdio-only;
- no public MCP HTTP listener;
- no public CDP;
- no arbitrary JavaScript surface;
- no raw CDP surface through C3;
- no user's Personal Chrome profile;
- TLS verification remains enabled;
- autonomous embedded Browser Agent remains deferred.

## Known caller paths

When configured:

```text
Local Codex
  -> mac-browser-plane MCP stdio

OpenClaw
  -> mac-browser-plane MCP stdio

Hermes
  -> mac-browser-plane MCP stdio

Cloud ChatGPT
  -> authorized Mac access bridge (for example CodexPro)
  -> local mac-browser-plane MCP
```

Transport availability is caller-specific. Capability availability and transport availability are separate facts.

## Discovery guarantee

This project **cannot guarantee that every arbitrary AI agent automatically discovers the Browser Plane**.

Automatic discovery depends on whether the caller:

1. has access to this repository or receives its project instructions;
2. reads `README.md` or `AGENTS.md`;
3. supports MCP server/tool discovery;
4. has `mac-browser-plane` configured in its MCP/client environment; or
5. receives this announcement in its system/project context.

To maximize discovery, the same capability truth is published in:

```text
README.md
AGENTS.md
docs/AI_CAPABILITY_ANNOUNCEMENT.md
docs/IMPLEMENTATION_STATUS.md
src/browser_plane/capabilities.json
browser_capabilities MCP tool
MCP tool list / descriptions
```

The machine-readable manifest and live MCP response are authoritative for runtime capability discovery.
