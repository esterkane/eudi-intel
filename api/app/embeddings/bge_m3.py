"""BGE-M3 dense + sparse embeddings on CPU (local-inference skill).

Implementation note (deviation from CLAUDE.md's "via FastEmbed/ONNX"): fastembed
0.8.0 does not ship BAAI/bge-m3 in any form (verified 2026-06-12), so the model
is served through FlagEmbedding on a CPU-only torch build instead. The model
identity, dense+sparse capability, CPU placement, and env-driven name are all
per contract. The container installs the CPU torch wheel, so GPU use is
structurally impossible here — the GPU stays reserved for the LLM.

The model is lazy-loaded once per process (~2.3 GB RAM). Heavy batch embedding
belongs in the Celery worker; the API process only ever embeds single query
strings (Phase 4).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import get_settings


class SparseVector(BaseModel):
    indices: list[int]
    values: list[float]


class EmbeddedText(BaseModel):
    dense: list[float]
    sparse: SparseVector


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[EmbeddedText]: ...


def lexical_weights_to_sparse(weights: dict[str, float]) -> SparseVector:
    """FlagEmbedding lexical weights {token_id: weight} → Qdrant sparse vector."""
    indices: list[int] = []
    values: list[float] = []
    for token_id, weight in weights.items():
        indices.append(int(token_id))
        values.append(float(weight))
    return SparseVector(indices=indices, values=values)


class BgeM3Embedder:
    """Lazy singleton around BGEM3FlagModel (CPU)."""

    def __init__(self, model_name: str, batch_size: int) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            # Imported lazily: pulls torch/transformers, which unit tests and the
            # API's non-embedding paths must not pay for.
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self._model_name, use_fp16=False, device="cpu")
        return self._model

    def embed(self, texts: list[str]) -> list[EmbeddedText]:
        model = self._load()
        output = model.encode(
            texts,
            batch_size=self._batch_size,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        results: list[EmbeddedText] = []
        for dense, weights in zip(output["dense_vecs"], output["lexical_weights"]):
            results.append(
                EmbeddedText(
                    dense=[float(x) for x in dense],
                    sparse=lexical_weights_to_sparse(weights),
                )
            )
        return results


_embedder: BgeM3Embedder | None = None


def get_embedder() -> BgeM3Embedder:
    global _embedder
    if _embedder is None:
        settings = get_settings()
        _embedder = BgeM3Embedder(settings.embedding_model, settings.embed_batch_size)
    return _embedder
