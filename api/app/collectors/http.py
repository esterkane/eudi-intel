"""HTTP-based collectors: feed (atom), crawl (static pages), scrape (list pages).

All three fetch a URL and snapshot the raw body; extraction/parsing is Phase 2.
They share one implementation because at the snapshot layer the only difference
is the source's declared method (which Phase 2 parsers dispatch on).

Dedupe note: GitHub HTML embeds per-request tokens (request-id, html-safe-nonce,
data-csrf values), so hashing the raw body would register a "new" snapshot on
every fetch of an unchanged page. The content hash is therefore computed over a
normalized form with those volatile attributes blanked; the stored payload stays
raw and untouched.
"""

from __future__ import annotations

import re

import httpx

from app.collectors.base import CollectResult, content_hash
from app.collectors.registry import SourceSpec

_VOLATILE_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb'name="request-id" content="[^"]*"'),
    re.compile(rb'name="html-safe-nonce" content="[^"]*"'),
    re.compile(rb'name="visitor-payload" content="[^"]*"'),
    re.compile(rb'name="visitor-hmac" content="[^"]*"'),
    # value= may be separated from data-csrf by other attrs (authenticity_token)
    re.compile(rb'data-csrf="true"[^>]*?value="[^"]*"'),
)

# Atom feeds: the feed-level <updated> (always the FIRST one, before any <entry>)
# is stamped with the request time when the feed is empty. Entry-level <updated>
# elements are meaningful content and stay in the hash.
_FEED_LEVEL_UPDATED = re.compile(rb"<updated>[^<]*</updated>")


def normalize_for_hash(body: bytes) -> bytes:
    for pattern in _VOLATILE_PATTERNS:
        body = pattern.sub(b"", body)
    body = _FEED_LEVEL_UPDATED.sub(b"<updated/>", body, count=1)
    return body


async def collect_http(spec: SourceSpec, client: httpx.AsyncClient) -> CollectResult:
    resp = await client.get(spec.url)
    resp.raise_for_status()
    body = resp.content
    return CollectResult(
        source_id=spec.id,
        url=spec.url,
        status="fetched",
        content_hash=content_hash(normalize_for_hash(body)),
        payload=body.decode(resp.encoding or "utf-8", errors="replace"),
    )
