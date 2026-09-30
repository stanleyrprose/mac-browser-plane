# DOCUMENT_OCR Provider Byte-Budget Fix — 2026-09-30

## Problem

SignalForge source S23 exposed a real capability mismatch after DOCUMENT_OCR was authorized for issuer-original Ministry of Construction PDFs.

The Provider Invocation Contract allowed a 4 MB official document, but the composed provider path fetched the PDF through the public browser_fetch MCP surface, whose intentional C0 body limit is 1 MB. A 1.47 MB scan-only tender PDF therefore failed before OCR even though it was inside the reviewed PIC budget.

## Decision

Keep the public browser_fetch 1 MB contract unchanged.

For an already validated DOCUMENT_OCR provider request only, the Provider Agent now performs a provider-internal strict-TLS PDF fetch bounded by the request max_bytes. The request max_bytes itself is already bounded by the local source/target PIC.

The internal fetch:

- permits HTTPS only, including redirects;
- uses system curl first;
- permits the existing curl_cffi retry only for the already-approved client-compatibility error classes;
- writes only into Browser Plane runtime evidence with directory mode 0700 and file mode 0600;
- validates the final URL against the local PIC target/final-url policy, never against a caller-supplied broader policy;
- requires a PDF magic header;
- refuses non-success HTTP status;
- preserves SHA-256 and byte length for the downstream OCR integrity checks.

## Security boundary

This change does not enlarge browser_fetch, the local MCP tool surface, C1/C2/C3 authority, or arbitrary remote URL authority.

Only a SignalForge request that has already passed the source-specific DOCUMENT_OCR PIC may use the larger document byte budget.

## Live verification

The S23 Yadanar Theingha Bridge official PDF was used as the live regression case:

- URL host/path: construction.gov.mm /storage/TinDar/
- PDF size: 1,472,391 bytes
- PIC request budget: 4,000,000 bytes
- fetch: HTTP 200 / system curl / strict TLS
- SHA-256: 33ce06727d4697160d8611d7ea9b227e0b8961c51f6c54c49a2f6f98427a84bd
- DOCUMENT_OCR: 1 page, mean confidence 79.16, network_access=false
- OCR recovered the Yadanar Theingha bridge identity and 2,480 ft scale.

Public browser_fetch remains capped at 1,000,000 bytes.
