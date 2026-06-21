"""Resource wiring for the MCP layer.

The MCP server is a sibling front-end to the FastAPI app: both adapt the same
retrieval core to a transport. The EUDI core already exposes its expensive
singletons as module-level objects / cached accessors — the async SQLAlchemy
``SessionLocal`` (``app.db.session``), the cached Qdrant client
(``app.db.qdrant.get_qdrant``), and the CPU embedder/reranker (loaded lazily by
``app.services.retrieval`` on first search). The tool impls default to the real
retrieval functions, which use those singletons, so there is nothing extra to
construct here beyond the cached settings.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings


def get_mcp_settings() -> Settings:
    """The cached application Settings (transport, model names, service URLs)."""
    return get_settings()
