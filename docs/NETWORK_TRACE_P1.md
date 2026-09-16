# Network Trace P1

**Status:** P1 validated locally on 2026-09-16
**Role:** internal operator diagnostic for Mac Browser Plane
**Implementation:** optional `mitmdump` process, default OFF

## Purpose

Network Trace P1 adds a bounded application-network observability layer for diagnosing browser/acquisition failures and discovering structured HTTP endpoints. It is not a browser engine and is not exposed as an MCP or SignalForge Provider tool.

The existing Browser Plane remains authoritative for browser lifecycle, jobs, leases, profiles, process ownership, and evidence. `mitmdump` is started only by an explicit local `browserctl trace ...` command and is registered in the existing Browser Process Registry so shutdown still requires proven ownership.

## Safety boundary

P1 deliberately does less than a general interception proxy:

- default OFF;
- listens only on `127.0.0.1`;
- requires an explicit bare host;
- configures mitmproxy `allow_hosts` for that host/subdomains;
- retains only bounded response metadata, not request/response bodies;
- does not persist query strings;
- does not read or store request headers;
- does not install a CA into macOS, Chrome, or any system trust store;
- does not capture all Mac traffic;
- does not launch Chrome or modify the existing engine router;
- is not available through local MCP or the remote Provider contract.

Stored flow metadata contains only timestamp, method, scheme, host, path, HTTP status, content type, response byte size, and a conservative `api_like` flag. Trace evidence and state files use the existing private Browser Plane runtime directories.

## Operator commands

```text
browserctl trace doctor
browserctl trace start --host example.com
browserctl trace summary
browserctl trace stop
```

`trace start` returns a loopback proxy URL. The caller explicitly routes a bounded debug client through that proxy. P1 does not silently modify system proxy settings.

## Verified smoke test

The local P1 smoke used `httpbin.org` over plain HTTP to avoid any trust-store change:

```text
trace host: httpbin.org
proxy:      127.0.0.1:18080
request:    GET http://httpbin.org/json
result:     HTTP 200 / application/json
summary:    1 flow, 1 api_like flow
```

The structured record contained `/json`, status `200`, content type `application/json`, and response size only. No response body was stored by Network Trace.

## HTTPS and certificate boundary

mitmproxy can inspect HTTPS only when the client trusts its generated CA. P1 intentionally does **not** install that CA globally. A future Browser Plane HTTPS PoC must use a dedicated isolated debug browser profile and a narrowly scoped trust configuration; the normal production profile and system trust store remain unchanged.

Applications using certificate pinning may reject interception even when a user CA is trusted. Bypassing pinning is outside this capability.

## HTTP/3 / QUIC boundary

Regular explicit HTTP proxy mode is aimed at HTTP/1.x and HTTP/2-style proxy traffic. Native UDP/QUIC traffic may bypass or require another mitmproxy mode. P1 does not add TUN, transparent routing, WireGuard, or system-wide routing changes merely to capture HTTP/3.

## Promotion gate

P1 proves that bounded metadata capture works. It does **not** yet route a Browser Plane Chrome worker through the proxy automatically. Promote this further only when a real source needs one of these outcomes:

1. discover an XHR/JSON/GraphQL endpoint that DOM acquisition cannot identify reliably;
2. diagnose an authentication/redirect/network failure not explainable by C2 evidence;
3. prove that API acquisition can replace a materially more expensive rendered-browser path.

If that gate is met, the next change should inject an optional loopback proxy into an existing ephemeral debug Chrome launch path without creating a second browser lifecycle manager or a new public MCP capability.
