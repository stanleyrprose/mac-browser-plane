# Public Read Acquisition Router v1

## Intent

`browser_acquire(url)` is the preferred local MCP surface when an authorized caller wants reliable public content but does not want to choose between HTTP and browser rendering.

The call itself authorizes one bounded read-only acquisition sequence:

```text
browser_acquire
  -> C0 browser_fetch
       -> system curl
       -> bounded curl_cffi when C0 transport evidence requires it
  -> classify C0 result
  -> C1 browser_render only when conservative render evidence is present
       -> Lightpanda
       -> safe Chrome fallback under existing C1 policy
```

## C1 render triggers

v1 permits C1 only for:

- an unresolved supported anti-bot challenge where C0 still selected system curl;
- successful HTML acquisition with an empty body;
- a low-content HTML shell that explicitly requires JavaScript;
- a low-visible-text SPA shell with script/runtime evidence.

A successful `curl_cffi` recovery is still a successful C0 result and is not rendered again.

## Non-triggers

These do not by themselves authorize C1:

- plain 401 or 403;
- plain 429;
- generic 5xx;
- DNS failure;
- connection failure;
- timeout;
- TLS certificate verification failure;
- non-HTML responses.

## Security boundary

- public HTTP(S) URL guard remains unchanged;
- direct egress only;
- C1 profile is `public-research`, ephemeral only;
- no click/type/download/interaction is performed;
- no C2 inspect or C3 Browser Use is authorized;
- no proxy or regional egress is added;
- Provider Invocation Contract is unchanged and does not expose `browser_acquire` yet.

## Caller guidance

Use `browser_acquire` for: “read this public URL reliably.”

Use `browser_fetch` when the caller specifically requires strict C0-only acquisition.

Use `browser_render` when the caller already knows JavaScript/DOM rendering is required.

Use `browser_inspect` or `browser_use` only for their explicit diagnostic or interaction purposes.
