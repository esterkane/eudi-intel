"""Declarative base. Entity models (Document, Section, Version, ...) are added
in later phases and import from here so Alembic can see their metadata."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
