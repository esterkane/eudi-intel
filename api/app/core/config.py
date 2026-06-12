"""Application settings, loaded from environment / .env.

Model names and every tunable are read from env (never hardcoded in call sites),
per the CLAUDE.md rule. Defaults mirror .env.example so the app is runnable with
docker-compose-provided variables.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Postgres ────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://eudi:eudi@postgres:5432/eudi"

    # ── Qdrant / Redis ──────────────────────────────────────────────────────
    qdrant_url: str = "http://qdrant:6333"
    redis_url: str = "redis://redis:6379/0"
    qdrant_latest_collection: str = "eudi_latest"
    qdrant_history_collection: str = "eudi_history"

    # ── Ollama / models (sizes capped per CLAUDE.md VRAM rules) ─────────────
    ollama_base_url: str = "http://host.docker.internal:11434"
    gen_model: str = "qwen3:8b"
    gen_context_tokens: int = 8192
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = True
    rerank_candidates: int = 30
    embed_batch_size: int = 16

    # ── Frontend ────────────────────────────────────────────────────────────
    next_public_api_url: str = "http://localhost:8000"

    # ── GitHub (empty = token-free mode) ────────────────────────────────────
    github_token: str = ""

    # ── Ingestion ────────────────────────────────────────────────────────────
    repos_dir: str = "/data/repos"  # git mirror directory (compose volume)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
