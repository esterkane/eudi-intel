"""Glossary matching + query expansion (offline; HyDE patched)."""

from __future__ import annotations

from typing import Any

import pytest

import app.services.query_expansion as qe
from app.core.config import get_settings
from app.services.glossary import expansion_terms, match_glossary
from app.services.query_expansion import expand_query


def test_android_without_google_matches_degoogled() -> None:
    matched = match_glossary("does the wallet work on android os without google?")
    terms = {m.term for m in matched}
    assert "de-Googled Android" in terms
    syns = [s.lower() for s in expansion_terms(matched)]
    assert "aosp" in syns and "grapheneos" in syns and "play integrity" in syns


def test_alias_variants_all_match() -> None:
    for phrasing in ["de-googled", "without GMS", "GrapheneOS support", "no google android"]:
        assert any(m.term == "de-Googled Android" for m in match_glossary(phrasing)), phrasing


def test_exact_identifier_query_matches_no_noise() -> None:
    # a precise spec query should not pull in unrelated glossary expansion
    matched = match_glossary("Topic 20 strong user authentication")
    assert all(m.term != "de-Googled Android" for m in matched)


def test_wua_aliases() -> None:
    assert any(m.term == "Wallet Unit Attestation" for m in match_glossary("how to prove the wallet is genuine"))
    assert any(m.term == "Wallet Unit Attestation" for m in match_glossary("WUA revocation"))


async def test_expand_query_glossary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_hyde(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        raise AssertionError("HyDE must not run when use_hyde=False")

    monkeypatch.setattr(qe, "chat", no_hyde)
    exp = await expand_query("android without google", get_settings(), use_hyde=False)
    assert exp.original == "android without google"
    assert "android without google" in exp.embed_text
    assert "AOSP" in exp.embed_text  # glossary synonyms appended
    assert exp.hyde_text == ""
    assert any(t.term == "de-Googled Android" for t in exp.glossary_terms)


async def test_expand_query_with_hyde(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_hyde(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        return "Hypothetical: AOSP devices use hardware key attestation instead of Play Integrity."

    monkeypatch.setattr(qe, "chat", fake_hyde)
    qe._HYDE_CACHE.clear()
    exp = await expand_query("android without google", get_settings(), use_hyde=True)
    assert "hardware key attestation" in exp.embed_text
    assert exp.hyde_text != ""


async def test_hyde_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def counting_hyde(system: str, user: str, settings: Any, max_tokens: int = 1024) -> str:
        calls["n"] += 1
        return "passage"

    monkeypatch.setattr(qe, "chat", counting_hyde)
    qe._HYDE_CACHE.clear()
    await expand_query("repeated query", get_settings(), use_hyde=True)
    await expand_query("Repeated Query", get_settings(), use_hyde=True)  # case-insensitive key
    assert calls["n"] == 1
