# Interface Reference

This document is the current caller-facing reference for Mac Browser Plane. The machine-readable capability boundary remains `src/browser_plane/capabilities.json`; exact executable behavior is defined by the current source.

## 1. Public invocation surfaces

Mac Browser Plane has two direct local interfaces:

1. `browserctl` CLI — operator/developer/job-lifecycle interface;
2. `mac-browser-plane` MCP over stdio — bounded AI/agent interface.

SignalForge production uses a separate Provider Agent. That Provider validates a reviewed cross-repository contract and then calls the local MCP; it is **not** a second public API and can be narrower than the local MCP.

## 2. MCP transport

Server executable:

```text
mac-browser-mcp
```

Production path:

```text
~/agent-browser-runtime/app/venv/bin/mac-browser-mcp
```

Transport:

```text
stdio only
```

There is no HTTP/WebSocket MCP listener.

## 3. MCP tools

Current surface: exactly **9 tools**.

### `browser_capabilities`

Arguments: none.

Returns the machine-readable capability/security/engine-routing manifest.

### `browser_doctor`

Arguments: none.

Runs readiness checks and returns the report plus the private report path. It does not start a second worker.

### `browser_fetch`

C0 strict-TLS HTTP(S) acquisition.

Arguments:

| Field | Type | Default | Bounds / meaning |
| --- | --- | --- | --- |
| `url` | string | required | absolute public `http://` or `https://` URL |
| `queue_timeout_sec` | int | 60 | 1–600 |
| `max_run_sec` | int | 60 | 1–600 |
| `client_timeout_sec` | int | 90 | 1–900 |

Evidence policy: always preserve C0 evidence/raw response according to runtime rules.

### `browser_render`

C1 JS/DOM render. This surface does not click or type.

| Field | Type | Default | Bounds / meaning |
| --- | --- | --- | --- |
| `url` | string | required | absolute public HTTP(S) URL |
| `profile` | string | `public-research` | one of the allowed runtime profiles |
| `profile_mode` | string | `ephemeral` | `ephemeral` or `exclusive-persistent` |
| `queue_timeout_sec` | int | 60 | 1–600 |
| `max_run_sec` | int | 120 | 1–600 |
| `client_timeout_sec` | int | 180 | 1–900 |

Engine routing is internal. Ephemeral AUTO C1 may use Lightpanda then safe Chrome fallback; persistent C1 uses Chrome.

When C1 executes with Chrome, the final rendered DOM is persisted as a private `rendered.html` evidence artifact when its UTF-8 size is at most 10 MB. The result includes `artifact_path`, `body_bytes`, `content_type`, and `sha256`. If the DOM exceeds that bound, C1 keeps its existing success semantics, omits the artifact, and returns `artifact_omitted_reason=RENDERED_HTML_EXCEEDS_10MB_LIMIT`. Callers must treat `artifact_path` as a local/private runtime path rather than a public download URL.

### `browser_inspect`

C2 read-only Chrome diagnostics.

| Field | Type | Default | Bounds / meaning |
| --- | --- | --- | --- |
| `url` | string | required | absolute public HTTP(S) URL |
| `profile` | string | `public-research` | allowed runtime profile |
| `queue_timeout_sec` | int | 60 | 1–600 |
| `max_run_sec` | int | 120 | 1–600 |
| `client_timeout_sec` | int | 180 | 1–900 |

Profile mode is forced to ephemeral. C2 exposes no arbitrary JavaScript and no raw/mutating CDP.

### `browser_use`

C3 deterministic multi-step Browser Use.

| Field | Type | Default | Bounds / meaning |
| --- | --- | --- | --- |
| `url` | string | required | initial absolute public HTTP(S) URL |
| `actions` | array<object> | required | non-empty, maximum 50 steps |
| `profile` | string | `public-research` | allowed runtime profile |
| `profile_mode` | string | `ephemeral` | `ephemeral` or `exclusive-persistent` |
| `queue_timeout_sec` | int | 60 | 1–600 |
| `max_run_sec` | int | 180 | 1–600 |
| `client_timeout_sec` | int | 240 | 1–900 |

Every action gets `timeout_ms=10000` by default and must stay within **1–60000 ms**.

Current ordinary AUTO C3 uses Chrome. Selective Camoufox routing is an internal/source-evidence mechanism; the public MCP caller does not choose an engine.

### `browser_status`

Arguments:

```text
job_id: string
```

Returns the public lifecycle record for one job.

### `browser_result`

Arguments:

```text
job_id: string
```

Returns stored result/failure information for one job.

### `browser_cancel`

Arguments:

```text
job_id: string
```

Requests cancellation and returns whether cancellation was accepted plus the resulting state.

## 4. MCP URL guard

Agent-facing URLs must:

- be absolute `http://` or `https://` URLs;
- contain a hostname;
- not use `localhost`, `*.localhost`, or `*.local`;
- not use an obvious literal non-global IP address.

Important implementation boundary: the current guard validates the supplied hostname/literal address; it is not a general-purpose DNS/network sandbox. Do not treat it as authorization to reach arbitrary internal resources. Remote Provider authorization remains separately source/URL/capability constrained.

## 5. Allowed MCP profiles

```text
public-research
authenticated-work
development
```

Allowed MCP profile modes:

```text
ephemeral
exclusive-persistent
```

Personal Chrome profile use is forbidden.

## 6. C3 action reference

### Targeting rule

Targeted actions must use **exactly one** target form:

```text
selector
role
label
text_target
```

Target/name strings are limited to 2000 characters.

`role` may include optional accessible `name`.

`exact: true|false` is allowed only with semantic targeting (`role`, `label`, `text_target`), not CSS `selector`.

### `navigate`

```json
{
  "action": "navigate",
  "url": "https://example.com",
  "wait_until": "domcontentloaded",
  "timeout_ms": 10000
}
```

`wait_until` values:

```text
commit
domcontentloaded
load
networkidle
```

### `click`

Requires one target form.

```json
{
  "action": "click",
  "role": "link",
  "name": "Learn more",
  "exact": true,
  "timeout_ms": 10000
}
```

Optional `force: true` exists only as a deliberate escape hatch for known interception/hidden-control cases; normal interaction remains the default.

### `type`

Requires one target form and `text`.

```json
{
  "action": "type",
  "label": "Search",
  "text": "tender",
  "timeout_ms": 10000
}
```

`text` is limited to 100,000 characters.

### `select`

Requires one target form and `value`.

```json
{
  "action": "select",
  "selector": "select[name=category]",
  "value": "legal",
  "force": false,
  "timeout_ms": 10000
}
```

Optional `force` follows the same deliberate escape-hatch rule as click.

### `press`

Requires `key`; target is optional.

Targeted:

```json
{
  "action": "press",
  "label": "Search",
  "key": "Enter"
}
```

Untargeted press operates through the executor's current page-level behavior.

### `wait`

Two forms exist.

Time wait:

```json
{
  "action": "wait",
  "ms": 1000
}
```

`ms` range: **0–30000**, default 1000.

Target-state wait:

```json
{
  "action": "wait",
  "text_target": "Results",
  "state": "visible"
}
```

Allowed states:

```text
attached
detached
visible
hidden
```

### `snapshot`

```json
{
  "action": "snapshot"
}
```

Returns bounded page information including the current bounded body-text excerpt and bounded ARIA snapshot according to runtime limits.

### `screenshot`

```json
{
  "action": "screenshot"
}
```

Screenshot data is persisted in the private evidence tree rather than becoming an unrestricted browser filesystem interface.

### `download`

Requires one target form.

```json
{
  "action": "download",
  "text_target": "Download PDF"
}
```

Downloaded artifacts remain under Browser Plane evidence ownership.

## 7. Common MCP job response

Execution tools return a public job record shaped like:

```json
{
  "job_id": "...",
  "state": "SUCCEEDED",
  "created_at": "...",
  "started_at": "...",
  "finished_at": "...",
  "failure_class": null,
  "partial_effect_possible": false,
  "result": {}
}
```

If the local client timeout expires before the job reaches a terminal state, the response also includes:

```text
status = JOB_STILL_PENDING
```

A caller can then use `browser_status`, `browser_result`, or `browser_cancel`.

## 8. Job lifecycle states

Current model states include:

```text
QUEUED
WAITING_RESOURCE
RUNNING
PAUSED_FOR_INSPECTION
WAITING_HUMAN
RECOVERY_REQUIRED
CANCEL_REQUESTED
SUCCEEDED
FAILED
CANCELLED
QUEUE_TIMEOUT
EXECUTION_TIMEOUT
STALLED_HUMAN_TIMEOUT
```

Current normal C0–C3 operation does not imply that every model state is actively used by every capability.

## 9. CLI reference

General command:

```bash
browserctl <command>
```

### Initialize

```bash
browserctl init
```

Creates/ensures runtime directories and initializes SQLite state.

### Submit a job

```bash
browserctl submit --file job.json
browserctl submit --stdin
```

Exactly one of `--file` or `--stdin` is required.

### Run synchronously

```bash
browserctl run --file job.json
browserctl run --stdin
browserctl run --file job.json --client-timeout 300
```

`run` submits the job and, if no production worker owns the worker lock, can acquire the same worker lock and execute work locally. It never creates a second concurrent worker.

### Job lifecycle

```bash
browserctl status <job-id>
browserctl result <job-id>
browserctl wait <job-id> --timeout 300 --poll 0.2
browserctl cancel <job-id>
```

### Worker

```bash
browserctl worker
browserctl worker --once
browserctl worker --idle-sleep 0.25 --max-jobs 0
```

`--max-jobs 0` means run until interrupted. A second worker fails with `WORKER_ALREADY_RUNNING`.

### Doctor

```bash
browserctl doctor
```

Exit status is success only when report status is `READY`.

### Backup

```bash
browserctl backup
browserctl backup --output /path/to/runtime-backup.db
```

Uses SQLite backup semantics and integrity checking.

### Capabilities

```bash
browserctl capabilities
```

Prints `capabilities.json`.

## 10. CLI JobSpec

`browserctl submit/run` consumes a JSON JobSpec. Minimal examples live under `examples/`.

Core fields currently parsed by the model:

| Field | Default |
| --- | --- |
| `task_type` | `fetch` |
| `url` | required |
| `engine` | `auto` |
| `egress` | `auto` |
| `profile` | `public-research` |
| `profile_mode` | `ephemeral` |
| `queue_timeout_sec` | 300 |
| `max_run_sec` | 120 |
| `human_hold_sec` | 600 |
| `evidence_policy` | `on_failure` |
| `control_mode` | `normal` |
| `retry_policy` | `none` |
| `allow_egress_fallback` | false |
| `idempotency_key` | null |
| `actions` | `[]` |

Operator warning: the model enum contains future/deferred values as well as currently authorized ones. Parsing a value does **not** mean the runtime authorizes it. For example, current execution preflight accepts only `auto`/`direct` egress and rejects autonomous `task_type=agent`; consult `capabilities.json` before constructing direct CLI jobs.

## 11. Local vs Provider authority

Do not assume the SignalForge Provider can use every local MCP operation/action.

```text
local MCP capability
!= automatically authorized remote Provider capability
```

Provider requests must additionally satisfy the reviewed Provider Invocation Contract. That contract is the remote source/capability/URL authorization boundary.
