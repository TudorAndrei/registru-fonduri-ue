"""Rulare periodică a pipeline-ului.

Registrul nu are sens ca fotografie: sursele publică trimestrial, apelurile se
schimbă săptămânal. Modulul acesta rulează `fetch -> extract -> build` pe un
program și ține un jurnal al rulărilor, ca să se vadă ce s-a schimbat de la una
la alta.

Jurnalul este partea importantă. O rulare care nu aduce nimic nou și una care
eșuează arată la fel din afară, dacă nimeni nu notează diferența.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
from croniter import croniter

from registru.config import CALLS_PARQUET, DATA_DIR, REGISTRY_PARQUET, ensure_dirs
from registru.pipeline.build import build, build_calls, write_interim
from registru.sources import SOURCES, get_source

RUNS_DIR = DATA_DIR / "runs"
LATEST = RUNS_DIR / "latest.json"

#: Ora 03:00, în ziua de 1 a fiecărei luni. Sursele naționale se actualizează
#: trimestrial, deci mai des nu are ce să aducă.
DEFAULT_CRON = "0 3 1 * *"

#: Cât se așteaptă înainte de a relua o rulare incompletă. Fără răgazul acesta,
#: o sursă indisponibilă ar face ca fiecare repornire de container să reia toată
#: colectarea — zeci de minute, de fiecare dată, pentru același eșec.
COOLDOWN_ORE = float(os.environ.get("REGISTRU_RAGAZ_ORE", "6"))


@dataclass
class SourceResult:
    source: str
    files: int = 0
    bytes: int = 0
    rows: int = 0
    error: str | None = None


@dataclass
class RunReport:
    """Ce a făcut o rulare, în termeni pe care îi poate citi un om."""

    started_at: str
    finished_at: str = ""
    seconds: float = 0.0
    ok: bool = True
    sources: list[SourceResult] = field(default_factory=list)
    projects: int = 0
    projects_new: int = 0
    calls: int = 0
    calls_new: int = 0
    calls_active: int = 0
    software: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        state = "ok" if self.ok else "cu erori"
        return (
            f"{self.started_at} — {state} în {self.seconds:.0f}s: "
            f"{self.projects:,} proiecte (+{self.projects_new:,}), "
            f"{self.calls:,} apeluri (+{self.calls_new:,}, {self.calls_active:,} active)"
        )


def _ids(path: Path, column: str) -> set[str]:
    """Identitățile din registrul curent, ca să se poată număra ce e nou."""
    if not path.exists():
        return set()
    try:
        return set(pl.read_parquet(path, columns=[column])[column].drop_nulls().to_list())
    except Exception:  # noqa: BLE001 — un registru stricat nu trebuie să oprească rularea
        return set()


def run_once(limit: int | None = None, only: list[str] | None = None) -> RunReport:
    """O rulare completă. Nu aruncă: o sursă căzută nu trebuie să oprească restul."""
    ensure_dirs()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = RunReport(started_at=datetime.now(UTC).isoformat(timespec="seconds"))

    before_projects = _ids(REGISTRY_PARQUET, "record_id")
    before_calls = _ids(CALLS_PARQUET, "call_id")

    for source_id in only or sorted(SOURCES):
        result = SourceResult(source=source_id)
        try:
            adapter = get_source(source_id)
            files = adapter.fetch(limit=limit)
            result.files = len(files)
            result.bytes = sum(item.bytes for item in files)
            frame = adapter.extract()
            result.rows = frame.height
            write_interim(source_id, frame, getattr(adapter, "kind", "project"))
        except Exception as error:  # noqa: BLE001 — se notează și se merge mai departe
            result.error = f"{type(error).__name__}: {error}"
            report.errors.append(f"{source_id}: {result.error}")
            # O sursă marcată opțională nu strică rularea. Kohesio răspunde 403
            # cererilor dintr-un centru de date; sunt 15 rânduri, iar a declara
            # rularea eșuată pentru ele ar însemna reluare la fiecare pornire.
            if not getattr(get_source(source_id), "optional", False):
                report.ok = False
            print(f"[schedule] {source_id}: {result.error.splitlines()[0]}", flush=True)
        report.sources.append(result)

    try:
        projects = build()
        report.projects = projects.height
        if "is_software" in projects.columns:
            report.software = int(projects["is_software"].sum())
        calls = build_calls()
        report.calls = calls.height
        if calls.height and "status" in calls.columns:
            report.calls_active = int((calls["status"] == "Activ").sum())
    except Exception as error:  # noqa: BLE001
        report.errors.append(f"build: {type(error).__name__}: {error}")
        report.ok = False
        traceback.print_exc()

    report.projects_new = len(_ids(REGISTRY_PARQUET, "record_id") - before_projects)
    report.calls_new = len(_ids(CALLS_PARQUET, "call_id") - before_calls)
    report.seconds = time.monotonic() - started
    report.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    _write_report(report)
    return report


def _write_report(report: RunReport) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("-", "")
    payload = json.dumps(asdict(report), ensure_ascii=False, indent=2)
    (RUNS_DIR / f"{stamp}.json").write_text(payload, "utf-8")
    LATEST.write_text(payload, "utf-8")


def read_latest() -> dict | None:
    if not LATEST.exists():
        return None
    try:
        return json.loads(LATEST.read_text("utf-8"))
    except json.JSONDecodeError:
        return None


def history(limit: int = 20) -> list[dict]:
    runs = sorted(RUNS_DIR.glob("2*.json"), reverse=True)[:limit]
    out = []
    for path in runs:
        try:
            out.append(json.loads(path.read_text("utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def cron_expression() -> str:
    return os.environ.get("REGISTRU_CRON", DEFAULT_CRON).strip() or DEFAULT_CRON


def next_run(expression: str | None = None, now: datetime | None = None) -> datetime:
    expression = expression or cron_expression()
    return croniter(expression, now or datetime.now(UTC)).get_next(datetime)


def de_ce_sa_ruleze_acum() -> str | None:
    """Motivul pentru care merită o rulare la pornire, sau None dacă nu merită.

    Nu este de ajuns să existe registrul. O rulare poate să reușească pentru o
    sursă și să cadă pentru alta — s-a întâmplat: proiectele s-au construit,
    apelurile au rămas zero pentru că sursa lor nu era accesibilă. Registrul
    exista, deci o repornire nu ar fi reîncercat nimic, iar golul ar fi rămas
    până la următoarea rulare programată, adică o lună.
    """
    if not REGISTRY_PARQUET.exists():
        return "registrul lipsește"
    if not CALLS_PARQUET.exists():
        return "lipsesc apelurile"
    ultima = read_latest()
    if ultima is None:
        return "nu există jurnal de rulare"

    inceput = ultima.get("started_at")
    if inceput:
        try:
            varsta = (datetime.now(UTC) - datetime.fromisoformat(inceput)).total_seconds() / 3600
        except ValueError:
            varsta = COOLDOWN_ORE + 1
        if varsta < COOLDOWN_ORE:
            return None

    if not ultima.get("ok"):
        return f"ultima rulare a avut erori: {'; '.join(ultima.get('errors') or [])[:200]}"
    if not ultima.get("calls"):
        return "ultima rulare nu a adus niciun apel"
    return None


def serve(
    expression: str | None = None,
    run_at_start: bool = True,
    limit: int | None = None,
) -> None:
    """Bucla de programare. Rulează până este oprită.

    Rularea la pornire există pentru server: un container proaspăt nu are
    registru, iar a aștepta până la 1 ale lunii ca să afli dacă merge nu este o
    strategie de desfășurare. Se reia și după o rulare cu erori, altfel o
    corectură desfășurată azi nu s-ar vedea decât luna viitoare.
    """
    expression = expression or cron_expression()
    print(f"[schedule] program: {expression}", flush=True)

    motiv = de_ce_sa_ruleze_acum() if run_at_start else None
    reusita = True
    if motiv:
        print(f"[schedule] rulez acum — {motiv}", flush=True)
        raport = run_once(limit=limit)
        reusita = raport.ok
        print(f"[schedule] {raport.summary()}", flush=True)

    while True:
        urmatoarea = next_run(expression)
        # După o rulare căzută nu se așteaptă până la următorul termen din
        # program: sursa poate fi indisponibilă o oră, iar programul e lunar.
        # Se reîncearcă după răgaz, dacă acesta cade mai devreme.
        if not reusita:
            reluare = datetime.now(UTC) + timedelta(hours=COOLDOWN_ORE)
            if reluare < urmatoarea:
                urmatoarea = reluare
                print(
                    f"[schedule] ultima rulare a avut erori, reîncerc peste {COOLDOWN_ORE:.0f}h",
                    flush=True,
                )

        seconds = max(1.0, (urmatoarea - datetime.now(UTC)).total_seconds())
        print(
            f"[schedule] următoarea rulare: {urmatoarea.isoformat()} (peste {seconds / 3600:.1f}h)",
            flush=True,
        )
        time.sleep(seconds)
        try:
            raport = run_once(limit=limit)
            reusita = raport.ok
            print(f"[schedule] {raport.summary()}", flush=True)
        except Exception:  # noqa: BLE001 — bucla nu moare din cauza unei rulări
            reusita = False
            traceback.print_exc()
