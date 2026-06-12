"""Heading-aware markdown chunking (ingestion-pipeline skill §4).

Each chunk corresponds to a real document section with a stable, deep-linkable
anchor URL (GitHub/MkDocs slug). Oversized sections are split at paragraph
boundaries with a small overlap; sub-chunks share the section's anchor.

Token counts are estimated at ~4 chars/token — chunk targets sit far below the
BGE-M3 8192 ceiling, so the approximation has ample headroom.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel

# ~1000 tokens target, ~50 tokens overlap (4 chars/token estimate)
MAX_SECTION_CHARS = 4000
OVERLAP_CHARS = 200

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MD_FORMATTING = re.compile(r"[*_`]|\[(.*?)\]\([^)]*\)")


class SectionChunk(BaseModel):
    heading: str
    section_path: str  # "H1 > H2 > H3"
    anchor_url: str
    content: str
    content_hash: str
    order_index: int
    token_estimate: int


def github_slug(heading: str, seen: dict[str, int]) -> str:
    """GitHub-style anchor slug, with -N suffixes for duplicate headings."""
    text = _HTML_COMMENT.sub("", heading)
    text = _MD_FORMATTING.sub(lambda m: m.group(1) or "", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    slug = re.sub(r" +", "-", text).strip("-")
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def _clean_heading(heading: str) -> str:
    text = _HTML_COMMENT.sub("", heading)
    return text.strip()


_FIRST_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def doc_title(markdown: str, fallback: str) -> str:
    """First H1 as a clean document title (comments stripped), else fallback."""
    match = _FIRST_H1.search(markdown)
    return _clean_heading(match.group(1)) if match else fallback


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _split_oversize(content: str) -> list[str]:
    """Split at paragraph boundaries near MAX_SECTION_CHARS, with overlap."""
    if len(content) <= MAX_SECTION_CHARS:
        return [content]
    paragraphs = content.split("\n\n")
    parts: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > MAX_SECTION_CHARS and current:
            parts.append(current)
            current = current[-OVERLAP_CHARS:] + "\n\n" + para
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def chunk_markdown(text: str, base_url: str) -> list[SectionChunk]:
    """Split markdown into heading-aware sections with deep-linkable anchors.

    Content before the first heading becomes an "(introduction)" section
    anchored at the document URL itself.
    """
    lines = text.splitlines()
    seen_slugs: dict[str, int] = {}
    # (heading, level, slug) stack for section_path; raw content lines per section
    sections: list[tuple[str, int, str, list[str]]] = []
    path_stack: list[tuple[int, str]] = []  # (level, heading)
    paths: list[str] = []
    in_fence = False
    current_lines: list[str] = []
    current_heading = "(introduction)"
    current_slug = ""

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content or sections:  # skip a totally empty intro, keep empty mid-doc sections
            sections.append((current_heading, 0, current_slug, current_lines))
            paths.append(" > ".join(h for _, h in path_stack) or current_heading)

    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        match = None if in_fence else _ATX_HEADING.match(line)
        if match is None:
            current_lines.append(line)
            continue
        flush()
        level = len(match.group(1))
        heading = _clean_heading(match.group(2)) or "(untitled)"
        while path_stack and path_stack[-1][0] >= level:
            path_stack.pop()
        path_stack.append((level, heading))
        current_heading = heading
        current_slug = github_slug(heading, seen_slugs)
        current_lines = []
    flush()

    chunks: list[SectionChunk] = []
    order = 0
    for (heading, _level, slug, body_lines), path in zip(sections, paths):
        content = "\n".join(body_lines).strip()
        if not content:
            continue
        anchor = f"{base_url}#{slug}" if slug else base_url
        for part in _split_oversize(content):
            chunks.append(
                SectionChunk(
                    heading=heading,
                    section_path=path,
                    anchor_url=anchor,
                    content=part,
                    content_hash=_hash(part),
                    order_index=order,
                    token_estimate=_estimate_tokens(part),
                )
            )
            order += 1
    return chunks
