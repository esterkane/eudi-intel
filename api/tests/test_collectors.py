"""Collector unit tests — offline (httpx.MockTransport; local tmp git repo)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest

from app.collectors.git import collect_git
from app.collectors.github_api import collect_github_api
from app.collectors.http import collect_http
from app.collectors.registry import SourceSpec
from app.models.source import FetchMethod, Tier

FEED_SPEC = SourceSpec(
    id="test_feed",
    title="test feed",
    tier=Tier.roadmap,
    method=FetchMethod.feed,
    url="https://example.org/releases.atom",
    api_url="https://api.github.com/repos/o/r/releases",
)


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_collect_http_hashes_body() -> None:
    body = b"<feed><entry>v1.0</entry></feed>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with _client(handler) as client:
        result = await collect_http(FEED_SPEC, client)
    assert result.status == "fetched"
    assert result.payload is not None and "v1.0" in result.payload
    assert len(result.content_hash) == 64
    # Same body → same hash (dedupe key stability)
    async with _client(handler) as client:
        again = await collect_http(FEED_SPEC, client)
    assert again.content_hash == result.content_hash


async def test_volatile_github_attributes_do_not_change_hash() -> None:
    """Per-request tokens in GitHub HTML must not defeat snapshot dedupe."""
    template = (
        '<html><meta name="request-id" content="{rid}" data-pjax-transient="true"/>'
        '<meta name="html-safe-nonce" content="{nonce}"/>'
        '<meta name="visitor-payload" content="{rid}base64=="/>'
        '<meta name="visitor-hmac" content="{nonce}hmac"/>'
        '<form><input type="hidden" data-csrf="true" value="{csrf}" /></form>'
        '<form><input type="hidden" data-csrf="true" name="authenticity_token"'
        ' value="{csrf}tok" /></form>'
        "<div>issue #1: real content</div></html>"
    )
    varied = iter(
        [
            template.format(rid="AAA:111", nonce="n1", csrf="c1==").encode(),
            template.format(rid="BBB:222", nonce="n2", csrf="c2==").encode(),
            template.format(rid="CCC:333", nonce="n3", csrf="c3==").encode().replace(
                b"issue #1", b"issue #2"
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=next(varied))

    async with _client(handler) as client:
        first = await collect_http(FEED_SPEC, client)
        second = await collect_http(FEED_SPEC, client)
        third = await collect_http(FEED_SPEC, client)

    # tokens changed, content identical → same hash
    assert second.content_hash == first.content_hash
    # actual content changed → different hash
    assert third.content_hash != first.content_hash
    # raw payload is stored untouched (tokens still present)
    assert second.payload is not None and 'content="n2"' in second.payload


async def test_empty_feed_request_timestamp_does_not_change_hash() -> None:
    """Feed-level <updated> is request-stamped on empty feeds; entry-level is content."""
    feed = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<updated>{feed_ts}</updated>{entries}</feed>"
    )
    entry = "<entry><title>v1</title><updated>2026-01-01T00:00:00Z</updated></entry>"
    bodies = iter(
        [
            feed.format(feed_ts="2026-06-12T06:35:58Z", entries="").encode(),
            feed.format(feed_ts="2026-06-12T06:38:53Z", entries="").encode(),
            feed.format(feed_ts="2026-06-12T06:40:00Z", entries=entry).encode(),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=next(bodies))

    async with _client(handler) as client:
        first = await collect_http(FEED_SPEC, client)
        second = await collect_http(FEED_SPEC, client)
        third = await collect_http(FEED_SPEC, client)

    assert second.content_hash == first.content_hash  # only request stamp moved
    assert third.content_hash != first.content_hash  # a real entry appeared


async def test_collect_http_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await collect_http(FEED_SPEC, client)


async def test_github_api_sends_token_and_etag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok123"
        if request.headers.get("If-None-Match") == 'W/"abc"':
            return httpx.Response(304)
        return httpx.Response(200, json=[{"tag_name": "v1"}], headers={"ETag": 'W/"abc"'})

    async with _client(handler) as client:
        first = await collect_github_api(FEED_SPEC, client, "tok123", None)
        assert first.status == "fetched"
        assert first.etag == 'W/"abc"'

        second = await collect_github_api(FEED_SPEC, client, "tok123", first.etag)
        assert second.status == "not_modified"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


async def test_collect_git_clone_and_idempotent_refetch(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-b", "main", cwd=origin)
    (origin / "doc.md").write_text("# hello")
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "c1", cwd=origin)

    spec = SourceSpec(
        id="test_repo", title="t", tier=Tier.reference, method=FetchMethod.git,
        url=str(origin),
    )
    repos = tmp_path / "mirrors"

    first = await collect_git(spec, repos)
    assert first.payload_ref == str(repos / "test_repo")
    assert (repos / "test_repo" / "doc.md").exists()

    # Re-run with no new commits → identical content hash (dedupe key)
    second = await collect_git(spec, repos)
    assert second.content_hash == first.content_hash

    # New commit upstream → new hash after refetch
    (origin / "doc.md").write_text("# hello v2")
    _git("commit", "-am", "c2", cwd=origin)
    third = await collect_git(spec, repos)
    assert third.content_hash != first.content_hash
    assert (repos / "test_repo" / "doc.md").read_text() == "# hello v2"
