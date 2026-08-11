"""Pagina apelurilor: `/apeluri`.

Restul registrului spune cine a luat bani. Pagina asta spune de unde se mai pot
lua: apelurile deschise acum, cu termen și buget.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import reflex as rx

from dashboard.state import ALL, _citeste, _money, _shorten, _stamp
from registru.config import CALLS_PARQUET

ACCENT = "iris"
PAGE_SIZE = 25

STATUS_COLORS = {"Activ": "green", "Urmează": "blue", "Închis": "gray"}


@dataclasses.dataclass
class Call:
    call_id: str = ""
    title: str = ""
    url: str = ""
    status: str = ""
    status_color: str = "gray"
    closes_at: str = ""
    days_left: str = ""
    budget: str = ""
    domains: str = ""
    beneficiaries: str = ""
    is_software: bool = False


def load_calls() -> pl.DataFrame:
    amprenta = _stamp(CALLS_PARQUET)
    if amprenta is None:
        return pl.DataFrame()
    return _citeste(str(CALLS_PARQUET), amprenta)


class CallsState(rx.State):
    search: str = ""
    status: str = "Activ"
    domain: str = ALL
    beneficiary: str = ALL
    min_budget: str = ""
    only_software: bool = False
    page: int = 0

    def _filtered(self) -> pl.DataFrame:
        frame = load_calls()
        if frame.is_empty():
            return frame
        if self.status != ALL:
            frame = frame.filter(pl.col("status") == self.status)
        if self.only_software and "is_software" in frame.columns:
            frame = frame.filter(pl.col("is_software"))
        if self.domain != ALL:
            frame = frame.filter(pl.col("domains").list.contains(self.domain))
        if self.beneficiary != ALL:
            frame = frame.filter(pl.col("beneficiaries").list.contains(self.beneficiary))
        if self.min_budget.strip():
            try:
                threshold = float(self.min_budget.replace(".", "").replace(",", "."))
            except ValueError:
                threshold = 0.0
            frame = frame.filter(pl.col("budget_amount").fill_null(0) >= threshold)
        if self.search.strip():
            needle = self.search.strip()
            frame = frame.filter(pl.col("title").str.contains(f"(?i){needle}", literal=False))
        # Termenul cel mai apropiat primul: dacă se închide luni, contează acum.
        return frame.sort("closes_at", nulls_last=True)

    @rx.var(cache=True)
    def has_calls(self) -> bool:
        return not load_calls().is_empty()

    @rx.var(cache=True)
    def statuses(self) -> list[str]:
        frame = load_calls()
        if frame.is_empty():
            return [ALL]
        return [ALL, *sorted(value for value in frame["status"].unique().to_list() if value)]

    @rx.var(cache=True)
    def domains(self) -> list[str]:
        return [ALL, *_exploded(load_calls(), "domains")]

    @rx.var(cache=True)
    def beneficiaries(self) -> list[str]:
        return [ALL, *_exploded(load_calls(), "beneficiaries")]

    @rx.var(cache=True)
    def total_label(self) -> str:
        return f"{self._filtered().height:,}".replace(",", ".")

    @rx.var(cache=True)
    def budget_label(self) -> str:
        frame = self._filtered()
        if frame.is_empty():
            return "—"
        euro = frame.filter(pl.col("budget_currency") == "EUR")
        return f"{_money(euro['budget_amount'].sum())} EUR"

    @rx.var(cache=True)
    def software_label(self) -> str:
        frame = self._filtered()
        if frame.is_empty() or "is_software" not in frame.columns:
            return "—"
        return f"{int(frame['is_software'].sum()):,}".replace(",", ".")

    @rx.var(cache=True)
    def page_label(self) -> str:
        total = max(1, -(-self._filtered().height // PAGE_SIZE))
        return f"{self.page + 1} / {total}"

    @rx.var(cache=True)
    def rows(self) -> list[Call]:
        frame = self._filtered()
        if frame.is_empty():
            return []
        today = date.today()
        out: list[Call] = []
        for row in frame.slice(self.page * PAGE_SIZE, PAGE_SIZE).to_dicts():
            closes = row.get("closes_at")
            left = (closes - today).days if closes else None
            amount = row.get("budget_amount")
            out.append(
                Call(
                    call_id=str(row.get("call_id") or ""),
                    title=_shorten(row.get("title"), 110),
                    url=str(row.get("url") or ""),
                    status=str(row.get("status") or "—"),
                    status_color=STATUS_COLORS.get(str(row.get("status") or ""), "gray"),
                    closes_at=str(closes) if closes else "—",
                    days_left=f"{left} zile" if left is not None and left >= 0 else "—",
                    budget=(
                        f"{_money(amount)} {row.get('budget_currency') or ''}".strip()
                        if amount
                        else "—"
                    ),
                    domains=_shorten(", ".join(row.get("domains") or []), 40),
                    beneficiaries=_shorten(", ".join(row.get("beneficiaries") or []), 40),
                    is_software=bool(row.get("is_software")),
                )
            )
        return out

    @rx.event
    def set_search(self, value: str) -> None:
        self.search = value
        self.page = 0

    @rx.event
    def set_status(self, value: str) -> None:
        self.status = value
        self.page = 0

    @rx.event
    def set_domain(self, value: str) -> None:
        self.domain = value
        self.page = 0

    @rx.event
    def set_beneficiary(self, value: str) -> None:
        self.beneficiary = value
        self.page = 0

    @rx.event
    def set_min_budget(self, value: str) -> None:
        self.min_budget = value
        self.page = 0

    @rx.event
    def reset_filters(self) -> None:
        self.search = ""
        self.status = "Activ"
        self.domain = ALL
        self.beneficiary = ALL
        self.min_budget = ""
        self.only_software = False
        self.page = 0

    @rx.event
    def toggle_software(self, value: bool) -> None:
        self.only_software = value
        self.page = 0

    @rx.event
    def next_page(self) -> None:
        self.page += 1

    @rx.event
    def prev_page(self) -> None:
        self.page = max(0, self.page - 1)


def _exploded(frame: pl.DataFrame, column: str) -> list[str]:
    """Valorile distincte dintr-o coloană-listă, pentru un meniu de filtrare."""
    if frame.is_empty() or column not in frame.columns:
        return []
    values = frame.explode(column)[column].drop_nulls().unique().to_list()
    return sorted(value for value in values if value)


def field(label: str, control: rx.Component, width: str = "12rem") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color_scheme="gray", weight="medium"),
        control,
        spacing="1",
        align="start",
        width=width,
    )


def call_row(call: Call) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.badge(
                call.status,
                color_scheme=call.status_color,  # ty: ignore[invalid-argument-type]
                variant="soft",
            )
        ),
        rx.table.cell(
            rx.link(rx.text(call.title, size="2"), href=call.url, is_external=True),
        ),
        rx.table.cell(rx.text(call.domains, size="1", color_scheme="gray")),
        rx.table.cell(rx.text(call.beneficiaries, size="1", color_scheme="gray")),
        rx.table.cell(rx.text(call.budget, size="2", align="right")),
        rx.table.cell(
            rx.vstack(
                rx.text(call.closes_at, size="2"),
                rx.text(call.days_left, size="1", color_scheme="gray"),
                spacing="0",
                align="start",
            )
        ),
        rx.table.cell(
            rx.cond(
                call.is_software,
                rx.badge("software", color_scheme=ACCENT, variant="soft"),
                rx.fragment(),
            )
        ),
    )


@rx.page(route="/", title="Apeluri deschise — Registru fonduri UE")
def calls_page() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading("Apeluri de finanțare", size="7"),
                    rx.text(
                        "Ce finanțări mai poți lua. Sursa: oportunitati-ue.gov.ro.",
                        size="2",
                        color_scheme="gray",
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.link(
                    rx.button("Proiecte finanțate", variant="soft", size="2"), href="/proiecte"
                ),
                rx.color_mode.button(),
                width="100%",
                align="center",
            ),
            rx.cond(
                CallsState.has_calls,
                rx.vstack(
                    rx.hstack(
                        rx.card(
                            rx.vstack(
                                rx.text("Apeluri", size="1", color_scheme="gray"),
                                rx.heading(CallsState.total_label, size="6"),
                                spacing="1",
                                align="start",
                            ),
                            flex="1",
                        ),
                        rx.card(
                            rx.vstack(
                                rx.text("Buget cumulat", size="1", color_scheme="gray"),
                                rx.heading(CallsState.budget_label, size="6"),
                                spacing="1",
                                align="start",
                            ),
                            flex="1",
                        ),
                        rx.card(
                            rx.vstack(
                                rx.text("Din care software", size="1", color_scheme="gray"),
                                rx.heading(CallsState.software_label, size="6"),
                                spacing="1",
                                align="start",
                            ),
                            flex="1",
                        ),
                        spacing="3",
                        width="100%",
                        wrap="wrap",
                    ),
                    rx.card(
                        rx.vstack(
                            field(
                                "Căutare",
                                rx.input(
                                    placeholder="Caută în titlul apelului…",
                                    value=CallsState.search,
                                    on_change=CallsState.set_search,
                                    width="100%",
                                ),
                                width="100%",
                            ),
                            rx.hstack(
                                field(
                                    "Stare",
                                    rx.select(
                                        CallsState.statuses,
                                        value=CallsState.status,
                                        on_change=CallsState.set_status,
                                        width="100%",
                                    ),
                                    width="10rem",
                                ),
                                field(
                                    "Domeniu",
                                    rx.select(
                                        CallsState.domains,
                                        value=CallsState.domain,
                                        on_change=CallsState.set_domain,
                                        width="100%",
                                    ),
                                    width="14rem",
                                ),
                                field(
                                    "Cine poate depune",
                                    rx.select(
                                        CallsState.beneficiaries,
                                        value=CallsState.beneficiary,
                                        on_change=CallsState.set_beneficiary,
                                        width="100%",
                                    ),
                                    width="16rem",
                                ),
                                field(
                                    "Buget minim",
                                    rx.input(
                                        placeholder="ex. 100000",
                                        value=CallsState.min_budget,
                                        on_change=CallsState.set_min_budget,
                                        width="100%",
                                    ),
                                    width="11rem",
                                ),
                                width="100%",
                                spacing="3",
                                align="end",
                                wrap="wrap",
                            ),
                            rx.hstack(
                                rx.hstack(
                                    rx.switch(
                                        checked=CallsState.only_software,
                                        on_change=CallsState.toggle_software,
                                        color_scheme=ACCENT,
                                    ),
                                    rx.text("Doar software și digitalizare", size="2"),
                                    spacing="2",
                                    align="center",
                                ),
                                rx.button(
                                    "Șterge filtrele",
                                    on_click=CallsState.reset_filters,
                                    variant="soft",
                                    color_scheme="gray",
                                ),
                                spacing="4",
                                align="center",
                                wrap="wrap",
                            ),
                            spacing="3",
                            width="100%",
                        ),
                        width="100%",
                    ),
                    rx.card(
                        rx.vstack(
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        rx.table.column_header_cell("Stare"),
                                        rx.table.column_header_cell("Apel"),
                                        rx.table.column_header_cell("Domenii"),
                                        rx.table.column_header_cell("Beneficiari"),
                                        rx.table.column_header_cell("Buget"),
                                        rx.table.column_header_cell("Se închide"),
                                        rx.table.column_header_cell(""),
                                    )
                                ),
                                rx.table.body(rx.foreach(CallsState.rows, call_row)),
                                variant="surface",
                                size="1",
                                width="100%",
                            ),
                            rx.hstack(
                                rx.button(
                                    "‹ Înapoi",
                                    on_click=CallsState.prev_page,
                                    variant="soft",
                                    size="2",
                                ),
                                rx.text(CallsState.page_label, size="2", color_scheme="gray"),
                                rx.button(
                                    "Înainte ›",
                                    on_click=CallsState.next_page,
                                    variant="soft",
                                    size="2",
                                ),
                                spacing="3",
                                justify="center",
                                width="100%",
                            ),
                            spacing="3",
                            width="100%",
                        ),
                        width="100%",
                        overflow_x="auto",
                    ),
                    spacing="4",
                    width="100%",
                ),
                rx.card(
                    rx.vstack(
                        rx.heading("Registrul se construiește", size="5"),
                        rx.text(
                            "Prima colectare durează 45-60 de minute: peste 5.000 de fișe de "
                            "apel, arhiva de proiecte și citirea PDF-urilor. Pagina se umple "
                            "singură când termină — nu trebuie reîncărcat nimic de mână.",
                            size="2",
                            color_scheme="gray",
                        ),
                        rx.text(
                            "Dacă a trecut mai mult, jurnalul serviciului `scheduler` spune ce "
                            "s-a întâmplat; local, `uv run registru schedule --once` face "
                            "aceeași rulare.",
                            size="1",
                            color_scheme="gray",
                        ),
                        spacing="3",
                        align="start",
                    ),
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
            padding_y="2rem",
        ),
        size="4",
        max_width="1400px",
    )
