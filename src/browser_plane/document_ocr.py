from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import RuntimePaths
from .ocr import OCRError, ocr_artifact, ocr_readiness

_ALLOWED_PSM = {4, 6, 11}
_MAX_INPUT_BYTES = 25 * 1024 * 1024
_MAX_PAGES = 20
_MAX_PAGE_TEXT_CHARS = 20_000
_MAX_TOTAL_TEXT_CHARS = 240_000
_SWIFT = Path("/usr/bin/swift")

_SWIFT_RASTERIZER = r"""
import Foundation
import PDFKit
import AppKit

let args = CommandLine.arguments
guard args.count == 4 else { exit(2) }
let input = URL(fileURLWithPath: args[1])
let outputDirectory = URL(fileURLWithPath: args[2], isDirectory: true)
guard let maxPages = Int(args[3]), maxPages > 0 else { exit(2) }
guard let document = PDFDocument(url: input) else { exit(3) }
let pageCount = document.pageCount
let count = min(pageCount, maxPages)
var written = 0

for index in 0..<count {
    guard let page = document.page(at: index) else { exit(4) }
    let bounds = page.bounds(for: .mediaBox)
    let scale: CGFloat = 2.5
    let target = NSSize(
        width: max(1200, bounds.width * scale),
        height: max(1600, bounds.height * scale)
    )
    let image = page.thumbnail(of: target, for: .mediaBox)
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        exit(5)
    }
    let name = String(format: "page-%03d.png", index + 1)
    try png.write(to: outputDirectory.appendingPathComponent(name))
    written += 1
}

let result: [String: Any] = [
    "page_count": pageCount,
    "rasterized_pages": written,
    "page_limit_truncated": pageCount > maxPages
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
"""


class DocumentOCRError(RuntimeError):
    pass


def document_ocr_readiness(paths: RuntimePaths) -> dict[str, Any]:
    image_ocr = ocr_readiness(paths)
    pdfkit = Path("/System/Library/Frameworks/PDFKit.framework").exists()
    swift = _SWIFT.is_file()
    return {
        "ready": bool(image_ocr.get("ready")) and pdfkit and swift,
        "swift_path": str(_SWIFT) if swift else None,
        "pdfkit_framework_present": pdfkit,
        "artifact_ocr_ready": bool(image_ocr.get("ready")),
        "rasterizer": "macOS PDFKit",
        "max_pages": _MAX_PAGES,
        "network_access": False,
    }


def _resolve_evidence_pdf(paths: RuntimePaths, artifact_path: str) -> Path:
    value = artifact_path.strip()
    if not value:
        raise DocumentOCRError("artifact_path must not be empty")
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = paths.evidence_dir / raw
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise DocumentOCRError(f"artifact_path is not readable: {exc}") from exc

    evidence_root = paths.evidence_dir.resolve()
    try:
        resolved.relative_to(evidence_root)
    except ValueError as exc:
        raise DocumentOCRError("artifact_path must be inside the Browser Plane evidence directory") from exc
    if not resolved.is_file():
        raise DocumentOCRError("artifact_path must reference a regular file")
    if resolved.suffix.lower() != ".pdf":
        raise DocumentOCRError("document_ocr accepts PDF evidence only")
    size = resolved.stat().st_size
    if size <= 0:
        raise DocumentOCRError("PDF evidence is empty")
    if size > _MAX_INPUT_BYTES:
        raise DocumentOCRError(f"PDF evidence exceeds {_MAX_INPUT_BYTES} bytes")
    with resolved.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        raise DocumentOCRError("artifact extension is PDF but file signature is not PDF")
    return resolved


def _rasterize_pdf(pdf_path: Path, output_dir: Path, *, max_pages: int) -> dict[str, Any]:
    if not _SWIFT.is_file():
        raise DocumentOCRError("/usr/bin/swift is unavailable for PDFKit rasterization")
    swift_path = output_dir / "rasterize.swift"
    swift_path.write_text(_SWIFT_RASTERIZER, encoding="utf-8")
    try:
        proc = subprocess.run(
            [str(_SWIFT), str(swift_path), str(pdf_path), str(output_dir), str(max_pages)],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocumentOCRError("PDFKit rasterization timed out after 90 seconds") from exc
    except OSError as exc:
        raise DocumentOCRError(f"PDFKit rasterization failed to start: {exc}") from exc
    finally:
        swift_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:1200]
        raise DocumentOCRError(f"PDFKit rasterization failed ({proc.returncode}): {detail}")
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DocumentOCRError("PDFKit rasterization returned invalid metadata") from exc
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("page_count"), int)
        or not isinstance(value.get("rasterized_pages"), int)
    ):
        raise DocumentOCRError("PDFKit rasterization metadata incomplete")
    return value


def ocr_document(
    paths: RuntimePaths,
    artifact_path: str,
    *,
    psm: int = 6,
    max_pages: int = 12,
) -> dict[str, Any]:
    if psm not in _ALLOWED_PSM:
        raise DocumentOCRError(f"psm must be one of: {', '.join(str(v) for v in sorted(_ALLOWED_PSM))}")
    if not isinstance(max_pages, int) or max_pages < 1 or max_pages > _MAX_PAGES:
        raise DocumentOCRError(f"max_pages must be between 1 and {_MAX_PAGES}")

    pdf_path = _resolve_evidence_pdf(paths, artifact_path)
    pdf_bytes = pdf_path.read_bytes()
    work_dir = Path(tempfile.mkdtemp(prefix="document-ocr-", dir=str(paths.evidence_dir)))
    pages: list[dict[str, Any]] = []
    all_text: list[str] = []
    confidences: list[float] = []
    try:
        raster = _rasterize_pdf(pdf_path, work_dir, max_pages=max_pages)
        images = sorted(work_dir.glob("page-*.png"))
        if len(images) != int(raster["rasterized_pages"]) or not images:
            raise DocumentOCRError("PDFKit rasterization page artifacts incomplete")

        for index, image_path in enumerate(images, start=1):
            try:
                ocr = ocr_artifact(paths, str(image_path), psm=psm)
            except OCRError as exc:
                raise DocumentOCRError(f"OCR failed on page {index}: {exc}") from exc
            text = str(ocr.get("text") or "")
            bounded_text = text[:_MAX_PAGE_TEXT_CHARS]
            confidence = ocr.get("mean_confidence")
            if isinstance(confidence, (int, float)):
                confidences.append(float(confidence))
            pages.append(
                {
                    "page": index,
                    "image_sha256": str(ocr.get("input_sha256") or ""),
                    "image_bytes": int(ocr.get("input_bytes") or 0),
                    "text": bounded_text,
                    "text_truncated": len(text) > len(bounded_text) or bool(ocr.get("text_truncated")),
                    "line_count": int(ocr.get("line_count") or 0),
                    "mean_confidence": confidence,
                }
            )
            all_text.append(f"--- PAGE {index} ---\n{bounded_text}")

        combined = "\n".join(all_text)
        combined = combined[:_MAX_TOTAL_TEXT_CHARS]
        return {
            "engine": "tesseract",
            "rasterizer": "macOS PDFKit",
            "model_profile": str(ocr.get("model_profile") or "unknown"),
            "languages": list(ocr.get("languages") or ["mya", "eng"]),
            "psm": psm,
            "input_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "input_bytes": len(pdf_bytes),
            "page_count": int(raster["page_count"]),
            "processed_pages": len(pages),
            "page_limit_truncated": bool(raster.get("page_limit_truncated")),
            "pages": pages,
            "text": combined,
            "text_truncated": len("\n".join(all_text)) > len(combined),
            "mean_confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
            "network_access": False,
            "intermediate_images_retained": False,
            "result_semantics": "EVIDENCE_ENRICHMENT_ONLY_CRITICAL_FIELDS_REQUIRE_SOURCE_CROSS_CHECK",
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
