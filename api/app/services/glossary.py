"""Domain glossary / alias map for EUDI + eIDAS 2.0 (semantic-recall skill).

Two jobs:
- expansion: when a query mentions a term/alias, add the term's technical
  synonyms to the embedded query text so vague phrasings retrieve the right
  material ("android without google" → AOSP, GrapheneOS, key attestation, ...);
- explanation: surface the matched term definitions in the support console (S4).

Deterministic and cheap (no LLM). Matching is case-insensitive, on word-ish
boundaries, against the canonical term and every alias.
"""

from __future__ import annotations

import re

from pydantic import BaseModel


class GlossaryTerm(BaseModel):
    term: str
    definition: str
    aliases: list[str] = []
    # technical synonyms added to the embedded query when this term matches
    expand: list[str] = []


GLOSSARY: tuple[GlossaryTerm, ...] = (
    GlossaryTerm(
        term="de-Googled Android",
        definition=(
            "Android builds without Google Mobile Services (GMS) — e.g. AOSP or "
            "GrapheneOS. Relevant to EUDI wallets because device/key attestation "
            "normally relies on Google Play Integrity / SafetyNet, which is absent "
            "on these builds, so alternative key attestation is needed."
        ),
        aliases=[
            "android without google", "without google", "without gms", "gms-less",
            "gms less", "de-googled", "degoogled", "google-free", "no google",
            "aosp", "graphene", "grapheneos", "calyx", "lineageos",
        ],
        expand=[
            "AOSP", "GrapheneOS", "Google Mobile Services", "Play Integrity",
            "SafetyNet", "hardware key attestation", "device attestation",
        ],
    ),
    GlossaryTerm(
        term="Wallet Unit Attestation",
        definition=(
            "An attestation proving a wallet unit/instance is genuine and "
            "non-revoked, issued by the Wallet Provider. Often abbreviated WUA "
            "(or WIA, Wallet Instance Attestation)."
        ),
        aliases=["wua", "wia", "wallet unit attestation", "wallet instance attestation",
                 "prove the wallet is genuine", "wallet is genuine", "wallet authenticity"],
        expand=["Wallet Unit Attestation", "Wallet Provider", "key attestation", "revocation"],
    ),
    GlossaryTerm(
        term="OpenID4VP (presentation)",
        definition=(
            "OpenID for Verifiable Presentations — the protocol a relying party "
            "(verifier) uses to request and receive credentials from a wallet."
        ),
        aliases=["oid4vp", "openid4vp", "openid for verifiable presentations",
                 "verifier rejects", "verifier request", "presentation request",
                 "invalid_request", "client_id_scheme"],
        expand=["OpenID4VP", "relying party", "verifier", "presentation", "client_id_scheme"],
    ),
    GlossaryTerm(
        term="OpenID4VCI (issuance)",
        definition="OpenID for Verifiable Credential Issuance — how an issuer issues credentials to a wallet.",
        aliases=["oid4vci", "openid4vci", "credential issuance", "issue a credential",
                 "issuance flow"],
        expand=["OpenID4VCI", "issuer", "credential issuance"],
    ),
    GlossaryTerm(
        term="PID",
        definition="Person Identification Data — the core identity dataset a member state issues to a wallet.",
        aliases=["pid", "person identification data", "identity data"],
        expand=["Person Identification Data", "PID Provider"],
    ),
    GlossaryTerm(
        term="rQES",
        definition="remote Qualified Electronic Signature — signing with a qualified certificate via the wallet.",
        aliases=["rqes", "qes", "qualified electronic signature", "remote signing", "electronic signature"],
        expand=["remote Qualified Electronic Signature", "qualified signature", "signing"],
    ),
    GlossaryTerm(
        term="SD-JWT VC",
        definition="Selective-Disclosure JWT Verifiable Credential — a credential format supporting selective disclosure.",
        aliases=["sd-jwt", "sd jwt", "sd-jwt vc", "selective disclosure"],
        expand=["SD-JWT VC", "selective disclosure", "credential format"],
    ),
    GlossaryTerm(
        term="mso_mdoc (ISO mdoc)",
        definition="ISO/IEC 18013-5 mobile document credential format (mdoc / mDL) using a Mobile Security Object.",
        aliases=["mdoc", "mso_mdoc", "mso mdoc", "iso 18013", "mdl", "mobile driving licence"],
        expand=["mso_mdoc", "ISO/IEC 18013-5", "mobile security object"],
    ),
    GlossaryTerm(
        term="Level of Assurance",
        definition="eIDAS assurance level (low / substantial / high) for electronic identification.",
        aliases=["loa", "level of assurance", "assurance level", "substantial", "high assurance"],
        expand=["Level of Assurance", "eIDAS", "substantial", "high"],
    ),
    GlossaryTerm(
        term="Relying Party",
        definition="A verifier that requests and validates credentials from a wallet (a.k.a. RP).",
        aliases=["relying party", "rp", "verifier registration", "rp registration"],
        expand=["relying party", "verifier", "registration"],
    ),
    GlossaryTerm(
        term="ARF Annex 2",
        definition="The normative High-Level Requirements of the Architecture and Reference Framework.",
        aliases=["annex 2", "annex-2", "high-level requirements", "hlr", "normative requirements"],
        expand=["Annex 2", "high-level requirements", "normative"],
    ),
    GlossaryTerm(
        term="Wallet Trust Mark",
        definition="A trust mark indicating a wallet solution is certified/recognised in the EUDI ecosystem.",
        aliases=["trust mark", "trustmark", "wallet trust mark"],
        expand=["Wallet Trust Mark", "certification", "trust"],
    ),
)

_WORD = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def match_glossary(query: str) -> list[GlossaryTerm]:
    """Glossary terms whose canonical name or any alias appears in the query."""
    norm = f" {_normalize(query)} "
    matched: list[GlossaryTerm] = []
    for term in GLOSSARY:
        needles = [term.term, *term.aliases]
        if any(f" {_normalize(n)} " in norm for n in needles):
            matched.append(term)
    return matched


def expansion_terms(matched: list[GlossaryTerm]) -> list[str]:
    """De-duplicated technical synonyms for the matched terms (order-stable)."""
    seen: set[str] = set()
    out: list[str] = []
    for term in matched:
        for syn in [term.term, *term.expand]:
            key = syn.lower()
            if key not in seen:
                seen.add(key)
                out.append(syn)
    return out
