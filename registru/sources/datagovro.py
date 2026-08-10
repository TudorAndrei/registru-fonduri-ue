"""Adaptor pentru portalul național de date deschise.

data.gov.ro rulează CKAN, deci are un API complet, nu doar butoane de descărcare:

    https://data.gov.ro/api/3/action/package_show?id=proiecte-contractate

Setul `proiecte-contractate` este publicat de MIPE, actualizat trimestrial, sub
licența OGL-ROU-1.0, și conține listele proiectelor contractate pe POIM, POC,
POCU, POR, POCA și POAT pentru 2014-2020.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from registru.config import RAW_DIR
from registru.headers import map_columns
from registru.schema import conform
from registru.sources.base import (
    FetchedFile,
    download,
    http_client,
    now_iso,
    read_manifest,
    sha256_file,
    write_manifest,
)
from registru.tabular import clean_frame, read_tabular

CKAN_API = "https://data.gov.ro/api/3/action"

#: Seturile de date urmărite. Cheia este id-ul CKAN.
DATASETS: dict[str, str] = {
    "proiecte-contractate": "Liste proiecte contractate, programe MIPE 2014-2020",
    "programele-nationale-2021-2027-afaceri-interne-proiecte-selectate": (
        "Programe naționale 2021-2027 afaceri interne, proiecte selectate"
    ),
}

#: Programele recunoscute din numele fișierului.
PROGRAM_PATTERN = re.compile(
    r"\b(poim|pocu|pocа|poca|poat|poad|por|poc|pcidif|pocidif|pndr|regio|podca)\b",
    re.IGNORECASE,
)

TABULAR_FORMATS = {"xlsx", "xls", "csv"}


class DataGovRo:
    id = "datagovro"
    kind = "project"
    name = "data.gov.ro (CKAN)"

    def __init__(self, datasets: list[str] | None = None) -> None:
        self.datasets = datasets or list(DATASETS)

    # ------------------------------------------------------------------ fetch

    def fetch(self, *, limit: int | None = None) -> list[FetchedFile]:
        fetched: list[FetchedFile] = []
        with http_client() as client:
            for dataset in self.datasets:
                response = client.get(f"{CKAN_API}/package_show", params={"id": dataset})
                response.raise_for_status()
                package = response.json()["result"]
                resources = [
                    resource
                    for resource in package.get("resources", [])
                    if (resource.get("format") or "").lower() in TABULAR_FORMATS
                ]
                resources.sort(key=lambda r: r.get("last_modified") or "", reverse=True)
                if limit is not None:
                    resources = resources[:limit]
                for resource in resources:
                    fetched.append(self._fetch_resource(client, dataset, resource))
        write_manifest(self.id, fetched)
        return fetched

    def _fetch_resource(self, client, dataset: str, resource: dict) -> FetchedFile:
        url = resource.get("datagovro_download_url") or resource["url"]
        suffix = Path(url.split("?")[0]).suffix or f".{(resource.get('format') or 'bin').lower()}"
        relative = Path(self.id) / dataset / f"{resource['id']}{suffix}"
        target = RAW_DIR / relative
        download(client, url, target)
        return FetchedFile(
            source=self.id,
            dataset=dataset,
            url=url,
            path=str(relative),
            sha256=sha256_file(target),
            bytes=target.stat().st_size,
            fetched_at=now_iso(),
            meta={
                "resource_id": resource["id"],
                "resource_name": resource.get("name"),
                "format": resource.get("format"),
                "last_modified": resource.get("last_modified"),
            },
        )

    # ---------------------------------------------------------------- extract

    def extract(self) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        for entry in read_manifest(self.id):
            path = RAW_DIR / entry.path
            if not path.exists():
                continue
            try:
                frame = self._extract_file(entry, path)
            except Exception as error:  # noqa: BLE001 — un fișier stricat nu oprește restul
                print(f"  ! {entry.path}: {type(error).__name__}: {error}")
                continue
            if frame is not None and frame.height:
                frames.append(frame)
        if not frames:
            from registru.schema import empty_frame

            return empty_frame()
        return pl.concat(frames, how="vertical_relaxed")

    def _extract_file(self, entry: FetchedFile, path: Path) -> pl.DataFrame | None:
        raw = read_tabular(path)
        if raw is None or raw.height == 0:
            return None
        mapping = map_columns(raw.columns)
        if "beneficiary_name" not in mapping.values():
            # Fără beneficiar nu avem un rând de registru; probabil e un tabel de sinteză.
            return None

        frame = raw.rename(mapping).select(list(mapping.values()))
        frame = frame.with_row_index("source_row").with_columns(
            pl.col("source_row").cast(pl.Int64),
            pl.lit(self.id).alias("source"),
            pl.lit(entry.dataset).alias("source_dataset"),
            pl.lit(entry.url).alias("source_url"),
            pl.lit(entry.path).alias("source_file"),
            pl.lit(entry.sha256).alias("source_sha256"),
            pl.lit(entry.fetched_at).alias("fetched_at"),
            pl.lit("RO").alias("country"),
            # Listele MIPE sunt exprimate în lei, marcat în antetul coloanei de valoare.
            pl.lit("RON").alias("currency"),
            pl.lit("2014-2020").alias("programming_period"),
        )
        program = _program_from_name(entry.meta.get("resource_name") or entry.path)
        if program and "program" not in frame.columns:
            frame = frame.with_columns(pl.lit(program).alias("program"))

        return conform(clean_frame(frame))


# --------------------------------------------------------------------- utile


def _program_from_name(name: str) -> str | None:
    match = PROGRAM_PATTERN.search(name)
    return match.group(1).upper() if match else None
