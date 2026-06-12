"""Feature-map / roadmap table parsing → RoadmapItem rows with maturity states.

The reference-implementation feature map (docs.eudi.dev) renders MkDocs tables
with a Status column (Completed / In Progress / Planned / ...). Each row becomes
a RoadmapItem; the title cell's local link (e.g. #issuance) provides the anchor.
"""

from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

from pydantic import BaseModel

from app.models.entities import Maturity


class ParsedRoadmapItem(BaseModel):
    title: str
    description: str | None
    maturity: Maturity
    anchor_url: str | None


class _Cell(BaseModel):
    text: str = ""
    href: str | None = None


class _TableParser(HTMLParser):
    """Collect tables as rows of cells (text + first link href)."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[_Cell]]] = []
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = _Cell()
        elif tag == "a" and self._cell is not None and self._cell.href is None:
            href = dict(attrs).get("href")
            if href:
                self._cell.href = href

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._cell.text = re.sub(r"\s+", " ", self._cell.text).strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self.tables and self._row:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.text += html_lib.unescape(data)


_MATURITY_MAP = {
    "completed": Maturity.completed,
    "in progress": Maturity.in_progress,
    "planned": Maturity.planned,
}


def _to_maturity(status_text: str) -> Maturity:
    return _MATURITY_MAP.get(status_text.strip().lower(), Maturity.other)


def parse_feature_map(page_html: str, page_url: str) -> list[ParsedRoadmapItem]:
    parser = _TableParser()
    parser.feed(page_html)
    items: list[ParsedRoadmapItem] = []
    seen: set[str] = set()
    for table in parser.tables:
        if not table:
            continue
        header = [cell.text.lower() for cell in table[0]]
        if "status" not in header:
            continue
        status_col = header.index("status")
        desc_col = header.index("description") if "description" in header else None
        title_col = next(
            (i for i in range(len(header)) if i not in (status_col, desc_col)), 0
        )
        for row in table[1:]:
            if len(row) <= status_col:
                continue
            title = row[title_col].text
            if not title or title in seen:
                continue
            seen.add(title)
            href = row[title_col].href
            anchor = f"{page_url}{href}" if href and href.startswith("#") else href
            items.append(
                ParsedRoadmapItem(
                    title=title,
                    description=(
                        row[desc_col].text if desc_col is not None and len(row) > desc_col else None
                    ),
                    maturity=_to_maturity(row[status_col].text),
                    anchor_url=anchor,
                )
            )
    return items
