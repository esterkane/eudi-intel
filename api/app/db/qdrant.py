"""Qdrant collections (latest + history) with named dense + sparse vectors.

Payload carries the full citation block fields (CLAUDE.md): doc_title,
source_url, tier, version_or_tag, section_heading, last_seen — plus the chunk
content so Phase 4 reranking needs no DB round trip.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient, models

from app.core.config import Settings, get_settings
from app.embeddings.bge_m3 import EmbeddedText

DENSE_NAME = "dense"
SPARSE_NAME = "sparse"
DENSE_DIM = 1024  # BGE-M3

_client: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url)
    return _client


class ChunkPayload(BaseModel):
    doc_title: str
    source_url: str  # deep-linkable anchor URL (citation target)
    doc_url: str
    tier: str
    version_or_tag: str | None
    repo: str  # source_id
    section_heading: str
    section_path: str
    last_seen: str  # ISO date
    content: str
    content_hash: str


def point_id(index_scope: str, anchor_url: str, order_index: int) -> str:
    """Stable point id so re-embedding overwrites instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{index_scope}:{anchor_url}:{order_index}"))


async def ensure_collections(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    client = get_qdrant()
    for name in (settings.qdrant_latest_collection, settings.qdrant_history_collection):
        if await client.collection_exists(name):
            continue
        await client.create_collection(
            collection_name=name,
            vectors_config={
                DENSE_NAME: models.VectorParams(
                    size=DENSE_DIM, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams()},
        )
        for field, schema in (
            ("tier", models.PayloadSchemaType.KEYWORD),
            ("version_or_tag", models.PayloadSchemaType.KEYWORD),
            ("repo", models.PayloadSchemaType.KEYWORD),
        ):
            await client.create_payload_index(
                collection_name=name, field_name=field, field_schema=schema
            )


async def upsert_chunks(
    collection: str,
    items: list[tuple[str, EmbeddedText, ChunkPayload]],
) -> None:
    """items: (point_id, vectors, payload)."""
    if not items:
        return
    client = get_qdrant()
    points = [
        models.PointStruct(
            id=pid,
            vector={
                DENSE_NAME: emb.dense,
                SPARSE_NAME: models.SparseVector(
                    indices=emb.sparse.indices, values=emb.sparse.values
                ),
            },
            payload=payload.model_dump(),
        )
        for pid, emb, payload in items
    ]
    await client.upsert(collection_name=collection, points=points)


async def count_points(collection: str, version_or_tag: str | None = None) -> int:
    client = get_qdrant()
    query_filter = None
    if version_or_tag is not None:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="version_or_tag", match=models.MatchValue(value=version_or_tag)
                )
            ]
        )
    result = await client.count(collection_name=collection, count_filter=query_filter)
    return result.count
