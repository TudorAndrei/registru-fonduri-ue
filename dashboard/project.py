"""Pagina unui proiect: `/proiect/<record_id>`.

Fiecare rând din registru are un URL propriu. Aceasta este singura pagină per
proiect care există pentru listele naționale 2014-2020 — autoritățile publică
doar fișiere Excel.
"""

from __future__ import annotations

import dataclasses

import polars as pl
import reflex as rx

from dashboard.state import _money, load_registry
from registru.links import anaf_url, kohesio_search_url, project_url

ACCENT = "iris"


@dataclasses.dataclass
class Row:
    """O pereche etichetă-valoare, afișată în fișa proiectului."""

    label: str = ""
    value: str = ""


class ProjectState(rx.State):
    """Reflex creează singur `record_id` din segmentul dinamic al rutei.

    Nu se declară ca variabilă de stare — asta ar da
    `DynamicRouteArgShadowsStateVarError` la compilare.
    """

    def _record(self) -> dict | None:
        frame = load_registry()
        if frame.is_empty() or not self.record_id:
            return None
        match = frame.filter(pl.col("record_id") == self.record_id)
        return match.to_dicts()[0] if match.height else None

    @rx.var(cache=True)
    def found(self) -> bool:
        return self._record() is not None

    @rx.var(cache=True)
    def title(self) -> str:
        record = self._record()
        return str((record or {}).get("project_title") or "Proiect fără titlu")

    @rx.var(cache=True)
    def beneficiary(self) -> str:
        record = self._record()
        return str((record or {}).get("beneficiary_name") or "—")

    @rx.var(cache=True)
    def summary(self) -> str:
        record = self._record()
        return str((record or {}).get("project_summary") or "")

    @rx.var(cache=True)
    def facts(self) -> list[Row]:
        record = self._record()
        if not record:
            return []
        counties = ", ".join(record.get("counties") or []) or "—"
        regions = ", ".join(record.get("regions") or []) or "—"
        return [
            Row(label="Program", value=_text(record.get("program"))),
            Row(label="Perioadă de programare", value=_text(record.get("programming_period"))),
            Row(label="Cod proiect", value=_text(record.get("project_code"))),
            Row(label="Beneficiar", value=_text(record.get("beneficiary_name"))),
            Row(label="CUI beneficiar", value=_text(record.get("beneficiary_cui"))),
            Row(label="Tip beneficiar", value=_text(record.get("beneficiary_type"))),
            Row(label="Județe", value=counties),
            Row(label="Regiuni", value=regions),
            Row(label="Localitate", value=_text(record.get("locality"))),
            Row(label="Dată de început", value=_text(record.get("start_date"))),
            Row(label="Dată de sfârșit", value=_text(record.get("end_date"))),
            Row(label="Stadiu", value=_text(record.get("project_status"))),
            Row(
                label="Valoare eligibilă",
                value=_money(record.get("total_eligible_amount")),
            ),
            Row(label="Valoare totală", value=_money(record.get("total_project_amount"))),
            Row(label="Plăți efectuate", value=_money(record.get("payments_amount"))),
            Row(label="Rată de cofinanțare UE", value=_text(record.get("cofinancing_rate"))),
            Row(label="Obiectiv specific", value=_text(record.get("specific_objective"))),
            Row(label="Cod de intervenție", value=_text(record.get("intervention_code"))),
        ]

    @rx.var(cache=True)
    def classification(self) -> list[Row]:
        record = self._record()
        if not record:
            return []
        return [
            Row(label="Etichetă", value=_text(record.get("software_label"))),
            Row(label="Scor", value=f"{record.get('software_score') or 0:.2f}"),
            Row(label="Motivul scorului", value=_text(record.get("software_evidence"))),
        ]

    @rx.var(cache=True)
    def provenance(self) -> list[Row]:
        record = self._record()
        if not record:
            return []
        return [
            Row(label="Sursă", value=_text(record.get("source"))),
            Row(label="Set de date", value=_text(record.get("source_dataset"))),
            Row(label="Fișier", value=_text(record.get("source_file"))),
            Row(label="Rând în fișier", value=_text(record.get("source_row"))),
            Row(label="Amprentă SHA-256", value=_text(record.get("source_sha256"))),
            Row(label="Descărcat la", value=_text(record.get("fetched_at"))),
        ]

    @rx.var(cache=True)
    def official_url(self) -> str:
        record = self._record() or {}
        return project_url(str(record.get("source") or ""), record.get("project_code")) or ""

    @rx.var(cache=True)
    def has_official_url(self) -> bool:
        return bool(self.official_url)

    @rx.var(cache=True)
    def search_url(self) -> str:
        record = self._record() or {}
        return kohesio_search_url(record.get("project_title"), record.get("beneficiary_name"))

    @rx.var(cache=True)
    def fiscal_url(self) -> str:
        record = self._record() or {}
        return anaf_url(record.get("beneficiary_cui")) or ""

    @rx.var(cache=True)
    def has_fiscal_url(self) -> bool:
        return bool(self.fiscal_url)

    @rx.var(cache=True)
    def file_url(self) -> str:
        record = self._record() or {}
        return str(record.get("source_url") or "")


def _text(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return text or "—"


def fact_row(item: Row) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item.label, size="2", color_scheme="gray"), width="16rem"),
        rx.table.cell(rx.text(item.value, size="2")),
    )


def fact_table(title: str, rows: rx.Var[list[Row]]) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(title, weight="bold", size="2"),
            rx.table.root(
                rx.table.body(rx.foreach(rows, fact_row)),
                variant="ghost",
                size="1",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
    )


@rx.page(route="/proiect/[record_id]", title="Proiect — Registru fonduri UE")
def project_page() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.link("‹ Înapoi la registru", href="/", size="2", color_scheme="gray"),
            rx.cond(
                ProjectState.found,
                rx.vstack(
                    rx.heading(ProjectState.title, size="6"),
                    rx.text(ProjectState.beneficiary, size="3", color_scheme="gray"),
                    rx.cond(
                        ProjectState.summary != "",
                        rx.card(rx.text(ProjectState.summary, size="2"), width="100%"),
                        rx.fragment(),
                    ),
                    rx.hstack(
                        rx.cond(
                            ProjectState.has_official_url,
                            rx.link(
                                rx.button("Fișa oficială Kohesio", size="2"),
                                href=ProjectState.official_url,
                                is_external=True,
                            ),
                            rx.fragment(),
                        ),
                        rx.link(
                            rx.button("Caută în Kohesio", size="2", variant="soft"),
                            href=ProjectState.search_url,
                            is_external=True,
                        ),
                        rx.cond(
                            ProjectState.has_fiscal_url,
                            rx.link(
                                rx.button("Date fiscale beneficiar", size="2", variant="soft"),
                                href=ProjectState.fiscal_url,
                                is_external=True,
                            ),
                            rx.fragment(),
                        ),
                        rx.link(
                            rx.button("Fișierul-sursă (XLSX)", size="2", variant="soft"),
                            href=ProjectState.file_url,
                            is_external=True,
                        ),
                        spacing="2",
                        wrap="wrap",
                    ),
                    rx.text(
                        "Pentru listele naționale 2014-2020 nu există o pagină publică per "
                        "proiect: autoritățile publică doar fișiere Excel. Căutarea Kohesio "
                        "este o încercare de a găsi proiectul, nu un link garantat.",
                        size="1",
                        color_scheme="gray",
                    ),
                    fact_table("Date", ProjectState.facts),
                    fact_table("Clasificare software", ProjectState.classification),
                    fact_table("Proveniență", ProjectState.provenance),
                    spacing="4",
                    width="100%",
                    align="start",
                ),
                rx.card(
                    rx.text("Proiectul nu există în registru.", size="2"),
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
            padding_y="2rem",
        ),
        size="3",
        max_width="1100px",
    )
