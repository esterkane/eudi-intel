"""GitHub Atom feed parsing → releases and tags ("what changed" inputs)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from pydantic import BaseModel

_ATOM = "{http://www.w3.org/2005/Atom}"


class FeedEntry(BaseModel):
    entry_id: str
    title: str
    url: str
    updated: datetime | None


def parse_atom(xml_text: str) -> list[FeedEntry]:
    root = ET.fromstring(xml_text)
    entries: list[FeedEntry] = []
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = entry.findtext(f"{_ATOM}id", default="")
        title = (entry.findtext(f"{_ATOM}title", default="") or "").strip()
        link = entry.find(f"{_ATOM}link")
        url = link.get("href", "") if link is not None else ""
        updated_text = entry.findtext(f"{_ATOM}updated")
        updated = datetime.fromisoformat(updated_text) if updated_text else None
        entries.append(FeedEntry(entry_id=entry_id, title=title, url=url, updated=updated))
    return entries


def tag_from_release_url(url: str) -> str | None:
    """https://github.com/o/r/releases/tag/v2.5.0 → v2.5.0"""
    marker = "/releases/tag/"
    if marker in url:
        return url.split(marker, 1)[1] or None
    return None
