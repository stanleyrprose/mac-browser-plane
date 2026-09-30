from __future__ import annotations

from dataclasses import dataclass

import curl_cffi
from curl_cffi import CurlFollow


MAX_C0_BODY_BYTES = 1_000_000
CURL_CLIENT_COMPAT_ERROR_CODES = frozenset({16, 35, 52, 56, 92})
_CHALLENGE_MARKERS = (
    ("cloudflare", (b"cf-chl-", b"__cf_chl_", b"challenge-platform", b"challenges.cloudflare.com")),
    ("akamai", (b"errors.edgesuite.net", b"akamai bot manager")),
    ("datadome", (b"geo.captcha-delivery.com", b"datadome.co/captcha", b"datadome captcha")),
)


class C0BodyTooLarge(RuntimeError):
    pass


@dataclass(frozen=True)
class C0TransportResponse:
    url: str
    status: int
    content_type: str | None
    body: bytes


def curl_error_supports_impersonated_retry(returncode: int) -> bool:
    return returncode in CURL_CLIENT_COMPAT_ERROR_CODES


def browser_challenge_evidence(
    status: int,
    content_type: str | None,
    body: bytes,
) -> str | None:
    if not body:
        return None

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type and not (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/xhtml+xml"}
    ):
        return None

    sample = body[:262_144].lower()
    for provider, markers in _CHALLENGE_MARKERS:
        if any(marker in sample for marker in markers):
            return f"{provider}_challenge"

    if status in {403, 503} and b"<title>just a moment...</title>" in sample:
        return "cloudflare_challenge"

    return None


def fetch_impersonated(
    url: str,
    *,
    timeout_sec: int,
    max_bytes: int = MAX_C0_BODY_BYTES,
) -> C0TransportResponse:
    body = bytearray()

    def capture(chunk: bytes) -> None:
        if len(body) + len(chunk) > max_bytes:
            raise C0BodyTooLarge(f"C0 response exceeded {max_bytes} bytes")
        body.extend(chunk)

    response = curl_cffi.get(
        url,
        impersonate="chrome",
        timeout=timeout_sec,
        allow_redirects=CurlFollow.SAFE,
        content_callback=capture,
    )
    return C0TransportResponse(
        url=str(response.url),
        status=int(response.status_code),
        content_type=response.headers.get("content-type"),
        body=bytes(body),
    )
