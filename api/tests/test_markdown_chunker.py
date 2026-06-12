"""Heading-aware chunking: paths, anchors, fences, dedupe slugs, oversize split."""

from __future__ import annotations

from app.parsers.markdown import MAX_SECTION_CHARS, chunk_markdown

BASE = "https://github.com/o/r/blob/main/doc.md"

SAMPLE = """\
Intro paragraph before any heading.

# Architecture and Reference Framework

## 1 Introduction

### 1.1 EUDI Wallet ecosystem

Ecosystem text.

### 1.2 Legal context

Legal text.

## 2 Functionalities

```python
# this is code, not a heading
x = 1
```

Functionality text.
"""


def test_sections_and_paths() -> None:
    chunks = chunk_markdown(SAMPLE, BASE)
    by_heading = {c.heading: c for c in chunks}

    assert "(introduction)" in by_heading
    assert by_heading["(introduction)"].anchor_url == BASE  # no fragment pre-heading

    eco = by_heading["1.1 EUDI Wallet ecosystem"]
    assert eco.section_path == (
        "Architecture and Reference Framework > 1 Introduction > 1.1 EUDI Wallet ecosystem"
    )
    assert eco.anchor_url == f"{BASE}#11-eudi-wallet-ecosystem"

    func = by_heading["2 Functionalities"]
    assert func.section_path == "Architecture and Reference Framework > 2 Functionalities"
    # the fenced pseudo-heading must not have produced a section
    assert "this is code, not a heading" not in by_heading
    assert "# this is code, not a heading" in func.content


def test_duplicate_headings_get_suffixed_slugs() -> None:
    text = "# T\n\n## Same\n\na\n\n## Same\n\nb\n"
    chunks = chunk_markdown(text, BASE)
    anchors = [c.anchor_url for c in chunks if c.heading == "Same"]
    assert anchors == [f"{BASE}#same", f"{BASE}#same-1"]


def test_html_comments_stripped_from_heading() -> None:
    text = "# ANNEX 2.01 - High-Level Requirements <!-- omit from toc -->\n\nbody\n"
    chunks = chunk_markdown(text, BASE)
    assert chunks[0].heading == "ANNEX 2.01 - High-Level Requirements"
    assert chunks[0].anchor_url == f"{BASE}#annex-201---high-level-requirements"


def test_oversize_section_splits_with_shared_anchor() -> None:
    body = "\n\n".join(f"Paragraph {i} " + "x" * 200 for i in range(40))
    chunks = chunk_markdown(f"# Big\n\n{body}\n", BASE)
    assert len(chunks) > 1
    assert all(c.anchor_url == f"{BASE}#big" for c in chunks)
    assert all(len(c.content) <= MAX_SECTION_CHARS + 250 for c in chunks)
    assert [c.order_index for c in chunks] == list(range(len(chunks)))


def test_hash_stability() -> None:
    a = chunk_markdown(SAMPLE, BASE)
    b = chunk_markdown(SAMPLE, BASE)
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
