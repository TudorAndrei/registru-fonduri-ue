"""Registrul adaptoarelor de sursă."""

from __future__ import annotations

from registru.sources.base import FetchedFile, Source
from registru.sources.datagovro import DataGovRo
from registru.sources.fondurieue import FonduriUe
from registru.sources.kohesio import Kohesio
from registru.sources.oportunitati import Oportunitati

SOURCES: dict[str, type] = {
    DataGovRo.id: DataGovRo,
    FonduriUe.id: FonduriUe,
    Kohesio.id: Kohesio,
    Oportunitati.id: Oportunitati,
}


def get_source(source_id: str) -> Source:
    try:
        return SOURCES[source_id]()
    except KeyError:
        known = ", ".join(sorted(SOURCES))
        raise KeyError(f"sursă necunoscută: {source_id!r} (cunoscute: {known})") from None


def sources_of_kind(kind: str) -> list[str]:
    """Id-urile adaptoarelor care produc un anumit fel de entitate."""
    return sorted(sid for sid, cls in SOURCES.items() if getattr(cls, "kind", "project") == kind)


__all__ = [
    "SOURCES",
    "DataGovRo",
    "FonduriUe",
    "FetchedFile",
    "Kohesio",
    "Oportunitati",
    "Source",
    "get_source",
    "sources_of_kind",
]
