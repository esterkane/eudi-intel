"""Query expansion (semantic-recall skill): build the text used for the dense +
sparse channel embeddings so vague queries retrieve the right material.

- Glossary aliases (deterministic, cheap, always available) add a matched term's
  technical synonyms to the embedded text.
- HyDE-lite (optional, one short LLM call, cached) adds a hypothetical answer
  passage — dense recall improves when the query text looks like the target text.

The lexical/heading channels keep using the ORIGINAL query (see retrieval.py), so
exact-identifier queries do not regress; expansion only adds semantic candidates.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.core.config import Settings
from app.services.glossary import GlossaryTerm, expansion_terms, match_glossary
from app.services.llm import LlmUnavailableError, chat

_HYDE_SYSTEM = (
    "You help retrieve EU Digital Identity (EUDI) / eIDAS 2.0 technical "
    "documentation. Given a question, write 2-3 sentences of a hypothetical "
    "answer using precise technical terminology (protocols, components, spec "
    "terms). Do not say you are unsure; just write the plausible passage."
)

# Cache HyDE passages by normalized query (HyDE is the expensive part). Bounded.
_HYDE_CACHE: dict[str, str] = {}
_HYDE_CACHE_MAX = 512
_WS = re.compile(r"\s+")


class QueryExpansion(BaseModel):
    original: str
    glossary_terms: list[GlossaryTerm]
    hyde_text: str
    embed_text: str  # what the dense/sparse channels embed


def _norm_key(query: str) -> str:
    return _WS.sub(" ", query.strip().lower())


async def _hyde(query: str, settings: Settings) -> str:
    key = _norm_key(query)
    if key in _HYDE_CACHE:
        return _HYDE_CACHE[key]
    try:
        text = await chat(_HYDE_SYSTEM, f"Question: {query}", settings, max_tokens=180)
    except LlmUnavailableError:
        return ""  # expansion is best-effort; never fail a search because HyDE is down
    if len(_HYDE_CACHE) >= _HYDE_CACHE_MAX:
        _HYDE_CACHE.clear()
    _HYDE_CACHE[key] = text
    return text


async def expand_query(
    query: str, settings: Settings, *, use_hyde: bool = False
) -> QueryExpansion:
    matched = match_glossary(query)
    alias_text = " ".join(expansion_terms(matched))
    hyde_text = await _hyde(query, settings) if use_hyde else ""
    embed_text = " ".join(part for part in (query, alias_text, hyde_text) if part).strip()
    return QueryExpansion(
        original=query,
        glossary_terms=matched,
        hyde_text=hyde_text,
        embed_text=embed_text,
    )
