"""Phase 3 indexing: sections → BGE-M3 dense+sparse vectors → Qdrant.

- latest index: every current Section, re-embedded only when content changed.
- history index: sections parsed at a pinned ARF tag (version-filtered queries);
  Phase 8 extends this on every new tag.

Heavy embedding runs in the Celery worker (app.worker.tasks), never in request
handlers. Plain async functions, no FastAPI coupling.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.qdrant import ChunkPayload, count_points, ensure_collections, point_id, upsert_chunks
from app.db.session import SessionLocal
from app.embeddings.bge_m3 import get_embedder
from app.models.entities import Document, Section, Version
from app.parsers.markdown import chunk_markdown, doc_title
from app.parsers.tiering import tier_for_repo_file
from app.services.version_diff import file_at, markdown_files_at

_UPSERT_BATCH = 64


async def sections_needing_embedding(session: AsyncSession) -> list[tuple[Section, Document]]:
    rows = await session.execute(
        select(Section, Document)
        .join(Document, Section.document_id == Document.id)
        .where(
            (Section.embedded_hash.is_(None))
            | (Section.embedded_hash != Section.content_hash)
        )
        .order_by(Section.id)
    )
    return [(section, document) for section, document in rows.all()]


def _payload_for(section: Section, document: Document) -> ChunkPayload:
    return ChunkPayload(
        doc_title=document.title,
        source_url=section.anchor_url,
        doc_url=document.url,
        tier=str(document.tier.value if hasattr(document.tier, "value") else document.tier),
        version_or_tag=document.version_or_tag,
        repo=document.source_id,
        section_heading=section.heading,
        section_path=section.section_path,
        last_seen=document.last_seen.isoformat(),
        content=section.content,
        content_hash=section.content_hash,
    )


async def embed_pending_sections(settings: Settings) -> int:
    """Embed changed/new sections into the latest index. Returns count embedded."""
    embedder = get_embedder()
    embedded = 0
    async with SessionLocal() as session:
        pending = await sections_needing_embedding(session)
        for start in range(0, len(pending), _UPSERT_BATCH):
            batch = pending[start : start + _UPSERT_BATCH]
            vectors = embedder.embed([section.content for section, _ in batch])
            items = [
                (
                    point_id("latest", section.anchor_url, section.order_index),
                    emb,
                    _payload_for(section, document),
                )
                for (section, document), emb in zip(batch, vectors)
            ]
            await upsert_chunks(settings.qdrant_latest_collection, items)
            for section, _ in batch:
                section.embedded_hash = section.content_hash
            await session.commit()
            embedded += len(batch)
    return embedded


async def _latest_arf_tag(session: AsyncSession) -> str | None:
    tags = list(
        await session.scalars(select(Version.tag).where(Version.source_id == "arf_repo"))
    )
    if not tags:
        return None

    def semver_key(tag: str) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", tag)[:4]) or (0,)

    return max(tags, key=semver_key)


async def index_history_tag(settings: Settings, tag: str) -> int:
    """Embed all ARF markdown at a tag into the history index (idempotent)."""
    if await count_points(settings.qdrant_history_collection, version_or_tag=tag) > 0:
        return 0
    async with SessionLocal() as session:
        published = await session.scalar(
            select(Version.published_at).where(
                Version.source_id == "arf_repo", Version.tag == tag
            )
        )
    last_seen = published.isoformat() if published else tag
    embedder = get_embedder()
    mirror = Path(settings.repos_dir) / "arf_repo"
    repo = "eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework"
    indexed = 0
    for relpath in await markdown_files_at(mirror, tag):
        text = await file_at(mirror, tag, relpath)
        base_url = f"https://github.com/{repo}/blob/{tag}/{relpath}"
        chunks = chunk_markdown(text, base_url=base_url)
        if not chunks:
            continue
        tier = tier_for_repo_file("arf_repo", relpath)
        title = doc_title(text, relpath)
        vectors = embedder.embed([c.content for c in chunks])
        items = [
            (
                point_id(f"history:{tag}", chunk.anchor_url, chunk.order_index),
                emb,
                ChunkPayload(
                    doc_title=title,
                    source_url=chunk.anchor_url,
                    doc_url=base_url,
                    tier=tier.value,
                    version_or_tag=tag,
                    repo="arf_repo",
                    section_heading=chunk.heading,
                    section_path=chunk.section_path,
                    last_seen=last_seen,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                ),
            )
            for chunk, emb in zip(chunks, vectors)
        ]
        await upsert_chunks(settings.qdrant_history_collection, items)
        indexed += len(items)
    return indexed


async def embed_and_index_all(settings: Settings) -> dict[str, int | str | None]:
    await ensure_collections(settings)
    embedded = await embed_pending_sections(settings)
    async with SessionLocal() as session:
        tag = await _latest_arf_tag(session)
    history_indexed = await index_history_tag(settings, tag) if tag else 0
    return {
        "sections_embedded": embedded,
        "history_tag": tag,
        "history_indexed": history_indexed,
        "latest_points": await count_points(settings.qdrant_latest_collection),
        "history_points": await count_points(settings.qdrant_history_collection),
    }
