from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import RuntimePaths


_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg"}
_ALLOWED_PSM = {4, 6, 11}
_MAX_INPUT_BYTES = 25 * 1024 * 1024
_MAX_TSV_BYTES = 4 * 1024 * 1024
_MAX_TEXT_CHARS = 200_000
_MAX_LINES = 1_000
_LANGUAGES = ("mya", "eng")


class OCRError(RuntimeError):
    pass


def _tesseract_path() -> Path | None:
    configured = os.environ.get("BROWSER_PLANE_TESSERACT")
    candidates = [configured, shutil.which("tesseract"), "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _preferred_tessdata_dir(paths: RuntimePaths) -> Path | None:
    configured = os.environ.get("BROWSER_PLANE_OCR_TESSDATA_DIR")
    candidate = Path(configured).expanduser() if configured else paths.root / "ocr" / "tessdata_best"
    if all((candidate / f"{lang}.traineddata").is_file() for lang in _LANGUAGES):
        return candidate
    return None


def ocr_readiness(paths: RuntimePaths) -> dict[str, Any]:
    tesseract = _tesseract_path()
    tessdata_dir = _preferred_tessdata_dir(paths)
    languages: list[str] = []
    version: str | None = None
    if tesseract is not None:
        try:
            version_proc = subprocess.run(
                [str(tesseract), "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if version_proc.returncode == 0 and version_proc.stdout:
                version = version_proc.stdout.splitlines()[0].strip()
            language_proc = subprocess.run(
                [str(tesseract), "--list-langs"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if language_proc.returncode == 0:
                languages = [line.strip() for line in language_proc.stdout.splitlines()[1:] if line.strip()]
        except (OSError, subprocess.SubprocessError):
            pass

    if tessdata_dir is not None:
        languages = list(_LANGUAGES)

    required_languages_present = all(lang in languages for lang in _LANGUAGES)
    return {
        "installed": tesseract is not None,
        "path": str(tesseract) if tesseract is not None else None,
        "version": version,
        "languages": list(_LANGUAGES),
        "required_languages_present": required_languages_present,
        "preferred_tessdata_dir": str(tessdata_dir) if tessdata_dir is not None else None,
        "model_profile": "tessdata_best" if tessdata_dir is not None else "system",
        "ready": tesseract is not None and required_languages_present,
    }


def _resolve_evidence_image(paths: RuntimePaths, artifact_path: str) -> Path:
    value = artifact_path.strip()
    if not value:
        raise OCRError("artifact_path must not be empty")

    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = paths.evidence_dir / raw
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise OCRError(f"artifact_path is not readable: {exc}") from exc

    evidence_root = paths.evidence_dir.resolve()
    try:
        resolved.relative_to(evidence_root)
    except ValueError as exc:
        raise OCRError("artifact_path must be inside the Browser Plane evidence directory") from exc

    if not resolved.is_file():
        raise OCRError("artifact_path must reference a regular file")
    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise OCRError("artifact_ocr P0 accepts PNG and JPEG images only")

    size = resolved.stat().st_size
    if size <= 0:
        raise OCRError("artifact image is empty")
    if size > _MAX_INPUT_BYTES:
        raise OCRError(f"artifact image exceeds {_MAX_INPUT_BYTES} bytes")

    with resolved.open("rb") as handle:
        header = handle.read(12)
    suffix = resolved.suffix.lower()
    if suffix == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OCRError("artifact extension is PNG but file signature is not PNG")
    if suffix in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise OCRError("artifact extension is JPEG but file signature is not JPEG")
    return resolved


def _parse_tsv(tsv_text: str) -> tuple[str, list[dict[str, Any]], float | None]:
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    lines: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    line_order: list[tuple[int, int, int, int]] = []
    confidences: list[float] = []

    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            key = (
                int(row.get("page_num") or 0),
                int(row.get("block_num") or 0),
                int(row.get("par_num") or 0),
                int(row.get("line_num") or 0),
            )
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
            confidence = float(row.get("conf") or -1)
        except (TypeError, ValueError):
            continue

        if key not in lines:
            lines[key] = {
                "words": [],
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "confidences": [],
            }
            line_order.append(key)
        entry = lines[key]
        entry["words"].append(text)
        entry["left"] = min(entry["left"], left)
        entry["top"] = min(entry["top"], top)
        entry["right"] = max(entry["right"], left + width)
        entry["bottom"] = max(entry["bottom"], top + height)
        if confidence >= 0:
            entry["confidences"].append(confidence)
            confidences.append(confidence)

    public_lines: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for key in line_order[:_MAX_LINES]:
        entry = lines[key]
        line_text = " ".join(entry["words"]).strip()
        if not line_text:
            continue
        line_confidences = entry["confidences"]
        line_confidence = round(sum(line_confidences) / len(line_confidences), 2) if line_confidences else None
        public_lines.append(
            {
                "text": line_text,
                "confidence": line_confidence,
                "bbox": [entry["left"], entry["top"], entry["right"], entry["bottom"]],
            }
        )
        text_parts.append(line_text)

    raw_text = "\n".join(text_parts)
    mean_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
    return raw_text[:_MAX_TEXT_CHARS], public_lines, mean_confidence


def ocr_artifact(paths: RuntimePaths, artifact_path: str, *, psm: int = 6) -> dict[str, Any]:
    if psm not in _ALLOWED_PSM:
        raise OCRError(f"psm must be one of: {', '.join(str(value) for value in sorted(_ALLOWED_PSM))}")
    image_path = _resolve_evidence_image(paths, artifact_path)
    tesseract = _tesseract_path()
    if tesseract is None:
        raise OCRError("Tesseract is not installed or executable")
    tessdata_dir = _preferred_tessdata_dir(paths)

    command = [str(tesseract), str(image_path), "stdout"]
    if tessdata_dir is not None:
        command.extend(["--tessdata-dir", str(tessdata_dir)])
    command.extend(["-l", "+".join(_LANGUAGES), "--psm", str(psm), "-c", "tessedit_create_tsv=1"])

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise OCRError("Tesseract OCR timed out after 60 seconds") from exc
    except OSError as exc:
        raise OCRError(f"Tesseract execution failed: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:1000]
        raise OCRError(f"Tesseract OCR failed ({proc.returncode}): {detail}")
    if len(proc.stdout.encode("utf-8")) > _MAX_TSV_BYTES:
        raise OCRError("Tesseract TSV output exceeded the bounded result size")

    text, lines, mean_confidence = _parse_tsv(proc.stdout)
    try:
        version_proc = subprocess.run(
            [str(tesseract), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        version = None
    else:
        version = version_proc.stdout.splitlines()[0].strip() if version_proc.returncode == 0 and version_proc.stdout else None

    with image_path.open("rb") as handle:
        body = handle.read()
    return {
        "engine": "tesseract",
        "engine_version": version,
        "model_profile": "tessdata_best" if tessdata_dir is not None else "system",
        "languages": list(_LANGUAGES),
        "psm": psm,
        "artifact_path": str(image_path),
        "input_sha256": hashlib.sha256(body).hexdigest(),
        "input_bytes": len(body),
        "text": text,
        "text_truncated": len(text) >= _MAX_TEXT_CHARS,
        "line_count": len(lines),
        "lines": lines,
        "mean_confidence": mean_confidence,
        "network_access": False,
        "result_semantics": "EVIDENCE_ENRICHMENT_ONLY_CRITICAL_FIELDS_REQUIRE_SOURCE_CROSS_CHECK",
    }
