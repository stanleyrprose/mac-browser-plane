from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from browser_plane.config import RuntimePaths
from browser_plane.ocr import OCRError, _parse_tsv, ocr_artifact


class OCRContractTests(unittest.TestCase):
    def _paths(self, root: Path) -> RuntimePaths:
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

    def test_parse_tsv_reconstructs_lines_bbox_and_confidence(self) -> None:
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t90\tTender\n"
            "5\t1\t1\t1\t1\t2\t45\t20\t40\t10\t80\t10DMS\n"
            "5\t1\t1\t1\t2\t1\t10\t40\t70\t10\t70\tImaging\n"
        )
        text, lines, mean = _parse_tsv(tsv)
        self.assertEqual(text, "Tender 10DMS\nImaging")
        self.assertEqual(lines[0]["bbox"], [10, 20, 85, 30])
        self.assertEqual(lines[0]["confidence"], 85.0)
        self.assertEqual(mean, 80.0)

    def test_artifact_must_stay_inside_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            outside = root / "outside.png"
            outside.write_bytes(b"\x89PNG\r\n\x1a\nrest")
            with self.assertRaisesRegex(OCRError, "inside the Browser Plane evidence directory"):
                ocr_artifact(paths, str(outside))

    def test_artifact_rejects_non_image_and_signature_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            text = paths.evidence_dir / "job" / "scan.txt"
            text.parent.mkdir()
            text.write_text("hello", encoding="utf-8")
            with self.assertRaisesRegex(OCRError, "PNG and JPEG"):
                ocr_artifact(paths, str(text))

            fake_png = text.with_name("scan.png")
            fake_png.write_bytes(b"not-a-png")
            with self.assertRaisesRegex(OCRError, "signature is not PNG"):
                ocr_artifact(paths, str(fake_png))

    def test_ocr_artifact_is_networkless_bounded_evidence_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            image = paths.evidence_dir / "job-1" / "scan.png"
            image.parent.mkdir()
            image_bytes = b"\x89PNG\r\n\x1a\nfixture"
            image.write_bytes(image_bytes)
            tsv = (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t1\t2\t10\t4\t95\t10DMS\n"
                "5\t1\t1\t1\t1\t2\t12\t2\t20\t4\t85\tImaging\n"
            )
            calls = [
                SimpleNamespace(returncode=0, stdout=tsv, stderr=""),
                SimpleNamespace(returncode=0, stdout="tesseract 5.5.3\n", stderr=""),
            ]
            with (
                patch("browser_plane.ocr._tesseract_path", return_value=Path("/opt/homebrew/bin/tesseract")),
                patch("browser_plane.ocr._preferred_tessdata_dir", return_value=None),
                patch("browser_plane.ocr.subprocess.run", side_effect=calls) as run,
            ):
                result = ocr_artifact(paths, str(image), psm=4)

            self.assertEqual(result["text"], "10DMS Imaging")
            self.assertEqual(result["languages"], ["mya", "eng"])
            self.assertEqual(result["psm"], 4)
            self.assertEqual(result["input_sha256"], hashlib.sha256(image_bytes).hexdigest())
            self.assertEqual(result["mean_confidence"], 90.0)
            self.assertFalse(result["network_access"])
            self.assertEqual(
                result["result_semantics"],
                "EVIDENCE_ENRICHMENT_ONLY_CRITICAL_FIELDS_REQUIRE_SOURCE_CROSS_CHECK",
            )
            ocr_command = run.call_args_list[0].args[0]
            self.assertNotIn("http://", " ".join(ocr_command))
            self.assertNotIn("https://", " ".join(ocr_command))

    def test_unsupported_psm_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            with self.assertRaisesRegex(OCRError, "psm must be one of"):
                ocr_artifact(paths, "ignored.png", psm=3)


if __name__ == "__main__":
    unittest.main()
