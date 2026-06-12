"""Atom feed parsing → entries; release-tag extraction."""

from __future__ import annotations

from app.parsers.feeds import parse_atom, tag_from_release_url

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:github.com,2008:https://github.com/o/r/releases</id>
  <updated>2026-06-12T06:00:00Z</updated>
  <entry>
    <id>tag:github.com,2008:Repository/1/v2.5.0</id>
    <updated>2026-04-01T10:00:00Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v2.5.0"/>
    <title>ARF 2.5.0</title>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1/v2.4.0</id>
    <updated>2026-02-01T10:00:00Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v2.4.0"/>
    <title>ARF 2.4.0</title>
  </entry>
</feed>
"""


def test_parse_atom_entries() -> None:
    entries = parse_atom(ATOM)
    assert len(entries) == 2
    first = entries[0]
    assert first.title == "ARF 2.5.0"
    assert first.url == "https://github.com/o/r/releases/tag/v2.5.0"
    assert first.updated is not None and first.updated.year == 2026


def test_tag_from_release_url() -> None:
    assert tag_from_release_url("https://github.com/o/r/releases/tag/v2.5.0") == "v2.5.0"
    assert tag_from_release_url("https://github.com/o/r/commit/abc") is None
