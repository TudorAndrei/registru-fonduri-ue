"""Interfața de linie de comandă.

registru fetch datagovro --limit 6
registru extract
registru build
registru stats
registru query "SELECT ... FROM registru"
registru export software.csv --software
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import duckdb
import polars as pl
import typer
from rich.console import Console
from rich.table import Table

from registru.config import CALLS_PARQUET, REGISTRY_DUCKDB, REGISTRY_PARQUET, ensure_dirs
from registru.pipeline.build import build as build_registry
from registru.pipeline.build import build_calls as build_calls_registry
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
    table = Table("id", "produce", "sursă")
    for source_id in sorted(SOURCES):
        adapter = get_source(source_id)
        kind = "apeluri" if getattr(adapter, "kind", "project") == "call" else "proiecte"
        table.add_row(source_id, kind, adapter.name)
    console.print(table)


@app.command()
def calls(
    active: Annotated[bool, typer.Option(help="doar apelurile deschise acum")] = True,
    software: Annotated[bool, typer.Option(help="doar apelurile clasificate ca software")] = False,
) -> None:
    """Apelurile de finanțare din registru."""
    if not CALLS_PARQUET.exists():
        raise typer.BadParameter("nu există apeluri; rulează `registru fetch oportunitati`")
    frame = pl.read_parquet(CALLS_PARQUET)
    if active:
        frame = frame.filter(pl.col("status") == "Activ")
    if software and "is_software" in frame.columns:
        frame = frame.filter(pl.col("is_software"))
    table = Table("închide", "buget", "apel")
    for row in frame.sort("closes_at", nulls_last=True).head(40).to_dicts():
        amount = row.get("budget_amount")
        budget = f"{amount:,.0f} {row.get('budget_currency') or ''}" if amount else "—"
        table.add_row(str(row.get("closes_at") or "—"), budget, str(row.get("title"))[:70])
    console.print(table)
    console.print(f"{frame.height:,} apeluri")


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
        write_interim(source_id, frame, getattr(adapter, "kind", "project"))
        console.print(f"  {frame.height:,} rânduri")


@app.command()
def build(
    source: Annotated[str | None, typer.Option(help="doar o sursă")] = None,
) -> None:
    """Deduplică, clasifică și scrie registrul (Parquet + DuckDB)."""
    frame = build_registry([source] if source else None)
    console.print(f"[green]{frame.height:,}[/green] proiecte -> {REGISTRY_PARQUET}")
    if "is_software" in frame.columns:
        software = int(frame["is_software"].sum())
        console.print(f"din care software: [green]{software:,}[/green]")

    calls = build_calls_registry()
    if calls.height:
        active = int((calls["status"] == "Activ").sum())
        console.print(
            f"[green]{calls.height:,}[/green] apeluri -> {CALLS_PARQUET} ({active:,} active)"
        )


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
def schedule(
    cron: Annotated[str | None, typer.Option(help="expresie cron; implicit lunar, ziua 1")] = None,
    once: Annotated[bool, typer.Option(help="rulează o singură dată și ieși")] = False,
    limit: Annotated[int | None, typer.Option(help="limită per sursă")] = None,
) -> None:
    """Rulează pipeline-ul periodic și ține jurnalul rulărilor."""
    from registru.schedule import run_once, serve

    if once:
        report = run_once(limit=limit)
        console.print(report.summary())
        for error in report.errors:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(0 if report.ok else 1)
    serve(cron, limit=limit)


@app.command()
def publica(
    colecteaza: Annotated[bool, typer.Option(help="colectează întâi de la surse")] = True,
) -> None:
    """Colectează și publică registrele în depozit — rutina lunară.

    Se rulează de pe o mașină de pe care sursele răspund. Serverul nu poate:
    `oportunitati-ue.gov.ro` și `mfe.gov.ro` lasă conexiunea să expire de pe
    adrese de centru de date, iar Kohesio răspunde 403. El ia rezultatul cu
    `registru sync`.
    """
    import subprocess  # noqa: S404 — se rulează git, cu argumente fixe

    if colecteaza:
        from registru.schedule import run_once

        raport = run_once()
        console.print(raport.summary())
        for eroare in raport.errors:
            console.print(f"[red]{eroare}[/red]")
        if not raport.ok:
            console.print("[red]colectarea a avut erori; nu public[/red]")
            raise typer.Exit(1)

    fisiere = [
        str(REGISTRY_PARQUET),
        str(CALLS_PARQUET),
        str(REGISTRY_PARQUET.parent.parent / "runs" / "latest.json"),
    ]
    radacina = Path(__file__).resolve().parent.parent

    def git(*argumente: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 — argumente fixe, fără shell
            ["git", *argumente],  # noqa: S607
            cwd=radacina,
            capture_output=True,
            text=True,
            check=False,
        )

    # `-f` fiindcă `data/` este ignorat: fișierele brute nu au ce căuta în git,
    # dar registrele construite da.
    git("add", "-f", *fisiere)
    if not git("diff", "--cached", "--quiet").returncode:
        console.print("registrele nu s-au schimbat, nu am ce publica")
        return

    data = datetime.now(UTC).date().isoformat()
    commit = git("commit", "-m", f"registru: colectare {data}")
    if commit.returncode:
        console.print(f"[red]{commit.stderr.strip()}[/red]")
        raise typer.Exit(1)
    push = git("push")
    if push.returncode:
        console.print(f"[red]{push.stderr.strip()}[/red]")
        raise typer.Exit(1)
    console.print("[green]publicat[/green] — serverul le ia la următoarea sincronizare")


@app.command()
def sync() -> None:
    """Aduce registrele publicate, în loc să colecteze.

    Pentru mașinile de pe care sursele nu răspund. Colectarea rulează unde
    merge, iar aici ajunge doar rezultatul.
    """
    from registru.sync import SURSA
    from registru.sync import sync as adu

    console.print(f"sursa: {SURSA}")
    table = Table("fișier", "stare")
    for nume, stare in adu():
        table.add_row(nume, stare)
    console.print(table)


@app.command()
def runs(limit: Annotated[int, typer.Option(help="câte rulări să arate")] = 10) -> None:
    """Jurnalul rulărilor."""
    from registru.schedule import history

    entries = history(limit)
    if not entries:
        console.print("nicio rulare înregistrată")
        raise typer.Exit(0)
    table = Table("început", "durată", "proiecte", "apeluri", "stare")
    for entry in entries:
        state = "[green]ok[/green]" if entry.get("ok") else "[red]erori[/red]"
        table.add_row(
            str(entry.get("started_at"))[:19],
            f"{entry.get('seconds', 0):.0f}s",
            f"{entry.get('projects', 0):,} (+{entry.get('projects_new', 0):,})",
            f"{entry.get('calls', 0):,} (+{entry.get('calls_new', 0):,})",
            state,
        )
    console.print(table)


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
