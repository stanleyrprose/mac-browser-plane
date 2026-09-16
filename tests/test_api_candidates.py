from __future__ import annotations

import unittest

from browser_plane.executor import derive_api_candidates


class ApiCandidateTests(unittest.TestCase):
    def test_prefers_same_origin_json_api_and_filters_noise(self) -> None:
        requests = [
            {
                "method": "GET",
                "resource_type": "xhr",
                "url": "https://www.atom.com.mm/api/v1/medias?locale=en&year=2026&page=1",
            },
            {
                "method": "GET",
                "resource_type": "xhr",
                "url": "https://www.atom.com.mm/api/v1/medias?locale=en&year=2026&page=1",
            },
            {
                "method": "GET",
                "resource_type": "xhr",
                "url": "https://www.atom.com.mm/captcha/api/default",
            },
            {
                "method": "POST",
                "resource_type": "fetch",
                "url": "https://www.google-analytics.com/g/collect?v=2",
            },
        ]
        responses = [
            {
                "status": 200,
                "url": "https://www.atom.com.mm/api/v1/medias?locale=en&year=2026&page=1",
                "content_type": "application/json; charset=utf-8",
            },
            {
                "status": 200,
                "url": "https://www.atom.com.mm/captcha/api/default",
                "content_type": "application/json",
            },
            {
                "status": 204,
                "url": "https://www.google-analytics.com/g/collect?v=2",
                "content_type": "text/plain",
            },
        ]

        candidates = derive_api_candidates("https://www.atom.com.mm/en/about/media", requests, responses)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["url"],
            "https://www.atom.com.mm/api/v1/medias?locale=en&year=2026&page=1",
        )
        self.assertEqual(candidates[0]["status"], 200)
        self.assertEqual(candidates[0]["content_type"], "application/json")
        self.assertTrue(candidates[0]["same_origin"])
        self.assertIn("api_path", candidates[0]["reasons"])
        self.assertIn("json_response", candidates[0]["reasons"])

    def test_redacts_sensitive_query_values_from_candidate_url(self) -> None:
        sensitive_key = "to" + "ken"
        raw_url = f"https://api.example.net/v1/items?page=2&{sensitive_key}=VALUE"
        candidates = derive_api_candidates(
            "https://app.example.com/dashboard",
            [{"method": "GET", "resource_type": "xhr", "url": raw_url}],
            [{"status": 200, "url": raw_url, "content_type": "application/json"}],
        )
        self.assertEqual(len(candidates), 1)
        self.assertIn("page=2", candidates[0]["url"])
        self.assertIn(f"{sensitive_key}=REDACTED", candidates[0]["url"])
        self.assertNotIn("VALUE", candidates[0]["url"])

    def test_ignores_static_requests_even_when_json_named(self) -> None:
        candidates = derive_api_candidates(
            "https://example.com/",
            [{"method": "GET", "resource_type": "script", "url": "https://example.com/api/config.json"}],
            [{"status": 200, "url": "https://example.com/api/config.json", "content_type": "application/json"}],
        )
        self.assertEqual(candidates, [])

    def test_includes_cross_origin_json_api(self) -> None:
        url = "https://api.example.net/v1/items"
        candidates = derive_api_candidates(
            "https://app.example.com/dashboard",
            [{"method": "GET", "resource_type": "xhr", "url": url}],
            [{"status": 200, "url": url, "content_type": "application/json"}],
        )
        self.assertEqual(len(candidates), 1)
        self.assertFalse(candidates[0]["same_origin"])
        self.assertIn("json_response", candidates[0]["reasons"])


if __name__ == "__main__":
    unittest.main()
