"""Phase 0 health-endpoint test. Component probes are patched so the test runs
offline (no Postgres/Qdrant/Redis/Ollama required), per the run-and-test skill's
"keep tests offline" rule."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routers.health as health_router
from app.main import app
from app.services.health_checks import ComponentHealth


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def ok_postgres() -> ComponentHealth:
        return ComponentHealth(status="ok", detail="SELECT 1")

    async def ok_with_settings(_settings: object) -> ComponentHealth:
        return ComponentHealth(status="ok", detail="ok")

    monkeypatch.setattr(health_router, "check_postgres", ok_postgres)
    monkeypatch.setattr(health_router, "check_qdrant", ok_with_settings)
    monkeypatch.setattr(health_router, "check_redis", ok_with_settings)
    monkeypatch.setattr(health_router, "check_ollama", ok_with_settings)
    monkeypatch.setattr(health_router, "check_generation", ok_with_settings)
    return TestClient(app)


def test_health_all_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["components"]) == {
        "postgres",
        "qdrant",
        "redis",
        "ollama",
        "generation",
    }
    assert all(c["status"] == "ok" for c in body["components"].values())


def test_health_degraded_when_a_component_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(_settings: object) -> ComponentHealth:
        return ComponentHealth(status="error", detail="connection refused")

    monkeypatch.setattr(health_router, "check_redis", down)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["components"]["redis"]["status"] == "error"


def test_generation_skipped_when_model_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def missing(_settings: object) -> ComponentHealth:
        return ComponentHealth(status="missing", detail="ollama pull qwen3:8b")

    monkeypatch.setattr(health_router, "check_ollama", missing)
    body = client.get("/health").json()
    assert body["components"]["ollama"]["status"] == "missing"
    assert body["components"]["generation"]["status"] == "skipped"
    assert body["status"] == "degraded"


def test_root_ok() -> None:
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert resp.json() == {"service": "eudi-intel-api", "status": "up"}
