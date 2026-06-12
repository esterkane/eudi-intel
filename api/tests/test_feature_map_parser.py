"""Feature-map tables → roadmap items with maturity (structure verified live)."""

from __future__ import annotations

from app.models.entities import Maturity
from app.parsers.feature_map import parse_feature_map

PAGE_URL = "https://docs.eudi.dev/latest/reference-implementation/feature-map/"

HTML = """
<article>
<table>
  <thead><tr><th>Format</th><th>Status</th><th>Description</th></tr></thead>
  <tbody>
    <tr><td><code>mso_mdoc</code></td><td>Published (ISO/IEC 18013-5)</td>
        <td>ISO credential format.</td></tr>
  </tbody>
</table>
<table>
  <thead><tr><th>Features</th><th>Description</th><th>Status</th></tr></thead>
  <tbody>
    <tr><td><a href="#issuance">Issuance</a></td><td>Issuance of credentials</td>
        <td>Completed</td></tr>
    <tr><td><a href="#presentation">Presentation</a></td><td>Presentation flows</td>
        <td>In Progress</td></tr>
    <tr><td>Future thing</td><td>Not yet started</td><td>Planned</td></tr>
  </tbody>
</table>
<table>
  <thead><tr><th>Unrelated</th><th>Columns</th></tr></thead>
  <tbody><tr><td>skip</td><td>me</td></tr></tbody>
</table>
</article>
"""


def test_parse_feature_map() -> None:
    items = parse_feature_map(HTML, PAGE_URL)
    by_title = {i.title: i for i in items}

    assert by_title["Issuance"].maturity == Maturity.completed
    assert by_title["Issuance"].anchor_url == f"{PAGE_URL}#issuance"
    assert by_title["Issuance"].description == "Issuance of credentials"
    assert by_title["Presentation"].maturity == Maturity.in_progress
    assert by_title["Future thing"].maturity == Maturity.planned
    # status strings outside the canonical three map to "other"
    assert by_title["mso_mdoc"].maturity == Maturity.other
    # the no-status table contributed nothing
    assert "skip" not in by_title
