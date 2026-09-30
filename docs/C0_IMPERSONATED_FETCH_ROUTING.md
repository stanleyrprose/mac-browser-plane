# C0 Impersonated Fetch Routing v1

Status: implementation contract for Mac Browser Plane.

## Goal

Keep `browser_fetch` as one caller-facing C0 capability while adding a bounded browser-like HTTP transport for cases where ordinary system `curl` is rejected because of TLS/HTTP client fingerprint or a clearly identified anti-bot challenge.

This is still C0 HTTP acquisition. It does not execute JavaScript, create a DOM, click, type, use a browser profile, or authorize escalation to C1/C2/C3.

## Routing

```text
browser_fetch
  -> system /usr/bin/curl
       -> ordinary response: return direct result
       -> explicit challenge evidence: try curl_cffi once
       -> bounded TLS/HTTP-client compatibility error: try curl_cffi once
  -> curl_cffi impersonate="chrome"
       -> useful non-challenge response: select curl_cffi result
       -> still challenged / failed: preserve direct result or fail with both errors
```

The result keeps `engine="c0-fetch"` and adds `transport` plus `transport_route` evidence.

## Fallback triggers

v1 permits one impersonated retry only for:

- explicit Cloudflare/Akamai/DataDome challenge markers in a textual response;
- selected libcurl client-compatibility errors: HTTP/2 protocol error, SSL connect error, empty reply, receive error, or HTTP/2 stream error.

A plain HTTP `403`, `429`, `401`, `5xx`, timeout, DNS failure, connection refusal, or certificate-verification failure does not by itself trigger impersonation.

## Security and resource boundaries

- normal TLS certificate verification stays enabled;
- `curl_cffi` uses `CurlFollow.SAFE` for redirects;
- response capture is bounded to 1,000,000 bytes;
- only GET acquisition is used;
- no cookies/profile state is persisted across C0 jobs;
- no proxy or alternate regional egress is introduced;
- no automatic C0 -> Browser fallback is introduced.

System curl also constrains initial and redirected URL schemes to HTTP/HTTPS. The existing MCP URL policy remains authoritative for public agent-facing URLs.

## Failure semantics

If direct curl returns explicit challenge evidence and the impersonated request does not produce a non-challenge 2xx/3xx response, the direct evidence remains canonical and the fallback attempt is recorded in `transport_route`.

If direct curl fails with an allowed client-compatibility error and the impersonated request also fails, the C0 job fails with both errors recorded in the exception message.

## Non-goals

v1 does not:

- treat `curl_cffi` as a browser engine;
- solve JavaScript challenges or CAPTCHA;
- add source-specific rules to Browser Plane;
- add automatic proxy rotation;
- bypass authorization, rate limits, or certificate validation;
- replace system curl as the default C0 transport.
