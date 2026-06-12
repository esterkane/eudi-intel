"""Shared collector types and helpers."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel

# Polite, identifiable client string for all outbound HTTP.
USER_AGENT = "eudi-intel/0.0 (local research mirror; +https://github.com/local/eudi-intel)"

HTTP_TIMEOUT_SECONDS = 30.0


class CollectResult(BaseModel):
    """Outcome of one collector run against one source."""

    source_id: str
    url: str
    status: Literal["fetched", "not_modified"]
    content_hash: str
    payload: str | None = None
    payload_ref: str | None = None
    etag: str | None = None


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
