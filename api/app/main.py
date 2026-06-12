"""FastAPI application entrypoint for the EUDI Intelligence & Authoring Workbench."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.routers import answer, health, ingest, search

app = FastAPI(
    title="EUDI Intelligence & Authoring Workbench",
    version="0.0.0",
)
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(search.router)
app.include_router(answer.router)


class RootResponse(BaseModel):
    service: str
    status: str


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(service="eudi-intel-api", status="up")
