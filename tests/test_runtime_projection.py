from __future__ import annotations

import unittest

from browser_plane.runtime_projection import project_doctor, project_immediate_ocr, project_job


class RuntimeProjectionTests(unittest.TestCase):
    def test_doctor_maps_native_readiness_to_conditions(self) -> None:
        projection = project_doctor(
            {
                "status": "DEGRADED",
                "checks": [
                    {"name": "sqlite_integrity", "ok": True},
                    {"name": "document_ocr", "ok": False},
                ],
            },
            "/private/doctor.json",
        )
        self.assertEqual(projection["runtime_state"]["operational_state"], "degraded")
        self.assertEqual(projection["job_state"], None)
        self.assertEqual(projection["verification_state"]["status"], "not_required")
        self.assertEqual(
            [item["status"] for item in projection["runtime_state"]["conditions"]],
            ["True", "False"],
        )
        self.assertEqual(projection["artifacts"][0]["private_ref"], "/private/doctor.json")

    def test_browser_job_success_does_not_claim_business_verification(self) -> None:
        row = {
            "job_id": "job-1",
            "state": "SUCCEEDED",
            "failure_class": None,
            "partial_effect_possible": 0,
        }
        projection = project_job(
            row,
            {
                "artifact_path": "/private/response.html",
                "sha256": "a" * 64,
                "body_bytes": 123,
                "content_quality": {"status": "PASS", "gate": "nonempty_rendered_body_v1"},
            },
        )
        self.assertEqual(projection["job_state"]["state"], "succeeded")
        self.assertEqual(projection["verification_state"]["status"], "unknown")
        self.assertEqual(projection["verification_state"]["reason"], "CALLER_VERIFICATION_REQUIRED")
        self.assertEqual(projection["verification_state"]["checks"][0]["status"], "pass")
        self.assertEqual(projection["artifacts"][0]["sha256"], "a" * 64)

    def test_document_ocr_success_remains_source_cross_check_required(self) -> None:
        projection = project_immediate_ocr(
            "document_ocr",
            {
                "input_sha256": "b" * 64,
                "input_bytes": 456,
                "network_access": False,
                "result_semantics": "EVIDENCE_ENRICHMENT_ONLY_CRITICAL_FIELDS_REQUIRE_SOURCE_CROSS_CHECK",
                "pages": [{"image_sha256": "c" * 64, "image_bytes": 789}],
            },
            "/private/source.pdf",
        )
        self.assertEqual(projection["job_state"]["state"], "succeeded")
        self.assertEqual(projection["verification_state"]["status"], "unknown")
        self.assertEqual(projection["verification_state"]["reason"], "SOURCE_CROSS_CHECK_REQUIRED")
        self.assertEqual(projection["artifacts"][0]["kind"], "ocr_input")
        self.assertFalse(projection["artifacts"][1]["retained"])


if __name__ == "__main__":
    unittest.main()
