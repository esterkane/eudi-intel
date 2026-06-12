"""Optional authenticated GitHub REST strategy (CLAUDE.md GitHub access policy).

Only used when GITHUB_TOKEN is set AND the source declares an api_url. Uses ETag
conditional requests: a 304 costs a request but transfers nothing and produces
no new snapshot. Token absent (the default) → this module is never called.
"""

from __future__ import annotations

import httpx

from app.collectors.base import CollectResult, content_hash
from app.collectors.registry import SourceSpec


async def collect_github_api(
    spec: SourceSpec,
    client: httpx.AsyncClient,
    token: str,
    previous_etag: str | None,
) -> CollectResult:
    assert spec.api_url is not None  # callers gate on this
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if previous_etag:
        headers["If-None-Match"] = previous_etag

    resp = await client.get(spec.api_url, headers=headers)
    if resp.status_code == 304:
        return CollectResult(
            source_id=spec.id,
            url=spec.api_url,
            status="not_modified",
            content_hash="",
            etag=previous_etag,
        )
    resp.raise_for_status()
    body = resp.content
    return CollectResult(
        source_id=spec.id,
        url=spec.api_url,
        status="fetched",
        content_hash=content_hash(body),
        payload=body.decode("utf-8", errors="replace"),
        etag=resp.headers.get("ETag"),
    )
