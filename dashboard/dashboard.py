"""Tabloul de bord: caută în registru, filtrează, vezi agregatele.

uv run --extra dashboard reflex run
"""

from __future__ import annotations

import reflex as rx

from dashboard.state import ALL, SORT_OPTIONS, Bucket, Project, State

ACCENT = "iris"


def kpi(label: str, value: rx.Var | str, hint: str = "") -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="1", color_scheme="gray", weight="medium"),
            rx.heading(value, size="6"),
            rx.text(hint, size="1", color_scheme="gray") if hint else rx.fragment(),
            spacing="1",
            align="start",
        ),
        size="2",
        flex="1",
        min_width="10rem",
    )


def field(label: str, control: rx.Component, width: str = "12rem") -> rx.Component:
    """Un control cu titlul lui deasupra.

    Patru selectoare identice, toate pe „toate”, nu spun ce filtrează.
    """
    return rx.vstack(
        rx.text(label, size="1", color_scheme="gray", weight="medium"),
        control,
        spacing="1",
        align="start",
        width=width,
    )


def filters() -> rx.Component:
    return rx.card(
        rx.vstack(
            field(
                "Căutare",
                rx.input(
                    placeholder="Beneficiar, titlu de proiect sau CUI…",
                    value=State.search,
                    on_change=State.set_search,
                    width="100%",
                ),
                width="100%",
            ),
            rx.hstack(
                field(
                    "Program",
                    rx.select(
                        State.programs,
                        value=State.program,
                        on_change=State.set_program,
                        width="100%",
                    ),
                ),
                field(
                    "Regiune de dezvoltare",
                    rx.select(
                        State.regions,
                        value=State.region,
                        on_change=State.set_region,
                        width="100%",
                    ),
                ),
                field(
                    "Județ",
                    rx.select(
                        State.counties,
                        value=State.county,
                        on_change=State.set_county,
                        width="100%",
                    ),
                ),
                field(
                    "Clasificare",
                    rx.select(
                        State.labels,
                        value=State.label,
                        on_change=State.set_label,
                        width="100%",
                    ),
                ),
                field(
                    "Stadiu",
                    rx.select(
                        State.statuses,
                        value=State.status,
                        on_change=State.set_status,
                        width="100%",
                    ),
                ),
                field(
                    "Valoare eligibilă minimă (lei)",
                    rx.input(
                        placeholder="ex. 1000000",
                        value=State.min_amount,
                        on_change=State.set_min_amount,
                        width="100%",
                    ),
                    width="14rem",
                ),
                field(
                    "Ordonare după",
                    rx.select(
                        SORT_OPTIONS,
                        value=State.sort_label,
                        on_change=State.set_sort,
                        width="100%",
                    ),
                    width="14rem",
                ),
                width="100%",
                spacing="3",
                align="end",
                wrap="wrap",
            ),
            rx.hstack(
                rx.hstack(
                    rx.switch(
                        checked=State.only_software,
                        on_change=State.toggle_software,
                        color_scheme=ACCENT,
                    ),
                    rx.text("Doar proiecte software", size="2"),
                    spacing="2",
                    align="center",
                ),
                rx.button(
                    "Șterge filtrele",
                    on_click=State.reset_filters,
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
    )


def bar_chart(title: str, data: rx.Var[list[Bucket]]) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(title, weight="bold", size="2"),
            rx.recharts.bar_chart(
                rx.recharts.bar(data_key="value", fill=rx.color(ACCENT, 9), radius=[4, 4, 0, 0]),
                rx.recharts.x_axis(data_key="name", hide=False, font_size="10px"),
                rx.recharts.y_axis(width=56, font_size="10px"),
                rx.recharts.graphing_tooltip(),
                data=data,
                height=260,
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        flex="1",
        min_width="22rem",
    )


def row(project: Project) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.badge(project.program, color_scheme="gray", variant="soft")),
        rx.table.cell(
            rx.vstack(
                rx.text(project.beneficiary_name, weight="medium", size="2"),
                rx.text(project.beneficiary_cui, size="1", color_scheme="gray"),
                spacing="0",
                align="start",
            )
        ),
        rx.table.cell(rx.text(project.project_title, size="2")),
        rx.table.cell(rx.text(project.county, size="2")),
        rx.table.cell(rx.text(project.total_eligible_amount, size="2", align="right")),
        rx.table.cell(rx.text(project.payments, size="2", align="right")),
        rx.table.cell(
            # Reflex tipează `color_scheme` ca literal, deși acceptă un Var la
            # rulare; culoarea vine din stare, deci verificatorul nu o poate ști.
            rx.badge(
                project.status,
                color_scheme=project.status_color,  # ty: ignore[invalid-argument-type]
                variant="soft",
            )
        ),
        rx.table.cell(
            rx.hstack(
                rx.badge(
                    project.software_label,
                    color_scheme=rx.cond(project.is_software, ACCENT, "gray"),
                    variant="soft",
                ),
                rx.text(project.software_score, size="1", color_scheme="gray"),
                spacing="2",
                align="center",
            )
        ),
        rx.table.cell(
            # Către fișa din registru, nu către fișierul Excel: nimeni nu vrea
            # să descarce 900 KB de tabel ca să vadă un rând.
            rx.link(
                rx.button("Deschide", size="1", variant="soft"),
                href=f"/proiect/{project.record_id}",
            )
        ),
    )


def table() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Program"),
                        rx.table.column_header_cell("Beneficiar"),
                        rx.table.column_header_cell("Proiect"),
                        rx.table.column_header_cell("Județ"),
                        rx.table.column_header_cell("Eligibil"),
                        rx.table.column_header_cell("Plătit"),
                        rx.table.column_header_cell("Stadiu"),
                        rx.table.column_header_cell("Clasificare"),
                        rx.table.column_header_cell("Fișă"),
                    )
                ),
                rx.table.body(rx.foreach(State.rows, row)),
                variant="surface",
                size="1",
                width="100%",
            ),
            rx.hstack(
                rx.button("‹ Înapoi", on_click=State.prev_page, variant="soft", size="2"),
                rx.text(State.page_label, size="2", color_scheme="gray"),
                rx.button("Înainte ›", on_click=State.next_page, variant="soft", size="2"),
                spacing="3",
                align="center",
                justify="center",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
        overflow_x="auto",
    )


def empty_state() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Registrul se construiește", size="5"),
            rx.text(
                "Prima colectare durează 45-60 de minute. Pagina se umple singură când "
                "termină. Local, rularea se pornește cu `uv run registru schedule --once`.",
                size="2",
                color_scheme="gray",
            ),
            spacing="3",
            align="start",
        ),
        width="100%",
    )


@rx.page(route="/proiecte", title="Proiecte finanțate — Registru fonduri UE")
def projects_page() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading("Proiecte deja finanțate", size="7"),
                    rx.text(
                        "Cine a luat bani și pentru ce — util ca să vezi ce trece la evaluare.",
                        color_scheme="gray",
                        size="2",
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.link(rx.button("Apeluri deschise", variant="soft", size="2"), href="/"),
                rx.color_mode.button(),
                width="100%",
                align="center",
            ),
            rx.cond(
                State.has_registry,
                rx.vstack(
                    rx.hstack(
                        kpi("Proiecte", State.total_rows_label),
                        kpi("Beneficiari", State.beneficiary_count_label),
                        kpi("Valoare eligibilă", State.total_amount_label),
                        kpi("Plăți către beneficiari", State.payments_label),
                        kpi("Cotă software", State.software_share_label),
                        spacing="3",
                        width="100%",
                        wrap="wrap",
                    ),
                    filters(),
                    rx.hstack(
                        bar_chart("Valoare eligibilă pe program (mil. lei)", State.by_program),
                        bar_chart("Proiecte pe clasificare", State.by_label),
                        spacing="3",
                        width="100%",
                        wrap="wrap",
                    ),
                    rx.hstack(
                        bar_chart(
                            "Primii 10 beneficiari după valoare (mil. lei)",
                            State.top_beneficiaries,
                        ),
                        width="100%",
                    ),
                    table(),
                    spacing="4",
                    width="100%",
                ),
                empty_state(),
            ),
            rx.text(State.freshness, size="1", color_scheme="gray"),
            rx.text(
                "Sursele: data.gov.ro (OGL-ROU-1.0), Kohesio și oportunitati-ue.gov.ro. "
                f"Fără filtru = {ALL}. Fiecare rând are legătura către fișierul original.",
                size="1",
                color_scheme="gray",
            ),
            spacing="4",
            width="100%",
            padding_y="2rem",
        ),
        size="4",
        max_width="1400px",
    )


# Tema stă în `rxconfig.py`, prin `RadixThemesPlugin`; `rx.App(theme=...)` este scos în 1.0.
# Importul înregistrează ruta /proiect/[record_id] prin decoratorul @rx.page.
import dashboard.calls  # noqa: E402, F401
import dashboard.project  # noqa: E402, F401

app = rx.App()
