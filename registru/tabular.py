"""Citirea tabelelor publicate de autorități, indiferent de format.

Toate listele oficiale au aceleași boli, fie că vin în XLSX, CSV sau PDF:

- antetul nu este pe primul rând, ci sub un banner cu celule îmbinate, și nu pe
  aceeași poziție de la un program la altul;
- aceeași coloană are cinci nume diferite;
- sumele sunt scrise românește, cu punct la mii și virgulă la zecimale, sau
  americănește, în același fișier;
- datele apar în cinci formate, plus numere de serie Excel.

Leacurile stau aici, o singură dată, iar adaptoarele le folosesc.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from registru.headers import map_columns
from registru.text import normalize_cui, squeeze

#: Câte rânduri de la început se caută pentru antetul real.
HEADER_SCAN_ROWS = 12

#: Formatele de dată întâlnite în fișierele oficiale, în ordinea frecvenței.
DATE_FORMATS = (
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d.%m.%y",
    "%Y/%m/%d",
)

#: Excel numără zilele de la 30 decembrie 1899.
_EXCEL_EPOCH = date(1899, 12, 30)
_MONEY = re.compile(r"[^0-9,.\-]")

MONEY_COLUMNS = (
    "total_eligible_amount",
    "total_project_amount",
    "eu_amount",
    "payments_amount",
    "cofinancing_rate",
)


def cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def dedupe_headers(headers: list[str]) -> list[str]:
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


def find_header_row(rows: list[list[str]]) -> int | None:
    """Rândul care dă cele mai multe coloane recunoscute câștigă."""
    best_index, best_score = None, 0
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        score = len(map_columns([cell(value) for value in row]))
        if score > best_score:
            best_index, best_score = index, score
    return best_index if best_score >= 2 else None


def frame_from_rows(rows: list[list[str]]) -> pl.DataFrame | None:
    """Rânduri brute -> cadru cu antet detectat. None dacă nu se recunoaște nimic."""
    if not rows:
        return None
    index = find_header_row(rows)
    if index is None:
        return None
    headers = dedupe_headers([cell(value) for value in rows[index]])
    body = rows[index + 1 :]
    if not body:
        return None
    width = len(headers)
    data = {name: [] for name in headers}
    for row in body:
        padded = [cell(value) for value in row[:width]] + [""] * max(0, width - len(row))
        for name, value in zip(headers, padded, strict=True):
            data[name].append(value)
    return pl.DataFrame(data)


def read_tabular(path: Path) -> pl.DataFrame | None:
    """Citește XLSX, XLS sau CSV și găsește singur rândul de antet.

    Registrul de lucru poate avea prima foaie goală sau de copertă, iar tabelul
    pe a doua, deci se încearcă toate foile și se ia prima care dă coloane
    recunoscute.
    """
    if path.suffix.lower() == ".csv":
        raw = pl.read_csv(path, has_header=False, infer_schema_length=0, ignore_errors=True)
        if raw.height == 0:
            return None
        return frame_from_rows([list(row) for row in raw.iter_rows()])

    # `calamine` citește și .xls, și .xlsx, și e mult mai rapid decât openpyxl.
    sheets = pl.read_excel(
        path,
        engine="calamine",
        sheet_id=0,
        has_header=False,
        infer_schema_length=0,
        raise_if_empty=False,
    )
    for sheet in sheets.values():
        if sheet.height == 0:
            continue
        frame = frame_from_rows([list(row) for row in sheet.iter_rows()])
        if frame is not None:
            return frame
    return None


def to_float(value: str | None) -> float | None:
    """`1.234.567,89 lei` -> 1234567.89. Formatul românesc, plus gunoi."""
    if value is None:
        return None
    text = _MONEY.sub("", str(value)).strip()
    if not text or text in {"-", ".", ","}:
        return None
    if "," in text and "." in text:
        # Ultimul separator este cel zecimal, oricare ar fi el.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def to_date(value: str | None) -> date | None:
    """Datele vin ca text în cinci formate, sau ca număr de serie Excel."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "n/a"}:
        return None
    head = text.split(" ")[0]
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


def clean_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Curăță numele, CUI-urile, sumele și datele; aruncă rândurile fără beneficiar."""
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
    for column in MONEY_COLUMNS:
        if column in frame.columns:
            exprs.append(
                pl.col(column)
                .cast(pl.Utf8, strict=False)
                .map_elements(to_float, return_dtype=pl.Float64)
                .alias(column)
            )
    for column in ("start_date", "end_date"):
        if column in frame.columns:
            exprs.append(
                pl.col(column)
                .cast(pl.Utf8, strict=False)
                .map_elements(to_date, return_dtype=pl.Date)
                .alias(column)
            )
    if exprs:
        frame = frame.with_columns(exprs)
    if "beneficiary_name" in frame.columns:
        frame = frame.filter(
            pl.col("beneficiary_name").is_not_null() & (pl.col("beneficiary_name") != "")
        )
    return frame
