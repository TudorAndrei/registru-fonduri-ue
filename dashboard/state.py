"""Starea tabloului de bord.

Registrul se citește o singură dată, din Parquet, și rămâne în memoria procesului.
Filtrarea se face cu Polars la fiecare schimbare — la ordinul de mărime al
registrului (sute de mii de rânduri) este instantanee și nu cere server de baze
de date.
"""

from __future__ import annotations

import dataclasses
import functools
from decimal import Decimal

import polars as pl
import reflex as rx

from registru.config import REGISTRY_PARQUET
from registru.geo import COUNTY_NAMES, NATIONAL, REGIONS

PAGE_SIZE = 25
ALL = "toate"

#: Ce se poate ordona, cu numele pe care îl vede omul. Numele coloanei din
#: registru nu are ce căuta într-un meniu.
SORT_COLUMNS: dict[str, str] = {
    "Valoare eligibilă": "total_eligible_amount",
    "Plăți efectuate": "payments_amount",
    "Scor software": "software_score",
    "Data de început": "start_date",
}
SORT_OPTIONS: list[str] = list(SORT_COLUMNS)


@dataclasses.dataclass
class Project:
    """Un rând, gata de afișat.

    Reflex 0.9 a scos `rx.Base`; modelele de date sunt dataclass-uri simple.
    """

    record_id: str = ""
    program: str = ""
    beneficiary_name: str = ""
    beneficiary_cui: str = ""
    project_title: str = ""
    county: str = ""
    total_eligible_amount: str = ""
    payments: str = ""
    software_score: str = ""
    software_label: str = ""
    is_software: bool = False
    source_url: str = ""


#: O bară dintr-un grafic. Recharts cere dicționare, nu dataclass-uri.
Bucket = dict[str, str | float]


@functools.lru_cache(maxsize=1)
def load_registry() -> pl.DataFrame:
    if not REGISTRY_PARQUET.exists():
        return pl.DataFrame()
    return pl.read_parquet(REGISTRY_PARQUET)


def _money(value: object) -> str:
    """Sumele Polars pot veni ca int, float sau Decimal; orice altceva e „—”."""
    if not isinstance(value, (int, float, Decimal)):
        return "—"
    return f"{float(value):,.0f}".replace(",", ".")


class State(rx.State):
    """Filtrele și rezultatele."""

    search: str = ""
    program: str = ALL
    county: str = ALL
    region: str = ALL
    label: str = ALL
    only_software: bool = False
    min_amount: str = ""
    page: int = 0
    sort_by: str = "total_eligible_amount"

    # ------------------------------------------------------------- filtrarea

    def _filtered(self) -> pl.DataFrame:
        frame = load_registry()
        if frame.is_empty():
            return frame
        if self.only_software and "is_software" in frame.columns:
            frame = frame.filter(pl.col("is_software"))
        if self.program != ALL:
            frame = frame.filter(pl.col("program") == self.program)
        if self.county != ALL:
            # `counties` este o listă parsată: un proiect multi-județean apare
            # sub fiecare județ al lui.
            frame = frame.filter(pl.col("counties").list.contains(self.county))
        if self.region != ALL:
            frame = frame.filter(pl.col("regions").list.contains(self.region))
        if self.label != ALL:
            frame = frame.filter(pl.col("software_label") == self.label)
        if self.search.strip():
            needle = self.search.strip()
            frame = frame.filter(
                pl.col("beneficiary_name").str.contains(f"(?i){needle}", literal=False)
                | pl.col("project_title").fill_null("").str.contains(f"(?i){needle}", literal=False)
                | pl.col("beneficiary_cui").fill_null("").str.contains(needle, literal=True)
            )
        if self.min_amount.strip():
            try:
                threshold = float(self.min_amount.replace(".", "").replace(",", "."))
            except ValueError:
                threshold = 0.0
            frame = frame.filter(pl.col("total_eligible_amount").fill_null(0) >= threshold)
        return frame

    # ------------------------------------------------------- valori calculate

    @rx.var(cache=True)
    def has_registry(self) -> bool:
        return not load_registry().is_empty()

    @rx.var(cache=True)
    def total_rows(self) -> int:
        return self._filtered().height

    @rx.var(cache=True)
    def total_rows_label(self) -> str:
        return f"{self.total_rows:,}".replace(",", ".")

    @rx.var(cache=True)
    def total_amount_label(self) -> str:
        frame = self._filtered()
        if frame.is_empty():
            return "—"
        return _money(frame["total_eligible_amount"].sum())

    @rx.var(cache=True)
    def payments_label(self) -> str:
        """Plăți efectuate, nu contribuția UE.

        Coloana `eu_amount` este populată în 0% din rândurile naționale — listele
        MIPE nu o publică. `payments_amount` acoperă 86% și spune același lucru
        util: cât a ajuns efectiv la beneficiar.
        """
        frame = self._filtered()
        if frame.is_empty():
            return "—"
        return _money(frame["payments_amount"].sum())

    @rx.var(cache=True)
    def beneficiary_count_label(self) -> str:
        frame = self._filtered()
        if frame.is_empty():
            return "—"
        column = "beneficiary_key" if "beneficiary_key" in frame.columns else "beneficiary_name"
        return f"{frame[column].n_unique():,}".replace(",", ".")

    @rx.var(cache=True)
    def software_share_label(self) -> str:
        frame = self._filtered()
        if frame.is_empty() or "is_software" not in frame.columns:
            return "—"
        mean = frame["is_software"].mean()
        share = float(mean) if isinstance(mean, (int, float, Decimal)) else 0.0
        return f"{100 * share:.0f}%"

    @rx.var(cache=True)
    def programs(self) -> list[str]:
        return [ALL, *_distinct(load_registry(), "program")]

    @rx.var(cache=True)
    def counties(self) -> list[str]:
        """Lista închisă a județelor, nu valorile distincte din fișier.

        Coloana `county` conține text liber — 1.410 valori distincte pentru 42 de
        județe — deci un `unique()` peste ea dă un filtru de necitit.
        """
        return [ALL, NATIONAL, *COUNTY_NAMES]

    @rx.var(cache=True)
    def regions(self) -> list[str]:
        return [ALL, *REGIONS]

    @rx.var(cache=True)
    def sort_label(self) -> str:
        for label, column in SORT_COLUMNS.items():
            if column == self.sort_by:
                return label
        return SORT_OPTIONS[0]

    @rx.var(cache=True)
    def labels(self) -> list[str]:
        return [ALL, *_distinct(load_registry(), "software_label")]

    @rx.var(cache=True)
    def page_count(self) -> int:
        return max(1, -(-self.total_rows // PAGE_SIZE))

    @rx.var(cache=True)
    def page_label(self) -> str:
        return f"{self.page + 1} / {self.page_count}"

    @rx.var(cache=True)
    def rows(self) -> list[Project]:
        frame = self._filtered()
        if frame.is_empty():
            return []
        if self.sort_by in frame.columns:
            frame = frame.sort(self.sort_by, descending=True, nulls_last=True)
        window = frame.slice(self.page * PAGE_SIZE, PAGE_SIZE)
        projects: list[Project] = []
        for row in window.to_dicts():
            projects.append(
                Project(
                    record_id=str(row.get("record_id") or ""),
                    program=str(row.get("program") or "—"),
                    # La POCU, coloana de beneficiar conține și lista partenerilor,
                    # uneori de câteva sute de rânduri. Se taie la afișare.
                    beneficiary_name=_shorten(row.get("beneficiary_name"), 70),
                    beneficiary_cui=str(row.get("beneficiary_cui") or "—"),
                    project_title=_shorten(row.get("project_title")),
                    county=_shorten(", ".join(row.get("counties") or []), 34),
                    total_eligible_amount=_money(row.get("total_eligible_amount")),
                    payments=_money(row.get("payments_amount")),
                    software_score=f"{row.get('software_score') or 0:.2f}",
                    software_label=str(row.get("software_label") or "—"),
                    is_software=bool(row.get("is_software")),
                    source_url=str(row.get("source_url") or ""),
                )
            )
        return projects

    @rx.var(cache=True)
    def by_program(self) -> list[Bucket]:
        return _buckets(self._filtered(), "program", "total_eligible_amount")

    @rx.var(cache=True)
    def by_label(self) -> list[Bucket]:
        frame = self._filtered()
        if frame.is_empty() or "software_label" not in frame.columns:
            return []
        grouped = (
            frame.group_by("software_label")
            .agg(pl.len().alias("value"))
            .sort("value", descending=True)
            .head(8)
        )
        return [{"name": str(row[0] or "—"), "value": float(row[1])} for row in grouped.iter_rows()]

    @rx.var(cache=True)
    def top_beneficiaries(self) -> list[Bucket]:
        return _buckets(self._filtered(), "beneficiary_name", "total_eligible_amount", top=10)

    # -------------------------------------------------------------- evenimente

    @rx.event
    def set_search(self, value: str) -> None:
        self.search = value
        self.page = 0

    @rx.event
    def set_program(self, value: str) -> None:
        self.program = value
        self.page = 0

    @rx.event
    def set_county(self, value: str) -> None:
        self.county = value
        self.page = 0

    @rx.event
    def set_region(self, value: str) -> None:
        self.region = value
        self.page = 0

    @rx.event
    def set_label(self, value: str) -> None:
        self.label = value
        self.page = 0

    @rx.event
    def set_min_amount(self, value: str) -> None:
        self.min_amount = value
        self.page = 0

    @rx.event
    def toggle_software(self, value: bool) -> None:
        self.only_software = value
        self.page = 0

    @rx.event
    def set_sort(self, value: str) -> None:
        self.sort_by = SORT_COLUMNS.get(value, "total_eligible_amount")
        self.page = 0

    @rx.event
    def next_page(self) -> None:
        if self.page + 1 < self.page_count:
            self.page += 1

    @rx.event
    def prev_page(self) -> None:
        self.page = max(0, self.page - 1)

    @rx.event
    def reset_filters(self) -> None:
        self.search = ""
        self.program = ALL
        self.county = ALL
        self.region = ALL
        self.label = ALL
        self.min_amount = ""
        self.only_software = False
        self.sort_by = SORT_COLUMNS[SORT_OPTIONS[0]]
        self.page = 0


def _distinct(frame: pl.DataFrame, column: str) -> list[str]:
    if frame.is_empty() or column not in frame.columns:
        return []
    values = [value for value in frame[column].unique().to_list() if value]
    return sorted(str(value) for value in values)


def _buckets(frame: pl.DataFrame, key: str, value: str, top: int = 12) -> list[Bucket]:
    """Sume pe categorie, exprimate în milioane.

    Sumele brute sunt de ordinul sutelor de miliarde de lei, iar axa graficului
    le-ar afișa trunchiat. Se împart aici, iar titlul graficului spune unitatea.
    """
    if frame.is_empty() or key not in frame.columns:
        return []
    grouped = (
        frame.group_by(key)
        .agg(pl.col(value).sum().alias("value"))
        .sort("value", descending=True, nulls_last=True)
        .head(top)
    )
    return [
        {"name": _shorten(row[0], 28), "value": round(float(row[1] or 0) / 1e6, 1)}
        for row in grouped.iter_rows()
    ]


def _shorten(value: object, width: int = 90) -> str:
    text = str(value or "—")
    return text if len(text) <= width else text[: width - 1] + "…"
