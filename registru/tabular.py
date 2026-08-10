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

#: Rânduri care nu sunt proiecte, deși stau în tabel: totalurile din subsol și
#: capetele de coloană rămase. Se caută în numele beneficiarului.
NOT_A_BENEFICIARY = re.compile(
    r"^(total|subtotal|contributi|cheltuieli|valoare|suma|fonduri|nr\.? crt)",
    re.IGNORECASE,
)

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


def looks_like_header(row: list[str]) -> bool:
    """Rândul acesta este tot un antet, nu date?

    Fișierele oficiale repetă antetul: o dată tradus în engleză imediat sub cel
    românesc, și încă o dată în capul fiecărei pagini de PDF. Fără verificarea
    asta, „SMIS code” ajunge în registru ca și cum ar fi un cod de proiect.

    Verificarea rulează pentru fiecare rând al fiecărui fișier, deci întâi
    elimină ieftin ce nu are cum să fie antet. Un rând de date poartă coduri,
    sume și date calendaristice — adică cifre — iar un antet nu. Fără filtrul
    acesta, maparea completă s-ar face de zeci de mii de ori degeaba.
    """
    texte = [
        value
        for value in (cell(v) for v in row)
        if value and len(value) <= 90 and not any(ch.isdigit() for ch in value)
    ]
    if len(texte) < 2:
        return False
    return len(map_columns(texte)) >= 2


def frame_from_rows(rows: list[list[str]]) -> pl.DataFrame | None:
    """Rânduri brute -> cadru cu antet detectat. None dacă nu se recunoaște nimic."""
    if not rows:
        return None
    index = find_header_row(rows)
    if index is None:
        return None
    headers = dedupe_headers([cell(value) for value in rows[index]])
    body = [row for row in rows[index + 1 :] if not looks_like_header(row)]
    if not body:
        return None
    width = len(headers)
    data: dict[str, list[str]] = {name: [] for name in headers}
    for row in body:
        padded = [cell(value) for value in row[:width]] + [""] * max(0, width - len(row))
        for name, value in zip(headers, padded, strict=True):
            data[name].append(value)
    return pl.DataFrame(data)


#: Linia care desparte antetul de corp într-un tabel Markdown: `|---|---|`.
_SEPARATOR = re.compile(r"^\|[\s:|-]+\|?$")


def rows_from_markdown(text: str) -> list[list[str]]:
    """Rândurile tabelelor dintr-un document Markdown.

    anydoc convertește PDF-ul într-un singur tabel pentru tot documentul, nu
    unul per pagină. Asta este exact ce lipsea: `pdfplumber` detectează coloane
    separat pe fiecare pagină, iar o pagină cu o coloană în minus decalează tot
    ce urmează.
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or _SEPARATOR.match(line):
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


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
            pl.col("beneficiary_name").is_not_null()
            & (pl.col("beneficiary_name") != "")
            # Un beneficiar are literă. Când `beneficiary_name` conține o sumă,
            # coloanele s-au decalat la citirea PDF-ului, iar rândul nu spune ce
            # pretinde că spune.
            & pl.col("beneficiary_name").str.contains(r"[A-Za-zÀ-ž]{3}")
            & ~pl.col("beneficiary_name").str.contains(NOT_A_BENEFICIARY.pattern[1:])
        )
    return frame
