from __future__ import annotations

import json
import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from browser_plane.provider_agent import SshProviderTransport
from browser_plane.translation_provider import (
    CodexOAuthTranslator,
    TranslationProviderError,
    _validate_output,
    request_sha256,
    run_translation_once,
    validate_translation_claim,
)

NOW = datetime(2026, 9, 12, 5, 0, tzinfo=UTC)


def request() -> dict:
    value = {
        "schema_version": 1,
        "translation_request_id": str(uuid.uuid4()),
        "provider_id": "mac-oauth-llm",
        "source_language": "my",
        "target_language": "zh-Hans",
        "values": ["အိတ်ဖွင့်တင်ဒါ 15.9.2026", "ရန်ကုန်"],
        "protected_tokens": [["15.9.2026"], []],
        "requested_at": "2026-09-12T05:00:00Z",
        "expires_at": "2026-09-12T05:02:00Z",
        "cache_key": "a" * 64,
    }
    value["request_sha256"] = request_sha256(value)
    return value


def claim(req: dict) -> dict:
    return {
        "status": "CLAIMED",
        "provider_id": "mac-oauth-llm",
        "translation_request_id": req["translation_request_id"],
        "translation_attempt_id": str(uuid.uuid4()),
        "claim_token": "claim-token",
        "claim_expires_at": "2026-09-12T05:01:00Z",
        "request": req,
    }


class FakeTransport:
    def __init__(self, claim_value: dict):
        self.claim_value = claim_value
        self.submitted: list[dict] = []
        self.failed: list[dict] = []

    def translation_claim(self):
        return self.claim_value

    def translation_submit(self, payload):
        self.submitted.append(payload)
        return {"status": "SUCCEEDED"}

    def translation_fail(self, payload):
        self.failed.append(payload)
        return {"status": "FAILED"}


class FakeTranslator:
    def translate(self, _request):
        return ["公开招标 15.9.2026", "仰光"], {"model": "test-model", "duration_ms": 12, "usage": {"tokens": 20}}


class TranslationProviderTests(unittest.TestCase):
    def test_claim_validation_is_independent_from_browser_pic(self) -> None:
        req = request()
        self.assertIs(validate_translation_claim(claim(req), now=NOW), req)

    def test_tampered_request_is_rejected(self) -> None:
        req = request()
        req["values"][0] = "tampered"
        with self.assertRaisesRegex(TranslationProviderError, "SHA-256"):
            validate_translation_claim(claim(req), now=NOW)

    def test_protected_numbers_and_dates_must_survive(self) -> None:
        req = request()
        self.assertEqual(_validate_output(req, ["公开招标 15.9.2026", "仰光"])[0], "公开招标 15.9.2026")
        with self.assertRaisesRegex(TranslationProviderError, "protected token"):
            _validate_output(req, ["公开招标 16.9.2026", "仰光"])

    def test_run_submits_bounded_translation_result(self) -> None:
        req = request()
        transport = FakeTransport(claim(req))
        result = run_translation_once(transport=transport, translator=FakeTranslator(), now=NOW)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(transport.submitted[0]["values"], ["公开招标 15.9.2026", "仰光"])
        self.assertEqual(transport.submitted[0]["model"], "test-model")
        self.assertEqual(transport.failed, [])

    def test_no_work_does_not_call_translator(self) -> None:
        transport = FakeTransport({"status": "NO_WORK"})

        class BrokenTranslator:
            def translate(self, _request):
                raise AssertionError("must not be called")

        self.assertEqual(run_translation_once(transport=transport, translator=BrokenTranslator())["status"], "NO_WORK")

    def test_codex_invocation_is_ephemeral_read_only_and_schema_bounded(self) -> None:
        req = request()
        done = type(
            "Done",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"translations": ["公开招标 15.9.2026", "仰光"]}, ensure_ascii=False),
                "stderr": "tokens used\n4,816\n",
            },
        )()
        translator = CodexOAuthTranslator(codex_binary="/opt/homebrew/bin/codex", timeout_seconds=10)
        with patch("browser_plane.translation_provider.subprocess.run", return_value=done) as run:
            values, meta = translator.translate(req)
        self.assertEqual(values[0], "公开招标 15.9.2026")
        self.assertEqual(meta["usage"]["tokens"], 4816)
        argv = run.call_args.args[0]
        self.assertIn("--ephemeral", argv)
        self.assertIn("read-only", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertIn("--output-schema", argv)
        self.assertIn("gpt-5.6-luna", argv)
        self.assertNotIn("danger-full-access", argv)
        env = run.call_args.kwargs["env"]
        self.assertEqual(set(env), {"HOME", "PATH", "LANG"})

    def test_legacy_bkk_wrapper_without_translation_commands_is_nonfatal(self) -> None:
        transport = SshProviderTransport("sf-provider-bangkok", "/tmp/key")
        denied = type(
            "Done",
            (),
            {
                "returncode": 126,
                "stdout": b'{"status":"DENY","error":"unsupported provider command"}',
                "stderr": b"",
            },
        )()
        with patch("browser_plane.provider_agent.subprocess.run", return_value=denied):
            result = transport.translation_claim()
        self.assertEqual(result["status"], "NO_WORK")
        self.assertEqual(result["compatibility"], "TRANSLATION_COMMAND_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
