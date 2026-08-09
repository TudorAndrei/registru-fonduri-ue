"""Normalizare de text. Datele oficiale sunt scrise inconsecvent, cu și fără diacritice."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: Sufixe de formă juridică, eliminate la potrivirea beneficiarilor.
LEGAL_SUFFIXES = (
    "srl",
    "sa",
    "sca",
    "snc",
    "scs",
    "pfa",
    "ii",
    "if",
    "ong",
    "asociatia",
    "fundatia",
    "societatea",
    "s r l",
    "s a",
)


def strip_diacritics(value: str) -> str:
    """`Județ` -> `Judet`. ș/ț cu virgulă și cu sedilă ajung la fel."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def slug(value: str | None) -> str:
    """Cheie de comparație: fără diacritice, fără punctuație, minuscule."""
    if value is None:
        return ""
    return _NON_ALNUM.sub(" ", strip_diacritics(str(value)).lower()).strip()


def squeeze(value: str | None) -> str:
    if value is None:
        return ""
    return _WS.sub(" ", str(value)).strip()


def normalize_header(value: str | None) -> str:
    """Antetul unei coloane de Excel, adus la o formă comparabilă."""
    return _WS.sub(" ", slug(value))


def normalize_company(name: str | None) -> str:
    """Numele unui beneficiar, pregătit pentru deduplicare.

    Elimină forma juridică, pentru că `ACME SRL`, `S.C. ACME S.R.L.` și `Acme`
    apar toate trei în fișierele oficiale, uneori în același fișier.
    """
    key = slug(name)
    if not key:
        return ""
    tokens = [t for t in key.split() if t not in {"sc", "s", "c"}]
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


_CUI = re.compile(r"\b(?:ro)?\s?(\d{2,10})\b", re.IGNORECASE)


def normalize_cui(value: str | int | None) -> str | None:
    """`RO 12345678`, `12345678`, `RO12345678` -> `12345678`."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    match = _CUI.search(text.replace(".", "").replace(",", ""))
    if not match:
        return None
    return match.group(1).lstrip("0") or None
