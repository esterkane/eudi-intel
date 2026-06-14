"""Phase 2 orchestration: snapshots + mirrors → Documents/Sections/entities.

Flow per ingestion-pipeline skill: parse → chunk → tier → diff. Embedding is
Phase 3. Plain async functions (no FastAPI coupling) for later Celery reuse.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.registry import REGISTRY, SourceSpec
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.entities import Discussion, Issue, PullRequest, Version
from app.models.source import FetchMethod, SourceSnapshot
from app.parsers.feature_map import parse_feature_map
from app.parsers.feeds import parse_atom, tag_from_release_url
from app.parsers.github_lists import (
    parse_discussion_list,
    parse_issue_list,
    parse_issue_list_json,
    parse_pull_list,
    parse_pull_list_json,
)
from app.parsers.html import chunk_html, html_to_markdown
from app.parsers.markdown import chunk_markdown, doc_title
from app.parsers.tiering import tier_for_repo_file
from app.services.entity_upserts import (
    upsert_document,
    upsert_github_items,
    upsert_release,
    upsert_roadmap_items,
    upsert_version,
)
from app.services.version_diff import compute_version_diff

# feed source → the repo-source whose domain entities it feeds
_FEED_TO_REPO = {
    "arf_releases_feed": "arf_repo",
    "arf_tags_feed": "arf_repo",
    "arf_commits_feed": "arf_repo",
    "sts_releases_feed": "sts_repo",
}
_GITHUB_REPO = re.compile(r"https://github\.com/([^/]+/[^/.]+)")


class ParseReport(BaseModel):
    documents: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}
    sections: int = 0
    versions_new: int = 0
    releases_new: int = 0
    issues_new: int = 0
    pulls_new: int = 0
    discussions_new: int = 0
    roadmap_items_new: int = 0
    diffs_computed: list[str] = []
    errors: list[str] = []


async def _latest_snapshot(session: AsyncSession, source_id: str) -> SourceSnapshot | None:
    snapshot: SourceSnapshot | None = await session.scalar(
        select(SourceSnapshot)
        .where(SourceSnapshot.source_id == source_id)
        .order_by(SourceSnapshot.fetched_at.desc())
        .limit(1)
    )
    return snapshot




def _repo_slug(spec: SourceSpec) -> str:
    match = _GITHUB_REPO.search(spec.url)
    if match is None:
        raise ValueError(f"source {spec.id} has no GitHub repo URL")
    return match.group(1)


async def _parse_repo_docs(
    session: AsyncSession, spec: SourceSpec, settings: Settings, report: ParseReport
) -> None:
    mirror = Path(settings.repos_dir) / spec.id
    repo = _repo_slug(spec)
    md_files = sorted(
        p for p in mirror.rglob("*.md") if ".git" not in p.parts
    )
    for path in md_files:
        relpath = path.relative_to(mirror).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        url = f"https://github.com/{repo}/blob/main/{relpath}"
        tier = tier_for_repo_file(spec.id, relpath)
        chunks = chunk_markdown(text, base_url=url)
        outcome = await upsert_document(
            session,
            source_id=spec.id,
            url=url,
            title=doc_title(text, path.name),
            tier=tier,
            doc_type="markdown",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            chunks=chunks,
            version_or_tag="main",
        )
        report.documents[outcome] += 1
        if outcome != "unchanged":
            report.sections += len(chunks)


async def _parse_crawl_page(
    session: AsyncSession, spec: SourceSpec, report: ParseReport
) -> None:
    snapshot = await _latest_snapshot(session, spec.id)
    if snapshot is None or snapshot.payload is None:
        report.errors.append(f"{spec.id}: no snapshot to parse")
        return
    markdown = html_to_markdown(snapshot.payload)
    if not markdown:
        report.errors.append(f"{spec.id}: extraction produced no content")
        return
    chunks = chunk_html(snapshot.payload, spec.url)
    outcome = await upsert_document(
        session,
        source_id=spec.id,
        url=spec.url,
        title=doc_title(markdown, spec.title),
        tier=spec.tier,
        doc_type="html",
        content_hash=hashlib.sha256(markdown.encode()).hexdigest(),
        chunks=chunks,
    )
    report.documents[outcome] += 1
    if outcome != "unchanged":
        report.sections += len(chunks)

    if spec.id == "refimpl_feature_map":
        items = parse_feature_map(snapshot.payload, spec.url)
        report.roadmap_items_new += await upsert_roadmap_items(session, items, spec.url)


async def _parse_feed(session: AsyncSession, spec: SourceSpec, report: ParseReport) -> None:
    snapshot = await _latest_snapshot(session, spec.id)
    if snapshot is None or snapshot.payload is None:
        report.errors.append(f"{spec.id}: no snapshot to parse")
        return
    entries = parse_atom(snapshot.payload)
    repo_source = _FEED_TO_REPO.get(spec.id, spec.id)
    for entry in entries:
        if spec.id.endswith("_tags_feed"):
            if await upsert_version(
                session,
                source_id=repo_source,
                tag=entry.title,
                url=entry.url,
                published_at=entry.updated,
            ):
                report.versions_new += 1
        elif spec.id.endswith("_releases_feed"):
            tag = tag_from_release_url(entry.url)
            if await upsert_release(
                session,
                source_id=repo_source,
                title=entry.title,
                url=entry.url,
                published_at=entry.updated,
                summary=None,
            ):
                report.releases_new += 1
            if tag and await upsert_version(
                session,
                source_id=repo_source,
                tag=tag,
                url=entry.url,
                published_at=entry.updated,
            ):
                report.versions_new += 1
        # commits feeds stay raw: they power "Current Activity" straight from
        # snapshots in Phase 6; no entity for individual commits.


def _is_json_payload(payload: str) -> bool:
    return payload.lstrip()[:1] in ("[", "{")


async def _parse_scrape(session: AsyncSession, spec: SourceSpec, report: ParseReport) -> None:
    snapshot = await _latest_snapshot(session, spec.id)
    if snapshot is None or snapshot.payload is None:
        report.errors.append(f"{spec.id}: no snapshot to parse")
        return
    repo = _repo_slug(spec)
    # Token-free snapshots are HTML; with a token the snapshot is REST JSON.
    rest = _is_json_payload(snapshot.payload)
    if spec.id.endswith("_issues"):
        items = (
            parse_issue_list_json(snapshot.payload, repo)
            if rest
            else parse_issue_list(snapshot.payload, repo)
        )
        report.issues_new += await upsert_github_items(session, items, Issue)
    elif spec.id.endswith("_pulls"):
        items = (
            parse_pull_list_json(snapshot.payload, repo)
            if rest
            else parse_pull_list(snapshot.payload, repo)
        )
        report.pulls_new += await upsert_github_items(session, items, PullRequest)
    elif spec.id.endswith("_discussions"):
        # Discussions are not in the REST bucket → always HTML.
        report.discussions_new += await upsert_github_items(
            session, parse_discussion_list(snapshot.payload, repo), Discussion
        )


def _semver_key(tag: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", tag)
    return tuple(int(n) for n in numbers[:4]) or (0,)


async def reingest_new_tags(settings: Settings, report: ParseReport | None = None) -> ParseReport:
    """Targeted re-ingest on version bumps (BUILD_PLAN Phase 8): when the two
    newest ARF tags have no stored diff, compute it (shallow tag fetch) and
    ensure the newest tag is indexed in the history collection. Idempotent —
    safe to call on every feeds poll."""
    report = report or ParseReport()
    async with SessionLocal() as session:
        try:
            tags = list(
                await session.scalars(select(Version.tag).where(Version.source_id == "arf_repo"))
            )
            if len(tags) < 2:
                report.errors.append("arf_repo: fewer than two versions known, no diff computed")
                return report
            ordered = sorted(tags, key=_semver_key)
            from_tag, to_tag = ordered[-2], ordered[-1]
            mirror = Path(settings.repos_dir) / "arf_repo"
            await compute_version_diff(
                session, source_id="arf_repo", mirror=mirror, from_tag=from_tag, to_tag=to_tag
            )
            await session.commit()
            report.diffs_computed.append(f"arf_repo: {from_tag} → {to_tag}")
        except Exception as exc:  # noqa: BLE001 - diff failure is reportable, not fatal
            await session.rollback()
            report.errors.append(f"version diff: {exc}")
            return report
    # history index for the newest tag (skips when already present)
    from app.services.vector_index import index_history_tag

    try:
        indexed = await index_history_tag(settings, to_tag)
        if indexed:
            report.diffs_computed.append(f"history indexed {to_tag}: {indexed} chunks")
    except Exception as exc:  # noqa: BLE001 - reportable, not fatal
        report.errors.append(f"history index {to_tag}: {exc}")
    return report


async def parse_for_methods(
    settings: Settings, methods: set[FetchMethod]
) -> ParseReport:
    """Parse latest snapshots/mirrors for sources of the given methods only —
    the unit of work for the per-cadence Beat tasks."""
    report = ParseReport()
    async with SessionLocal() as session:
        for spec in REGISTRY:
            if spec.method not in methods:
                continue
            # Parsing failures must not abort the whole run; report per source.
            try:
                if spec.method == FetchMethod.git:
                    await _parse_repo_docs(session, spec, settings, report)
                elif spec.method == FetchMethod.crawl:
                    await _parse_crawl_page(session, spec, report)
                elif spec.method == FetchMethod.feed:
                    await _parse_feed(session, spec, report)
                elif spec.method == FetchMethod.scrape:
                    await _parse_scrape(session, spec, report)
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - isolate per-source failures
                await session.rollback()
                report.errors.append(f"{spec.id}: {exc}")
    return report


async def parse_all(settings: Settings) -> ParseReport:
    report = await parse_for_methods(
        settings,
        {FetchMethod.git, FetchMethod.crawl, FetchMethod.feed, FetchMethod.scrape},
    )
    return await reingest_new_tags(settings, report)
