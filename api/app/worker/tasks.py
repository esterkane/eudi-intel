"""Celery tasks. Embedding is the heavy ingestion step and always runs here,
never in API request handlers (CLAUDE.md VRAM/RAM rules: BGE-M3 on CPU, in the
worker)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.services.vector_index import embed_and_index_all
from app.worker.celery_app import celery_app


@celery_app.task(name="embed_and_index")
def embed_and_index() -> dict[str, Any]:
    return asyncio.run(embed_and_index_all(get_settings()))
