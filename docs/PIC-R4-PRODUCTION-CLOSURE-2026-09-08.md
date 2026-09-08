# PIC v1 R4 Mac Provider Production Closure — 2026-09-08

## Decision

**Mac Browser Plane PIC v1 R4 remote Provider production = COMPLETE / PASS.**

The production path is pull-only. The Mac receives no inbound Browser/MCP/CDP production connection.

## Final runtime boundary

```text
Bangkok durable ProviderRequest
  <- outbound restricted SSH pull from Mac Provider Agent
Mac Provider Agent
  -> local mac-browser-mcp stdio
  -> existing Browser Plane runtime / JobStore / worker
  -> restricted SSH submit back to Bangkok
```

The calling application remains responsible for source policy and capability authorization. Browser Plane remains an execution plane, not an embedded autonomous planner.

## Git chain

- R4 enable PR #30 merged at `f5072ac4f0cf180282f8af9bdd20d7ff9d49d5b1`.
- Production backlog-drain fix PR #31 merged at `7a13bcb1ab8acf0a69585bbddc0a6d88cd56d9ea`.
- Installed runtime was rebuilt from `7a13bcb1...` after merge.

## Installed runtime proof

```text
Provider LaunchAgent = running
production_enabled   = true
invocation_mode      = pull_ssh_v1
remote_invocation    = true
Provider stderr tail = empty
Provider TCP LISTEN  = none
```

Backlog polling behavior from the installed runtime:

```text
completed work -> 0.0 seconds before next claim
NO_WORK        -> 10.0 seconds idle poll delay
```

This preserves low idle SSH polling while draining production request batches without artificial per-item delay.

## Security boundary

The production Provider Agent uses the dedicated SignalForge Provider SSH identity created for PIC v1. It does not use the Mac administrator/root SSH identity.

Bangkok binds that identity to a forced-command provider dispatcher. Earlier R3 verification proved arbitrary commands such as `id` are denied; credential disable/restore was also live-tested.

R4 does not change these boundaries:

- no PTY;
- no SSH forwarding;
- no user-rc;
- no arbitrary remote shell;
- no inbound Mac service;
- no arbitrary JavaScript/raw CDP capability expansion;
- local Browser execution still goes through MCP stdio and the existing Browser Plane runtime.

## Live offline isolation

During R4/R5 production verification the Provider LaunchAgent was deliberately booted out while `browserctl doctor` remained `READY`.

Bangkok S38 then failed only after its bounded 90-second Provider acquisition timeout. While the Provider Agent remained offline, a separate Direct HTTP S37 refresh succeeded after the existing Worker single-application admission slot was free.

The timed-out ProviderRequest was deliberately left until TTL expiration. After Provider Agent restoration, it was marked `EXPIRED / PROVIDER_REQUEST_EXPIRED`; the Agent did not execute it as orphaned work.

This proves Provider unavailability is an acquisition dependency for the explicitly routed Provider source, not a Mac Browser Plane failure and not a Direct HTTP outage.

## Unattended proof

After Provider Agent restoration, no source-specific S38 refresh was used for recovery. Bangkok restored its production timer and its normal `run-due` scheduler invoked S38 automatically.

SignalForge recorded the unattended S38 run as:

```text
started_at        = 2026-09-08T14:20:54.213550Z
trigger_kind      = POLL
status            = SUCCESS
changed           = 0
signals_created   = 0
backlog_remaining = 0
```

This proves the Mac Provider Agent operates independently of the ChatGPT/CodexPro session once installed.

## Closed / still deferred

Closed:

- remote production invocation through `pull_ssh_v1`;
- dedicated launchd Provider Agent;
- bounded SignalForge source authorization through the reviewed PIC contract;
- unattended Mac pull and result submission;
- production batch draining.

Still deferred unless separately authorized:

- SEA/VPS Browser egress;
- China Browser egress;
- autonomous embedded Browser Agent / LLM planner;
- headed/human takeover;
- generic cross-source Browser fallback;
- arbitrary JavaScript/raw CDP surfaces.

SignalForge's source-specific production facts and final S38 GREEN closure live in the SignalForge repository under `docs/verification/PIC-R4-R5-PRODUCTION-CLOSURE-2026-09-08.md`.
