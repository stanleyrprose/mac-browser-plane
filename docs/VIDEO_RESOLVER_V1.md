# Video Resolver v1

**Status:** local capability implementation  
**Date:** 2026-09-28

## Goal

Provide a bounded, read-only video resolution capability for local agents before they download media.

The resolver answers:

- what single public video the URL represents;
- which playable formats are currently visible;
- which bounded resolver strategy succeeded;
- which strategy hint a caller should reuse for a subsequent yt-dlp download.

It does **not** download media and does not return signed media URLs.

## Boundary

video_resolve is orthogonal to C0-C3, like OCR. It does not become C4 and does not create a second Browser worker.

v1 is deliberately small:

- one public HTTP(S) video URL at a time;
- anonymous session only;
- no personal Chrome profile;
- no account-session import;
- no playlist expansion;
- no media bytes;
- no signed stream URL output;
- SignalForge Provider authorization remains disabled.

The caller continues to own planning and the actual download.

## Backend

The backend is pinned yt-dlp with its default extras. A supported JavaScript runtime is required; Node is preferred and Deno is accepted.

Production install uses the project video optional dependency so the resolver does not depend on an unrelated system Python package.

## YouTube strategy

The resolver tries a bounded sequence:

1. youtube-default
2. youtube-mweb
3. youtube-web-safari-hls

The sequence is evidence-driven rather than a claim that one client is universally superior. The default path preserves yt-dlp upstream behavior. mweb is a quick fallback when the default YouTube path stalls or changes. web_safari remains a final HLS-oriented fallback.

The user-supplied total timeout is divided across remaining strategies. Each yt-dlp attempt also has bounded socket timeout and retry settings, so one stalled YouTube endpoint cannot consume a fresh full timeout for every fallback.

## Safety and privacy

The resolver invokes yt-dlp with --ignore-config. This prevents a user-level yt-dlp config from silently importing browser state or changing the resolver's anonymous v1 contract.

Returned format objects deliberately omit direct media URLs and request headers. Error text strips HTTP(S) URLs before it is returned.

The capability manifest exposes the contract as:

- session_mode = anonymous_only_v1
- signed_stream_urls_returned = false
- signalforge_provider_authorized = false

## Download Agent contract

A local download agent should use:

~~~text
video_resolve(url)
    -> metadata + formats + download_hint
    -> caller-owned yt-dlp download
~~~

download_hint.strategy records the successful strategy. download_hint.extractor_args is either null or a bounded yt-dlp extractor argument such as the selected YouTube client.

For a successful default strategy, the caller should use its normal yt-dlp download path.

When extractor_args is non-null, the caller may reuse that exact strategy for the subsequent download. The caller remains responsible for destination, filename policy, media selection, verification, and any platform-specific authorization rules.

The existing Douyin routing contract remains authoritative for Douyin links; this resolver does not replace the Douyin project's browser/session handling.

## Live verification

A real public YouTube smoke on 2026-09-28 used:

~~~text
browserctl video-resolve <public-youtube-url> --timeout 45 --max-formats 8
~~~

Observed result:

- status: RESOLVED
- strategy: youtube-default
- elapsed: about 3.3 seconds
- playable format count: 43
- visible video ceiling: 2160p / 4K
- signed stream URLs returned: false

The result is a point-in-time external-source check, not a guarantee that YouTube will keep the same protocol behavior.

## Reopen gates

Do not add a managed YouTube challenge-proof service, account-session support, or a dedicated browser sidecar merely because upstream supports it.

Reopen only when repeated real failures show that the bounded anonymous strategy is insufficient for the user's actual download workloads. Any future browser-backed proof provider must integrate with Browser Plane process ownership rather than launching an untracked browser.
