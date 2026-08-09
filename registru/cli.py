"""Interfața de linie de comandă.

registru fetch datagovro --limit 6
registru extract
registru build
registru stats
registru query "SELECT ... FROM registru"
registru export software.csv --software
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import duckdb
import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from registru.config import REGISTRY_DUCKDB, REGISTRY_PARQUET, ensure_dirs
from registru.pipeline.build import build as build_registry
from registru.pipeline.build import write_interim
from registru.sources import SOURCES, get_source

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Registru deschis al proiectelor cu finanțare europeană în România.",
)
console = Console()


@app.command()
def sources() -> None:
    """Arată adaptoarele disponibile."""
    table = Table("id", "sursă")
    for source_id in sorted(SOURCES):
        table.add_row(source_id, get_source(source_id).name)
    console.print(table)


@app.command()
def fetch(
    source: Annotated[str, typer.Argument(help="id-ul sursei, sau 'all'")] = "all",
    limit: Annotated[
        int | None,
        typer.Option(help="câte fișiere sau pagini să aducă (implicit: tot / 10 pagini)"),
    ] = None,
) -> None:
    """Descarcă fișierele brute. Nu rescrie niciodată ce este deja pe disc."""
    ensure_dirs()
    ids = sorted(SOURCES) if source == "all" else [source]
    for source_id in ids:
        adapter = get_source(source_id)
        console.print(f"[bold]{adapter.name}[/bold]")
        files = adapter.fetch(limit=limit)
        total = sum(item.bytes for item in files)
        console.print(f"  {len(files)} fișiere, {total / 1e6:.1f} MB")


@app.command()
def extract(
    source: Annotated[str, typer.Argument(help="id-ul sursei, sau 'all'")] = "all",
) -> None:
    """Citește fișierele descărcate și scrie rânduri pe schema canonică."""
    ensure_dirs()
    ids = sorted(SOURCES) if source == "all" else [source]
    for source_id in ids:
        adapter = get_source(source_id)
        console.print(f"[bold]{adapter.name}[/bold]")
        frame = adapter.extract()
        write_interim(source_id, frame)
        console.print(f"  {frame.height:,} rânduri")


@app.command()
def build(
    source: Annotated[str | None, typer.Option(help="doar o sursă")] = None,
) -> None:
    """Deduplică, clasifică și scrie registrul (Parquet + DuckDB)."""
    frame = build_registry([source] if source else None)
    console.print(f"[green]{frame.height:,}[/green] rânduri -> {REGISTRY_PARQUET}")
    if "is_software" in frame.columns:
        software = int(frame["is_software"].sum())
        console.print(f"din care software: [green]{software:,}[/green]")


@app.command()
def all(  # noqa: A001 — numele comenzii contează mai mult decât umbrirea built-in-ului
    limit: Annotated[int | None, typer.Option(help="limită per sursă")] = None,
) -> None:
    """fetch + extract + build, în ordine."""
    fetch("all", limit)
    extract("all")
    build(None)


@app.command()
def stats() -> None:
    """Sinteza registrului."""
    frame = _load()
    table = Table("indicator", "valoare")
    table.add_row("rânduri", f"{frame.height:,}")
    table.add_row("beneficiari distincți", f"{frame['beneficiary_key'].n_unique():,}")
    table.add_row("programe", ", ".join(sorted(_non_null(frame, "program"))[:12]) or "—")
    if "is_software" in frame.columns:
        table.add_row("proiecte software", f"{int(frame['is_software'].sum()):,}")
    total = frame["total_eligible_amount"].sum()
    if total:
        table.add_row("eligibil total", f"{total:,.0f}")
    console.print(table)

    if "software_label" in frame.columns:
        breakdown = (
            frame.group_by("software_label").agg(pl.len().alias("n")).sort("n", descending=True)
        )
        labels = Table("etichetă", "rânduri")
        for row in breakdown.iter_rows():
            labels.add_row(str(row[0]), f"{row[1]:,}")
        console.print(labels)


@app.command()
def query(sql: Annotated[str, typer.Argument(help="SQL peste tabelul `registru`")]) -> None:
    """Rulează SQL peste registru, cu DuckDB."""
    if not REGISTRY_DUCKDB.exists():
        raise typer.BadParameter("registrul nu există încă; rulează `registru build`")
    connection = duckdb.connect(str(REGISTRY_DUCKDB), read_only=True)
    try:
        result = connection.execute(sql).pl()
    finally:
        connection.close()
    console.print(result)


@app.command()
def export(
    target: Annotated[Path, typer.Argument(help="fișier .csv sau .parquet")],
    software: Annotated[bool, typer.Option(help="doar proiectele clasificate ca software")] = False,
) -> None:
    """Exportă registrul integral. Descărcarea completă rămâne gratuită și fără cont."""
    frame = _load()
    if software and "is_software" in frame.columns:
        frame = frame.filter(pl.col("is_software"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix == ".parquet":
        frame.write_parquet(target)
    else:
        frame.write_csv(target)
    console.print(f"{frame.height:,} rânduri -> {target}")


@app.command()
def dashboard() -> None:
    """Pornește tabloul de bord Reflex."""
    import subprocess  # noqa: S404 — pornim Reflex din același interpretor
    import sys

    root = Path(__file__).resolve().parent.parent
    raise SystemExit(subprocess.call([sys.executable, "-m", "reflex", "run"], cwd=root))  # noqa: S603


def _load() -> pl.DataFrame:
    if not REGISTRY_PARQUET.exists():
        raise typer.BadParameter("registrul nu există încă; rulează `registru build`")
    return pl.read_parquet(REGISTRY_PARQUET)


def _non_null(frame: pl.DataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        return []
    return [value for value in frame[column].unique().to_list() if value]


if __name__ == "__main__":
    app()
