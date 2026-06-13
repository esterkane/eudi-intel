"""Ingestion endpoints (Phase 1): trigger collectors, inspect snapshot state."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.collectors.registry import REGISTRY, get_source
from app.collectors.runner import SourceRunReport, run_all, run_sources
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.entities import (
    Discussion,
    Document,
    Issue,
    PullRequest,
    Release,
    RoadmapItem,
    Section,
    Version,
    VersionDiff,
)
from app.models.source import SourceSnapshot
from app.services.deep_ingest import DeepIngestReport, deep_ingest_activity
from app.services.parse_pipeline import ParseReport, parse_all

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRunResponse(BaseModel):
    results: list[SourceRunReport]


class SnapshotSummaryRow(BaseModel):
    source_id: str
    snapshots: int
    last_seen_at: str


class SnapshotSummaryResponse(BaseModel):
    total: int
    sources: list[SnapshotSummaryRow]


@router.post("/run-all", response_model=IngestRunResponse)
async def ingest_run_all() -> IngestRunResponse:
    return IngestRunResponse(results=await run_all(get_settings()))


@router.post("/run/{source_id}", response_model=IngestRunResponse)
async def ingest_run_one(source_id: str) -> IngestRunResponse:
    spec = get_source(source_id)
    if spec is None:
        known = ", ".join(s.id for s in REGISTRY)
        raise HTTPException(status_code=404, detail=f"unknown source '{source_id}'; known: {known}")
    return IngestRunResponse(results=await run_sources((spec,), get_settings()))


@router.post("/parse-all", response_model=ParseReport)
async def ingest_parse_all() -> ParseReport:
    return await parse_all(get_settings())


@router.post("/deep-activity", response_model=DeepIngestReport)
async def ingest_deep_activity(limit: int = Query(default=40, ge=1, le=200)) -> DeepIngestReport:
    """Phase S1: fetch issue/PR/discussion bodies into the searchable corpus."""
    return await deep_ingest_activity(get_settings(), limit=limit)


class EntityCountsResponse(BaseModel):
    documents: int
    sections: int
    versions: int
    releases: int
    issues: int
    pull_requests: int
    discussions: int
    roadmap_items: int
    version_diffs: int
    documents_by_tier: dict[str, int]


@router.get("/entities", response_model=EntityCountsResponse)
async def entity_counts() -> EntityCountsResponse:
    async with SessionLocal() as session:

        async def count(model: type) -> int:
            return (
                await session.scalar(select(func.count()).select_from(model))
            ) or 0

        tier_rows = (
            await session.execute(
                select(Document.tier, func.count(Document.id)).group_by(Document.tier)
            )
        ).all()
        return EntityCountsResponse(
            documents=await count(Document),
            sections=await count(Section),
            versions=await count(Version),
            releases=await count(Release),
            issues=await count(Issue),
            pull_requests=await count(PullRequest),
            discussions=await count(Discussion),
            roadmap_items=await count(RoadmapItem),
            version_diffs=await count(VersionDiff),
            documents_by_tier={str(tier): n for tier, n in tier_rows},
        )


class EmbedTriggerResponse(BaseModel):
    task_id: str


class EmbedStatusResponse(BaseModel):
    sections_total: int
    sections_pending: int
    latest_points: int
    history_points: int


@router.post("/embed", response_model=EmbedTriggerResponse)
async def trigger_embed() -> EmbedTriggerResponse:
    """Enqueue the embed-and-index task in the Celery worker (background)."""
    from app.worker.tasks import embed_and_index

    result = embed_and_index.delay()
    return EmbedTriggerResponse(task_id=result.id)


@router.get("/embed/status", response_model=EmbedStatusResponse)
async def embed_status() -> EmbedStatusResponse:
    from app.db.qdrant import count_points

    settings = get_settings()
    async with SessionLocal() as session:
        total = (await session.scalar(select(func.count()).select_from(Section))) or 0
        pending = (
            await session.scalar(
                select(func.count())
                .select_from(Section)
                .where(
                    (Section.embedded_hash.is_(None))
                    | (Section.embedded_hash != Section.content_hash)
                )
            )
        ) or 0
    try:
        latest = await count_points(settings.qdrant_latest_collection)
        history = await count_points(settings.qdrant_history_collection)
    except Exception:  # noqa: BLE001 - collections may not exist before first run
        latest = history = 0
    return EmbedStatusResponse(
        sections_total=total,
        sections_pending=pending,
        latest_points=latest,
        history_points=history,
    )


@router.get("/snapshots", response_model=SnapshotSummaryResponse)
async def snapshot_summary() -> SnapshotSummaryResponse:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    SourceSnapshot.source_id,
                    func.count(SourceSnapshot.id),
                    func.max(SourceSnapshot.last_seen_at),
                ).group_by(SourceSnapshot.source_id)
            )
        ).all()
    sources = [
        SnapshotSummaryRow(source_id=sid, snapshots=n, last_seen_at=str(seen))
        for sid, n, seen in rows
    ]
    return SnapshotSummaryResponse(total=sum(r.snapshots for r in sources), sources=sources)
