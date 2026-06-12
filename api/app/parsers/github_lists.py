"""Token-free parsing of GitHub list pages (eudi-source-registry: 'scrape').

Three different page generations are in play (verified against live payloads,
2026-06-12):
- issues:      React app; rows live in an embedded JSON GraphQL payload
               (`react-app.embeddedData`, nodes with __typename == "Issue").
- pulls:       classic server-rendered rows (`id="issue_<n>"`).
- discussions: server-rendered links (`href=".../discussions/<n>"`).
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel

_EMBEDDED_DATA = re.compile(
    r'<script type="application/json" data-target="react-app.embeddedData">(.*?)</script>',
    re.DOTALL,
)
_TAG_STRIP = re.compile(r"<[^>]+>")
_PULL_ROW = re.compile(r'id="issue_(\d+)"')
_RELATIVE_TIME = re.compile(r'<relative-time[^>]*datetime="([^"]+)"')


class GithubListItem(BaseModel):
    repo: str  # "owner/name"
    number: int
    title: str
    state: str
    url: str
    updated_at: datetime | None = None


def _strip_tags(text: str) -> str:
    return html_lib.unescape(_TAG_STRIP.sub("", text)).strip()


def _walk_for_issues(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if node.get("__typename") == "Issue" and "number" in node:
            out.append(node)
        for value in node.values():
            _walk_for_issues(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_for_issues(value, out)


def parse_issue_list(page_html: str, repo: str) -> list[GithubListItem]:
    match = _EMBEDDED_DATA.search(page_html)
    if match is None:
        return []
    data = json.loads(match.group(1))
    nodes: list[dict[str, Any]] = []
    _walk_for_issues(data, nodes)
    items: list[GithubListItem] = []
    seen: set[int] = set()
    for node in nodes:
        number = int(node["number"])
        if number in seen:
            continue
        seen.add(number)
        title = node.get("title") or _strip_tags(str(node.get("titleHtml", "")))
        if not title:
            continue
        updated_raw = node.get("updatedAt")
        items.append(
            GithubListItem(
                repo=repo,
                number=number,
                title=title,
                state=str(node.get("state", "OPEN")).lower(),
                url=f"https://github.com/{repo}/issues/{number}",
                updated_at=datetime.fromisoformat(updated_raw) if updated_raw else None,
            )
        )
    return items


def parse_pull_list(page_html: str, repo: str) -> list[GithubListItem]:
    items: list[GithubListItem] = []
    rows = list(_PULL_ROW.finditer(page_html))
    for i, row in enumerate(rows):
        number = int(row.group(1))
        end = rows[i + 1].start() if i + 1 < len(rows) else len(page_html)
        chunk = page_html[row.start() : end]
        title_match = re.search(
            rf'href="/{re.escape(repo)}/pull/{number}"[^>]*>(.*?)</a>', chunk, re.DOTALL
        )
        if title_match is None:
            continue
        state = "open" if 'aria-label="Open Pull Request"' in chunk else "closed"
        time_match = _RELATIVE_TIME.search(chunk)
        items.append(
            GithubListItem(
                repo=repo,
                number=number,
                title=_strip_tags(title_match.group(1)),
                state=state,
                url=f"https://github.com/{repo}/pull/{number}",
                updated_at=(
                    datetime.fromisoformat(time_match.group(1)) if time_match else None
                ),
            )
        )
    return items


def parse_discussion_list(page_html: str, repo: str) -> list[GithubListItem]:
    # List rows use class "markdown-title"; the spotlight card uses
    # "discussion-title" (verified live 2026-06-12). Accept either.
    pattern = re.compile(
        rf'<a[^>]*href="/{re.escape(repo)}/discussions/(\d+)"[^>]*class="[^"]*'
        rf'(?:discussion-title|markdown-title)[^"]*"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    items: list[GithubListItem] = []
    seen: set[int] = set()
    for match in pattern.finditer(page_html):
        number = int(match.group(1))
        title = _strip_tags(match.group(2))
        if number in seen or not title:
            continue
        seen.add(number)
        items.append(
            GithubListItem(
                repo=repo,
                number=number,
                title=title,
                state="open",
                url=f"https://github.com/{repo}/discussions/{number}",
            )
        )
    return items
