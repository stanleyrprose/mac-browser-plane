# Source Capability Matrix

**Observed on:** 2026-09-04  
**Runtime:** Mac Browser Plane R1, Mac mini direct egress  
**Policy:** C0 first; C1 only when C0 is genuinely insufficient; C2 is diagnostics, not a default acquisition path.

## Current Matrix

| Source | Business purpose | C0 | C1 | C2 | Preferred production path | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| MPT Tender | Telecom procurement / tender monitoring | PASS | PASS | PASS | **C0** | Initial Python `urllib` client hit a TLS-chain compatibility failure; macOS `/usr/bin/curl` with normal TLS verification returns HTTP 200 and ~80 KB HTML. Browser is not required. |
| Myanma Port Authority — Tenders & Announcement | Port / infrastructure / procurement monitoring | PASS | Not required | Not required | **C0** | Static HTML contains current tender dates/titles, including 21/08/2026 and `Open Tender Invitation for three Tugs`; complete response is preserved as `response.html`. |
| Myanma Port Authority — tender PDF attachment | Tender evidence attachment | PASS | Not required | Not required | **C0 binary artifact** | Real PDF returned HTTP 200 / 78,480 bytes. Binary response is preserved as `response.pdf`, SHA-256 recorded, mode `0600`; no lossy text decoding. |
| Ministry of Commerce — 2026 Notifications | Regulation / import-export / policy monitoring | PASS | Not required | Not required | **C0** | Static HTML contains 2026 notification entries and current dates; complete response is preserved as a raw text/HTML artifact; no Browser requirement observed. |

## Source-specific observations

### MPT Tender

URL:

```text
https://mpt.com.mm/en/about-home/tenders/
```

Observed:

```text
old C0 urllib        -> TLS certificate-chain failure
C1 Playwright        -> HTTP 200
C2 diagnostics       -> HTTP 200
C0 macOS system curl -> HTTP 200 / 80,226-byte HTML
```

Disposition:

```text
Preferred path = C0
Browser required = NO
```

Engineering lesson:

> A C0 client/TLS failure must be classified before escalating to C1. It does not prove that the source requires Browser execution.

### Myanma Port Authority — Tenders

URL:

```text
https://www.mpa.gov.mm/tenders-and-announcement/
```

Observed on Mac Browser Plane C0:

```text
HTTP 200
HTML ~= 252 KB
business list present in static HTML
```

Static HTML was verified to contain:

```text
21/08/2026
Open Tender Invitation for three Tugs
```

Disposition:

```text
Preferred path = C0
Browser required = NO
```

### Myanma Port Authority — PDF evidence

Real attachment tested:

```text
https://www.mpa.gov.mm/wp-content/uploads/2026/04/Tug-3Nos-Tender-Eng2026.pdf
```

Observed:

```text
HTTP 200
Content-Type: application/pdf
Content-Length: 78,480 bytes
```

R1 behavior after source acceptance hardening:

```text
text_excerpt = omitted
artifact      = response.pdf
sha256        = recorded
file mode     = 0600
```

No PDF parser is added to Browser Plane. Extraction/canonicalization remains an application-layer concern.

### Ministry of Commerce — Notifications

URL:

```text
https://commerce.gov.mm/en/noti/archive/2026
```

Observed on Mac Browser Plane C0:

```text
HTTP 200
HTML ~= 108 KB
2026 notification list present in static HTML
```

Disposition:

```text
Preferred path = C0
Browser required = NO
```

## Escalation rule

For every future source:

```text
C0 Direct
  |
  +-- sufficient -> freeze source on C0
  |
  +-- failure -> classify first
         |
         +-- TLS / DNS / HTTP-client / transient network issue -> fix or classify C0
         +-- static HTML lacks required business content because JS renders it -> C1
         +-- C1 behaves unexpectedly / needs investigation -> C2
         +-- deterministic C1 remains insufficient for a real workflow -> evaluate C3 separately
```

Do not enable C1/C2/C3 merely because they are available.

## Current conclusion

The first three real Myanmar business sources do **not** provide evidence that C3 Browser Agent is needed.

The useful Browser Plane role today is:

- reliable C0 transport;
- deterministic C1 when a future source actually requires Browser rendering/interaction;
- C2 diagnostics for explaining failures;
- safe preservation of binary source evidence such as tender PDFs.
