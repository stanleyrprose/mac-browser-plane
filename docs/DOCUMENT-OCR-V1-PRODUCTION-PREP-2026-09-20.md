# Document OCR v1 — Production Preparation — 2026-09-20

## Goal

Provide a bounded PDF OCR capability for SignalForge review evidence without introducing a second OCR engine, cloud OCR service, inbound Mac listener, arbitrary file access, or canonical-truth authority.

## Architecture

Local MCP:

```text
runtime-owned PDF
    ↓
document_ocr
    ↓
macOS PDFKit page rasterization
    ↓
temporary runtime-owned PNG pages
    ↓
existing artifact_ocr
    ↓
Tesseract 5.5.3 / tessdata_best / mya+eng
    ↓
bounded page OCR evidence
```

Intermediate page images are deleted after OCR.

## Local boundaries

- input must resolve inside Browser Plane runtime evidence;
- PDF extension + PDF magic required;
- maximum PDF size 25 MB;
- allowed PSM: 4 / 6 / 11;
- maximum 20 pages; default 12;
- fixed mya+eng OCR;
- no OCR network access;
- combined OCR text bounded;
- result includes original PDF SHA-256 and per-page raster SHA/confidence;
- result semantics remain evidence enrichment only.

## Provider composition

The Mac Provider Agent adds `DOCUMENT_OCR`.

It does not accept an arbitrary local path from SignalForge.

Execution is fixed:

```text
approved requested_url
    ↓
browser_fetch
    ↓
runtime-owned PDF artifact
    ↓
PDF SHA / size / magic verification
    ↓
document_ocr(psm=6,max_pages=12)
    ↓
OCR input SHA must equal fetched PDF SHA
    ↓
portable JSON evidence result
```

Any SHA mismatch fails closed.

Raw `artifact_ocr` path invocation remains local-only. SignalForge remote document OCR still depends on the Provider Invocation Contract authorizing a source/target URL surface.

## Live Pobbathiri acceptance

Official document:

`https://myanmar.gov.mm/documents/20143/0/Newspaper+advertiement+10082026.pdf/aa3cebae-2f59-5c3c-e840-640c99f0cb92`

Source-branch live result:

```text
engine                       tesseract
rasterizer                   macOS PDFKit
model_profile                tessdata_best
languages                    mya + eng
psm                          6
input_sha256                 3dd5dd18a2395ba1bb18bdc31c9fa9850a98aced98fb05b7453c4380d24c9eea
input_bytes                  34575
page_count                   1
processed_pages              1
page_limit_truncated         false
mean_confidence              73.26
network_access               false
intermediate_images_retained false
```

OCR recovered the key visual evidence for the MPT/MDDC Pobbathiri tender, including project scope, tender-form sale date, evening 04:30 close, site survey date, and the 09:30–14:00 bid-submission window.

## Doctor

Source runtime doctor:

```text
status = READY

artifact_ocr.ready = true
document_ocr.ready = true
swift_path = /usr/bin/swift
pdfkit_framework_present = true
artifact_ocr_ready = true
network_access = false
```

## Verification

- document OCR + Provider + MCP focused tests: 31 / 31 PASS
- full Browser Plane pytest: 104 passed
- compileall: PASS
- capabilities JSON: PASS
- git diff --check: PASS

## Authority

OCR produces evidence, not truth.

SignalForge must reconcile OCR with native PDF extraction and other official evidence before critical fields are treated as reviewed. Conflicts remain human-review required.
