"""FastAPI application entrypoint for the EUDI Intelligence & Authoring Workbench."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import get_settings
from app.routers import answer, author, dashboard, health, ingest, search

app = FastAPI(
    title="EUDI Intelligence & Authoring Workbench",
    version="0.0.0",
)
# The browser-facing UI calls the API cross-origin (localhost:3000 → :8000).
# Explicit origins only — single-user local stack, no wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(answer.router)
app.include_router(dashboard.router)
app.include_router(author.router)


class RootResponse(BaseModel):
    service: str
    status: str


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(service="eudi-intel-api", status="up")
