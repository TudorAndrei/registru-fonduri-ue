"""Registrul adaptoarelor de sursă."""

from __future__ import annotations

from registru.sources.base import FetchedFile, Source
from registru.sources.datagovro import DataGovRo
from registru.sources.kohesio import Kohesio

SOURCES: dict[str, type] = {
    DataGovRo.id: DataGovRo,
    Kohesio.id: Kohesio,
}


def get_source(source_id: str) -> Source:
    try:
        return SOURCES[source_id]()
    except KeyError:
        known = ", ".join(sorted(SOURCES))
        raise KeyError(f"sursă necunoscută: {source_id!r} (cunoscute: {known})") from None


__all__ = ["SOURCES", "DataGovRo", "FetchedFile", "Kohesio", "Source", "get_source"]
