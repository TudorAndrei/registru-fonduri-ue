"""Adaptor pentru portalul național de date deschise.

data.gov.ro rulează CKAN, deci are un API complet, nu doar butoane de descărcare:

    https://data.gov.ro/api/3/action/package_show?id=proiecte-contractate

Setul `proiecte-contractate` este publicat de MIPE, actualizat trimestrial, sub
licența OGL-ROU-1.0, și conține listele proiectelor contractate pe POIM, POC,
POCU, POR, POCA și POAT pentru 2014-2020.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
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
from registru.text import normalize_cui, squeeze

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
        raw = _read_tabular(path)
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

        frame = _clean(frame)
        return conform(frame)


# --------------------------------------------------------------------- utile


#: Câte rânduri de la început se caută pentru antetul real.
HEADER_SCAN_ROWS = 12


def _read_tabular(path: Path) -> pl.DataFrame | None:
    """Citește fișierul și găsește singur rândul de antet.

    Fișierele oficiale încep cu un banner („LISTA PROIECTELOR CONTRACTATE -
    PROGRAMUL OPERAȚIONAL …”), uneori pe mai multe rânduri, uneori cu celule
    îmbinate. Antetul adevărat este mai jos și nu este pe aceeași poziție de la
    un program la altul, deci se caută: rândul care dă cele mai multe coloane
    recunoscute câștigă.
    """
    if path.suffix.lower() == ".csv":
        raw = pl.read_csv(path, has_header=False, infer_schema_length=0, ignore_errors=True)
    else:
        # `calamine` citește și .xls, și .xlsx, și e mult mai rapid decât openpyxl.
        raw = pl.read_excel(path, engine="calamine", has_header=False, infer_schema_length=0)
    if raw.height == 0:
        return None

    best_index, best_score = None, 0
    for index in range(min(HEADER_SCAN_ROWS, raw.height)):
        candidate = [_cell(value) for value in raw.row(index)]
        score = len(map_columns(candidate))
        if score > best_score:
            best_index, best_score = index, score

    if best_index is None or best_score < 2:
        return None

    headers = _dedupe([_cell(value) for value in raw.row(best_index)])
    body = raw.slice(best_index + 1)
    if body.height == 0:
        return None
    return body.rename(dict(zip(body.columns, headers, strict=True)))


def _cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _dedupe(headers: list[str]) -> list[str]:
    """Numele de coloane trebuie să fie unice; celulele goale nu sunt."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, header in enumerate(headers):
        name = header or f"col_{index}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        result.append(name)
    return result


def _program_from_name(name: str) -> str | None:
    match = PROGRAM_PATTERN.search(name)
    if not match:
        return None
    return match.group(1).upper()


_MONEY = re.compile(r"[^0-9,.\-]")


def _to_float(value: str | None) -> float | None:
    """`1.234.567,89 lei` -> 1234567.89. Formatul românesc, plus gunoi."""
    if value is None:
        return None
    text = _MONEY.sub("", str(value)).strip()
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


#: Formatele de dată întâlnite în fișierele oficiale, în ordinea frecvenței.
DATE_FORMATS = (
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d.%m.%y",
    "%Y/%m/%d",
    "%d %B %Y",
)

#: Excel numără zilele de la 30 decembrie 1899.
_EXCEL_EPOCH = date(1899, 12, 30)


def _to_date(value: str | None) -> date | None:
    """Datele vin ca text în cinci formate, sau ca număr de serie Excel."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "n/a"}:
        return None
    head = text.split(" ")[0] if " " not in text[:11] else text[:10]
    for fmt in DATE_FORMATS:
        for candidate in (text, head):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    try:
        serial = float(text.replace(",", "."))
    except ValueError:
        return None
    if 1 < serial < 200_000:
        return _EXCEL_EPOCH + timedelta(days=int(serial))
    return None


def _clean(frame: pl.DataFrame) -> pl.DataFrame:
    exprs = []
    if "beneficiary_name" in frame.columns:
        exprs.append(
            pl.col("beneficiary_name")
            .map_elements(squeeze, return_dtype=pl.Utf8)
            .alias("beneficiary_name")
        )
    if "beneficiary_cui" in frame.columns:
        exprs.append(
            pl.col("beneficiary_cui")
            .map_elements(normalize_cui, return_dtype=pl.Utf8)
            .alias("beneficiary_cui")
        )
    for column in (
        "total_eligible_amount",
        "total_project_amount",
        "eu_amount",
        "payments_amount",
        "cofinancing_rate",
    ):
        if column in frame.columns:
            exprs.append(
                pl.col(column).map_elements(_to_float, return_dtype=pl.Float64).alias(column)
            )
    for column in ("start_date", "end_date"):
        if column in frame.columns:
            exprs.append(
                pl.col(column)
                .cast(pl.Utf8, strict=False)
                .map_elements(_to_date, return_dtype=pl.Date)
                .alias(column)
            )
    if exprs:
        frame = frame.with_columns(exprs)
    if "beneficiary_name" in frame.columns:
        frame = frame.filter(
            pl.col("beneficiary_name").is_not_null() & (pl.col("beneficiary_name") != "")
        )
    return frame
