# Architecture Decision Index

This is a compact index of durable decisions. Detailed evidence/rationale remains in the linked focused documents and dated closure records.

## D-001 — Browser execution lives on the Mac mini

**Decision:** Mac Browser Plane is the Browser runtime. VPS Worker/SignalForge keep Direct HTTP/API/ETL responsibilities. The old VPS Browser/Crawlee runtime direction is superseded.

**Why:** avoids duplicate browser state/profile/lifecycle stacks and keeps real browser execution close to the Mac host/user environment.

**Current boundary:** Mac direct Internet egress only.

## D-002 — One state authority and one Browser worker

**Decision:** SQLite JobStore + leases/process registry remain the runtime authority; only one active Runtime Worker executes jobs.

**Why:** prevents split ownership, profile races, duplicated effects, and inconsistent recovery.

## D-003 — Development checkout is not the production runtime

**Decision:** production launchd executes a separately installed non-editable runtime under `~/agent-browser-runtime/app/`.

**Why:** macOS TCC can block LaunchAgents under `~/Documents`; source edits should not mutate live production implicitly.

## D-004 — Local MCP is stdio-only

**Decision:** expose a thin `mac-browser-plane` MCP adapter over the existing runtime, with no HTTP/WebSocket listener and no second worker.

**Why:** gives AI callers a standard protocol without creating a new network attack surface or lifecycle authority.

Detailed history: `LOCAL_AGENT_MCP_ADAPTER_V0.md` and its live closure.

## D-005 — C3 is deterministic execution, not an embedded Browser Agent

**Decision:** C3 exposes a closed action/semantic-target surface. Planning/reasoning remains with the external caller.

**Why:** preserves testable deterministic execution and avoids embedding another LLM/planner/runtime inside Browser Plane.

## D-006 — C2 remains read-only Chrome diagnostics

**Decision:** C2 uses a dedicated Chrome diagnostic session and explicit CDP allowlist. No separate DevTools daemon and no `Runtime.evaluate`.

**Why:** satisfies current diagnostic needs with fewer services and a clearer mutation boundary.

## D-007 — Lightpanda is an internal ephemeral-C1 fast path

**Decision:** Lightpanda may be preferred for ephemeral C1 rendering and safely fall back to Chrome. It does not get a native exposed MCP/server/agent surface.

**Why:** gain a lightweight engine without duplicating the Browser Plane architecture.

Detailed contract: `LIGHTPANDA_ENGINE_ROUTING.md`.

## D-008 — Camoufox is selective, not AUTO

**Decision:** adopt upstream Camoufox capability as a short-lived internal engine for selected ephemeral C1/C3 work. Do not inherit `jo-inc/camofox-browser` server/runtime/MCP architecture. AUTO does not promote to Camoufox and no automatic cross-engine replay exists.

**Why:** anti-detection value is source-dependent, while automatic replay can duplicate side effects and generic 403-based routing is semantically unsafe.

Detailed contract: `CAMOUFOX_ENGINE_ROUTING.md`.

## D-009 — SignalForge remote production is Mac-initiated pull

**Decision:** Provider Agent polls Bangkok using a dedicated restricted SSH identity, validates a reviewed Provider Invocation Contract, then invokes local MCP stdio. The Mac exposes no inbound Browser/MCP/CDP service.

**Why:** enables unattended cross-host production while preserving the local Browser Plane security boundary and avoiding a public remote-control API.

Detailed evidence: `PIC-R4-PRODUCTION-CLOSURE-2026-09-08.md` and PIC contract documents.

## D-010 — No automatic Direct HTTP -> Browser fallback

**Decision:** acquisition policy/source registry determines whether Browser capability is authorized. A Direct HTTP failure alone does not authorize Browser execution.

**Why:** HTTP failure reasons include auth, rate limit, region policy, TLS/client behavior, WAF, and source changes; automatic escalation can be wrong or unsafe.

## D-011 — Historical closure evidence stays historical

**Decision:** dated closure documents record accepted state at a point in time and are not continuously rewritten. Current truth lives in `capabilities.json` + current-state docs.

**Why:** preserves auditability while preventing stale stage restrictions from being mistaken for the current system.