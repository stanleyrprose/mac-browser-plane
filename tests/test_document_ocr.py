from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from browser_plane.config import RuntimePaths
from browser_plane.document_ocr import DocumentOCRError, ocr_document


def _paths(root: Path) -> RuntimePaths:
    state = root / "state"
    paths = RuntimePaths(
        root=root,
        state_dir=state,
        evidence_dir=root / "evidence",
        profiles_dir=root / "profiles",
        auth_state_dir=root / "auth-state",
        logs_dir=root / "logs",
        run_dir=root / "run",
        db_path=state / "runtime.db",
    )
    paths.ensure()
    return paths


class DocumentOCRTests(unittest.TestCase):
    def test_runtime_owned_pdf_is_rasterized_ocrd_and_temp_pages_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            pdf = paths.evidence_dir / "input.pdf"
            body = b"%PDF-1.4\nfixture"
            pdf.write_bytes(body)

            def rasterize(_pdf: Path, output_dir: Path, *, max_pages: int):
                self.assertEqual(max_pages, 12)
                (output_dir / "page-001.png").write_bytes(b"png1")
                (output_dir / "page-002.png").write_bytes(b"png2")
                return {"page_count": 2, "rasterized_pages": 2, "page_limit_truncated": False}

            def fake_ocr(_paths, artifact_path: str, *, psm: int):
                page = Path(artifact_path).name
                index = 1 if page == "page-001.png" else 2
                return {
                    "model_profile": "tessdata_best",
                    "languages": ["mya", "eng"],
                    "input_sha256": hashlib.sha256(f"png{index}".encode()).hexdigest(),
                    "input_bytes": 4,
                    "text": f"page {index} text",
                    "text_truncated": False,
                    "line_count": index,
                    "mean_confidence": 70.0 + index,
                }

            with patch("browser_plane.document_ocr._rasterize_pdf", side_effect=rasterize), patch(
                "browser_plane.document_ocr.ocr_artifact", side_effect=fake_ocr
            ):
                result = ocr_document(paths, "input.pdf", psm=6, max_pages=12)

            self.assertEqual(result["input_sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(result["page_count"], 2)
            self.assertEqual(result["processed_pages"], 2)
            self.assertFalse(result["page_limit_truncated"])
            self.assertEqual(result["mean_confidence"], 71.5)
            self.assertIn("page 1 text", result["text"])
            self.assertIn("page 2 text", result["text"])
            self.assertFalse(result["network_access"])
            self.assertFalse(result["intermediate_images_retained"])
            self.assertEqual(list(paths.evidence_dir.glob("document-ocr-*")), [])

    def test_rejects_path_escape_non_pdf_bad_magic_and_invalid_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root / "runtime")
            outside = root / "outside.pdf"
            outside.write_bytes(b"%PDF-1.4")
            with self.assertRaisesRegex(DocumentOCRError, "inside the Browser Plane evidence directory"):
                ocr_document(paths, str(outside))

            image = paths.evidence_dir / "x.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            with self.assertRaisesRegex(DocumentOCRError, "PDF evidence only"):
                ocr_document(paths, "x.png")

            bad = paths.evidence_dir / "bad.pdf"
            bad.write_bytes(b"not pdf")
            with self.assertRaisesRegex(DocumentOCRError, "signature is not PDF"):
                ocr_document(paths, "bad.pdf")

            good = paths.evidence_dir / "good.pdf"
            good.write_bytes(b"%PDF-1.4")
            with self.assertRaisesRegex(DocumentOCRError, "max_pages"):
                ocr_document(paths, "good.pdf", max_pages=0)


if __name__ == "__main__":
    unittest.main()
