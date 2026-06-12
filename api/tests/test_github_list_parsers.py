"""GitHub list-page parsers against fixtures mirroring the real markup
(structures verified from live payloads on 2026-06-12)."""

from __future__ import annotations

import json

from app.parsers.github_lists import (
    parse_discussion_list,
    parse_issue_list,
    parse_pull_list,
)

REPO = "eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework"


def _issues_page(nodes: list[dict[str, object]]) -> str:
    payload = {
        "payload": {
            "preloadedQueries": [
                {"result": {"data": {"repository": {"search": {"edges": [
                    {"node": n} for n in nodes
                ]}}}}}
            ]
        }
    }
    return (
        "<html><script type=\"application/json\" "
        "data-target=\"react-app.embeddedData\">"
        + json.dumps(payload)
        + "</script></html>"
    )


def test_parse_issue_list_from_embedded_json() -> None:
    page = _issues_page(
        [
            {
                "__typename": "Issue",
                "number": 705,
                "titleHtml": "Topic AE - Liveness Tests <em>in</em> Remote Flows",
                "state": "OPEN",
                "updatedAt": "2026-06-01T12:00:00Z",
            },
            {"__typename": "Issue", "number": 705, "titleHtml": "duplicate"},
            {"__typename": "Issue", "number": 700, "title": "Plain title", "state": "OPEN"},
            {"__typename": "Repository", "number": 999},
        ]
    )
    items = parse_issue_list(page, REPO)
    assert [i.number for i in items] == [705, 700]
    assert items[0].title == "Topic AE - Liveness Tests in Remote Flows"
    assert items[0].state == "open"
    assert items[0].url == f"https://github.com/{REPO}/issues/705"
    assert items[0].updated_at is not None


def test_parse_issue_list_without_embedded_json() -> None:
    assert parse_issue_list("<html>nothing here</html>", REPO) == []


def test_parse_pull_list() -> None:
    page = f"""
    <div id="issue_681" class="Box-row js-issue-row">
      <span aria-label="Open Pull Request"></span>
      <a href="/{REPO}/pull/681" class="Link--primary">Fix <code>typo</code> in annex</a>
      <relative-time datetime="2026-05-20T08:00:00Z"></relative-time>
    </div>
    <div id="issue_650" class="Box-row js-issue-row">
      <a href="/{REPO}/pull/650" class="Link--primary">Older change</a>
    </div>
    """
    items = parse_pull_list(page, REPO)
    assert [i.number for i in items] == [681, 650]
    assert items[0].title == "Fix typo in annex"
    assert items[0].state == "open"
    assert items[0].updated_at is not None
    assert items[1].state == "closed"


def test_parse_discussion_list() -> None:
    page = f"""
    <a data-x="1" href="/{REPO}/discussions/167" class="discussion-title Link--primary">
      Welcome to Discussions!</a>
    <a href="/{REPO}/discussions/167" class="discussion-title">dupe of 167</a>
    <a href="/{REPO}/discussions?discussions_q=label" class="other">filter link</a>
    <a href="/{REPO}/discussions/200" class="lh-condensed discussion-title Link">Topic B</a>
    <a href="/{REPO}/discussions/661" class="Link--primary markdown-title">List row topic</a>
    <a data-hovercard-type="discussion" href="/{REPO}/discussions/661" class="avatar">x</a>
    """
    items = parse_discussion_list(page, REPO)
    assert [i.number for i in items] == [167, 200, 661]
    assert items[0].title == "Welcome to Discussions!"
    assert items[0].url == f"https://github.com/{REPO}/discussions/167"
    assert items[2].title == "List row topic"
