"""bge-reranker-v2-m3 on CPU (local-inference skill).

Cross-encoder scoring of (query, candidate) pairs, applied only to the top
RERANK_CANDIDATES fused results (~30) and toggleable via RERANK_ENABLED.

The model is driven directly via transformers (fast tokenizer +
AutoModelForSequenceClassification): FlagEmbedding's FlagReranker calls the
removed slow-tokenizer API `prepare_for_model` under transformers 5.x
(verified against 5.11.0). Lazy singleton like the embedder; torch in the
containers is CPU-only, so the GPU stays reserved for the LLM.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

_BATCH_SIZE = 8


class BgeReranker:
    def __init__(self, model_name: str, max_length: int = 256) -> None:
        # Shorter max_length trades a little long-document precision for a large
        # CPU speedup; the relevance signal is usually early in the passage.
        self._model_name = model_name
        self._max_length = max_length
        self._tokenizer: Any = None
        self._model: Any = None

    def _load(self) -> None:
        if self._model is None:
            # Imported lazily: pulls torch/transformers, which unit tests and
            # non-rerank paths must not pay for.
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self._model_name)
            self._model.eval()

    def score(self, query: str, candidates: list[str]) -> list[float]:
        """Relevance score per candidate, normalized to (0, 1) via sigmoid."""
        if not candidates:
            return []
        self._load()
        import torch

        scores: list[float] = []
        with torch.no_grad():
            for start in range(0, len(candidates), _BATCH_SIZE):
                batch = candidates[start : start + _BATCH_SIZE]
                inputs = self._tokenizer(
                    [query] * len(batch),
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self._max_length,
                    return_tensors="pt",
                )
                logits = self._model(**inputs).logits.view(-1)
                scores.extend(torch.sigmoid(logits).tolist())
        return [float(s) for s in scores]


_reranker: BgeReranker | None = None


def get_reranker() -> BgeReranker:
    global _reranker
    if _reranker is None:
        settings = get_settings()
        _reranker = BgeReranker(settings.reranker_model, max_length=settings.rerank_max_length)
    return _reranker
