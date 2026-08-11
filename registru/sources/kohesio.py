"""Adaptor pentru Kohesio, platforma Comisiei Europene.

Interfața publică este un SPA peste un API REST nedocumentat, care răspunde la:

    https://kohesio.ec.europa.eu/api/projects?page=0&size=20&countryCode=RO

Atenție: parametrul este `countryCode`. `country=RO` întoarce HTTP 400.

Kohesio aduce descrieri și coordonate geografice, pe care listele naționale nu le
au. Nu aduce CUI-ul beneficiarului, deci nu poate fi singura sursă.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import polars as pl

from registru.config import RAW_DIR
from registru.schema import conform, empty_frame
from registru.sources.base import (
    FetchedFile,
    http_client,
    now_iso,
    read_manifest,
    sha256_file,
    write_manifest,
)

API = "https://kohesio.ec.europa.eu/api/projects"
PAGE_SIZE = 100
_TAGS = re.compile(r"<[^>]+>")


class Kohesio:
    id = "kohesio"
    kind = "project"
    name = "Kohesio (Comisia Europeană)"

    def __init__(self, country: str = "RO") -> None:
        self.country = country

    # ------------------------------------------------------------------ fetch

    def fetch(self, *, limit: int | None = None) -> list[FetchedFile]:
        """Salvează paginile de API ca JSON pe disc, ca orice altă dovadă."""
        fetched: list[FetchedFile] = []
        max_pages = limit if limit is not None else 10
        with http_client({"Referer": "https://kohesio.ec.europa.eu/en/"}) as client:
            for page in range(max_pages):
                params = {"page": page, "size": PAGE_SIZE, "countryCode": self.country}
                response = client.get(API, params=params)
                response.raise_for_status()
                payload = response.json()
                items = payload.get("list") or []
                if not items:
                    break
                relative = Path(self.id) / self.country / f"page-{page:04d}.json"
                target = RAW_DIR / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
                fetched.append(
                    FetchedFile(
                        source=self.id,
                        dataset=f"projects-{self.country}",
                        url=str(response.url),
                        path=str(relative),
                        sha256=sha256_file(target),
                        bytes=target.stat().st_size,
                        fetched_at=now_iso(),
                        meta={"page": page, "total": payload.get("numberResults")},
                    )
                )
                if len(items) < PAGE_SIZE:
                    break
        write_manifest(self.id, fetched)
        return fetched

    # ---------------------------------------------------------------- extract

    def extract(self) -> pl.DataFrame:
        rows: list[dict] = []
        for entry in read_manifest(self.id):
            path = RAW_DIR / entry.path
            if not path.exists():
                continue
            payload = json.loads(path.read_text("utf-8"))
            for index, item in enumerate(payload.get("list") or []):
                rows.append(_row(item, entry, index))
        if not rows:
            return empty_frame()
        return conform(pl.DataFrame(rows, infer_schema_length=None))


def _first(values, default=None):
    if isinstance(values, list):
        return values[0] if values else default
    return values if values is not None else default


def _clean_html(value: str | None) -> str | None:
    if not value:
        return None
    text = _TAGS.sub(" ", value).replace("&nbsp;", " ")
    return " ".join(text.split()) or None


def _parse_date(value) -> date | None:
    text = _first(value)
    if not text:
        return None
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _parse_float(value) -> float | None:
    text = _first(value)
    if text in (None, ""):
        return None
    try:
        return float(str(text).replace(",", "."))
    except ValueError:
        return None


def _row(item: dict, entry: FetchedFile, index: int) -> dict:
    coordinates = _first(item.get("coordinates")) or ""
    latitude = longitude = None
    if isinstance(coordinates, str) and "," in coordinates:
        head, _, tail = coordinates.partition(",")
        try:
            latitude, longitude = float(head.strip()), float(tail.strip())
        except ValueError:
            latitude = longitude = None
    return {
        "project_code": item.get("item"),
        "project_title": _first(item.get("originalLabels")) or _first(item.get("labels")),
        "project_summary": _clean_html(
            _first(item.get("originalDescriptions")) or _first(item.get("descriptions"))
        ),
        "start_date": _parse_date(item.get("startTimes")),
        "end_date": _parse_date(item.get("endTimes")),
        "total_eligible_amount": _parse_float(item.get("totalBudgets")),
        "eu_amount": _parse_float(item.get("euBudgets")),
        "currency": "EUR",
        "country": _first(item.get("countrycode")) or "RO",
        "specific_objective": _first(item.get("objectiveIds")),
        "latitude": latitude,
        "longitude": longitude,
        "programming_period": "2014-2020",
        "source": entry.source,
        "source_dataset": entry.dataset,
        "source_url": entry.url,
        "source_file": entry.path,
        "source_sha256": entry.sha256,
        "source_row": index,
        "fetched_at": entry.fetched_at,
    }
