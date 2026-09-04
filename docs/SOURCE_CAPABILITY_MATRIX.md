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
| Ministry of Border Affairs — Tenders | Public-sector tender monitoring | PASS | Not required | Not required | **C0** | `Load More` is backed by ordinary Drupal `?page=N` links. C0 page 0 and page 1 both returned HTTP 200 with different content; no click/JS execution is needed. |
| Myanmar National Trade Portal — Legal Documents | Regulation / legal / trade-policy monitoring | PASS | Not required | Not required | **C0** | Initial page is server-rendered; pagination uses ordinary `?page=N` URLs and filters are a normal GET form. C0 keyword filter returned exactly 1/1 target result. |

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

### Ministry of Border Affairs — Tenders

URL:

```text
https://moba.gov.mm/tender
```

Observed on Mac Browser Plane C0:

```text
page 0 -> HTTP 200 / 84,281-byte HTML
page 1 -> HTTP 200 / 82,925-byte HTML
page contents differ
```

The page visibly presents `Load More`, but the raw HTML exposes ordinary Drupal pager links:

```text
?page=0
?page=1
...
?page=6
```

Disposition:

```text
Preferred path = C0
Browser required = NO
```

A visible interactive control is not, by itself, evidence of a Browser requirement.

### Myanmar National Trade Portal — Legal Documents

URL:

```text
https://www.myanmartradeportal.gov.mm/legals
```

Observed on Mac Browser Plane C0:

```text
initial page -> HTTP 200 / 58,396-byte HTML
454 results advertised in server-rendered HTML
pagination -> ?page=2 ... ?page=31
```

The search/filter UI is a normal GET form to `/legals` with parameters such as:

```text
keyword
legal_type
responsible_agency
issuing_agency
from_date
to_date
```

A direct C0 request for:

```text
?keyword=Notification+(2/2026)
```

returned:

```text
HTTP 200
Displaying 1 - 1 of 1 result
Notification (2/2026) present
Notification 101/2026 absent
```

Disposition:

```text
Preferred path = C0
Browser required = NO
```

Filtering and pagination should therefore be modeled as deterministic URL/query generation, not Browser clicks.

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

The first five real Myanmar public business/regulatory source families tested do **not** provide evidence that C3 Browser Agent is needed. Even visible `Load More`, pagination, and filtering controls have so far reduced to deterministic C0 URLs/query parameters.

The useful Browser Plane role today is:

- reliable C0 transport;
- deterministic C1 when a future source actually requires Browser rendering/interaction;
- C2 diagnostics for explaining failures;
- safe preservation of binary source evidence such as tender PDFs.
