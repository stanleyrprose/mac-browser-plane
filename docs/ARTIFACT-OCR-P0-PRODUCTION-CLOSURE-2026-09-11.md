# Artifact OCR P0 Production Closure — 2026-09-11

## Scope

This closure records the minimum sufficient OCR capability added to Mac Browser Plane after real SignalForge evidence showed that scan/image-only Myanmar procurement material was blocking business-field recovery.

Artifact OCR is deliberately **orthogonal to C0–C3**. It is not C4, does not add a browser engine, does not add a daemon or network listener, and does not move SignalForge business semantics into Browser Plane.

## Decision

P0 uses local Tesseract with fixed Burmese + English recognition:

```text
engine        = Tesseract 5.5.3
languages     = mya + eng
model profile = runtime-local tessdata_best
transport     = local MCP stdio
network       = none
```

The temporary Homebrew `tesseract-lang` all-language bundle used during benchmarking was removed. Production keeps only `eng.traineddata` (~15 MB) and `mya.traineddata` (~14 MB) under `~/agent-browser-runtime/ocr/tessdata_best/`.

Apple Vision was inspected on the current Mac runtime and Burmese was not present in its supported recognition-language list, so it was not selected for P0. Heavier document OCR systems remain unnecessary until evidence shows Tesseract is insufficient.

## Capability contract

The new MCP tool is:

```text
artifact_ocr(artifact_path, psm=6)
```

P0 boundaries:

- input must resolve inside Browser Plane's runtime evidence directory;
- symlink/path escape fails closed;
- PNG/JPEG only;
- maximum input size 25 MB;
- file signature must match the image extension;
- fixed `mya+eng` recognition;
- allowed PSM values: 4, 6, 11;
- no network I/O;
- output includes input SHA-256, reconstructed text, line bounding boxes and confidence;
- result semantics are `EVIDENCE_ENRICHMENT_ONLY_CRITICAL_FIELDS_REQUIRE_SOURCE_CROSS_CHECK`.

Local MCP and the CodexPro bridge may invoke the capability. The existing SignalForge Provider Invocation Contract does **not** authorize OCR in this P0 slice.

## Real-evidence benchmark

### MTE 1605

Official image:

```text
https://mte.gov.mm/images/2022/ll%20sep.jpg
SHA-256 = 6a6c2452cf8ae18bf4985c3bd77f63bbd77ec710ad5b37ae3db51409854348e1
```

The SHA exactly matched the existing SignalForge reviewed-image evidence. `tessdata_best` recovered the important business text, including:

- action date `2026-09-15`;
- action time `08:30`;
- approximately `6243` tons of logs/sawn timber;
- MTE / Gyogon Forest Compound / Insein / Yangon location text.

This benchmark exposed two errors in the existing SignalForge reviewed enrichment: its stored `09:30` time and `6 categories/types` quantity interpretation do not match the official image. Those business-data corrections are intentionally handled in SignalForge separately from this Browser Plane capability PR.

### DOMS scan-only attachments

The current `doms:12735` opportunity's official 8DMS/9DMS/10DMS PDFs had already been verified as effectively scan-only under text-PDF extraction. OCR testing recovered useful Tender No / Group / Commodity scope. Quantity-table cells were less reliable, and the non-best model read `10DMS` as `L0DMS`; `tessdata_best` corrected that identifier.

Therefore OCR is useful for evidence enrichment, but a single OCR result is not authoritative for critical identifiers, dates or quantities.

## Implementation verification

Source verification after the final OCR TSV fix:

```text
targeted OCR/MCP tests: 17 passed
full source suite:      65 passed
compileall:             PASS
```

PR #42 implementation head `470a8247e1494beb77a6f8e6a688b8f72e1cf5ff` passed GitHub Actions `test` in run `34619859893`.

A live acceptance run also caught and fixed an integration bug before closure: passing the `tsv` config name while using a minimal custom `--tessdata-dir` caused Tesseract to fall back to plain text and the parser returned zero lines. The implementation now enables TSV with `-c tessedit_create_tsv=1`, which works without copying unrelated config files into the minimal tessdata directory.

## Installed-runtime acceptance

The reviewed feature revision was installed into the non-editable production runtime and the LaunchAgent was reinstalled.

`browserctl doctor` returned `READY` with:

```text
SQLite integrity                    ok
Artifact OCR installed              true
Tesseract version                   5.5.3
languages                           mya, eng
model_profile                       tessdata_best
required_languages_present          true
stale_profile_leases                []
browser_process_ownership residue   []
```

The installed `mac-browser-mcp-call list` returned exactly ten authorized local tools with no missing or unexpected tool.

A real MCP call against the same MTE evidence returned:

```text
ok                = true
input_sha256       = 6a6c2452cf8ae18bf4985c3bd77f63bbd77ec710ad5b37ae3db51409854348e1
model_profile      = tessdata_best
network_access     = false
line_count         = 20
mean_confidence    = 79.22
```

The returned text contained Burmese-script values corresponding to `6243`, `15-9-2026`, and `08:30`. A post-smoke doctor run remained `READY` with no lease/process residue.

## Explicit non-goals / deferred scope

P0 does not implement PDF rasterization, table understanding, OCR HTTP service, cloud OCR, automatic multi-engine routing, automatic SignalForge source routing, or SignalForge Provider OCR authorization. These should be added only when a concrete source/value case justifies them.

## Production rule

> OCR produces evidence, not truth. Source/application logic must cross-check critical identifiers, dates, quantities and actions against independent source metadata or other issuer evidence; conflicts remain review/unknown rather than being silently promoted to canonical fact.
