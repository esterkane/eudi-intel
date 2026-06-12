"""Ingest router tests — runner patched so they run offline."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routers.ingest as ingest_router
from app.collectors.runner import SourceRunReport
from app.main import app


async def fake_run_all(_settings: object) -> list[SourceRunReport]:
    return [
        SourceRunReport(source_id="arf_repo", status="fetched", snapshot_created=True,
                        content_hash="a" * 64),
        SourceRunReport(source_id="ec_policy_page", status="error", error="boom"),
    ]


def test_run_all_reports_per_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_router, "run_all", fake_run_all)
    resp = TestClient(app).post("/ingest/run-all")
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert {r["source_id"] for r in results} == {"arf_repo", "ec_policy_page"}
    assert results[0]["snapshot_created"] is True
    assert results[1]["status"] == "error"


def test_run_unknown_source_404() -> None:
    resp = TestClient(app).post("/ingest/run/not_a_source")
    assert resp.status_code == 404
    assert "unknown source" in resp.json()["detail"]
