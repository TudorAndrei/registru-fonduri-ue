"""Construiește registrul din rândurile extrase.

Pași: identitate stabilă -> deduplicare -> clasificare -> scriere Parquet și DuckDB.
"""

from __future__ import annotations

import hashlib

import duckdb
import polars as pl

from registru.config import (
    CALLS_PARQUET,
    INTERIM_DIR,
    REGISTRY_DUCKDB,
    REGISTRY_PARQUET,
    ensure_dirs,
)
from registru.pipeline.classify import classify, classify_calls
from registru.pipeline.normalize import derive_eu_amount, normalize_geo, normalize_status_column
from registru.schema import (
    CALLS_COLUMNS,
    REGISTRY_COLUMNS,
    conform,
    conform_calls,
    empty_calls,
    empty_frame,
)
from registru.text import normalize_company


def interim_path(source_id: str, kind: str = "project"):
    suffix = "" if kind == "project" else f".{kind}"
    return INTERIM_DIR / f"{source_id}{suffix}.parquet"


def write_interim(source_id: str, frame: pl.DataFrame, kind: str = "project") -> None:
    ensure_dirs()
    shaped = conform(frame) if kind == "project" else conform_calls(frame)
    shaped.write_parquet(interim_path(source_id, kind))


def read_interim(source_ids: list[str] | None = None) -> pl.DataFrame:
    ensure_dirs()
    paths = [path for path in sorted(INTERIM_DIR.glob("*.parquet")) if "." not in path.stem]
    if source_ids:
        wanted = set(source_ids)
        paths = [path for path in paths if path.stem in wanted]
    frames = [pl.read_parquet(path) for path in paths]
    if not frames:
        return empty_frame()
    return pl.concat([conform(frame) for frame in frames], how="vertical_relaxed")


def _record_id(source: str, source_file: str | None, source_row: int | None) -> str:
    raw = f"{source}|{source_file}|{source_row}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324 — identitate, nu securitate


def add_identity(frame: pl.DataFrame) -> pl.DataFrame:
    """Cheie stabilă per rând și cheie de potrivire pentru beneficiar."""
    if frame.height == 0:
        return frame
    ids = [
        _record_id(row["source"], row["source_file"], row["source_row"])
        for row in frame.select("source", "source_file", "source_row").to_dicts()
    ]
    keys = [normalize_company(name) for name in frame["beneficiary_name"].to_list()]
    return frame.with_columns(
        pl.Series("record_id", ids, dtype=pl.Utf8),
        pl.Series("beneficiary_key", keys, dtype=pl.Utf8),
    )


#: Câmpuri pe care o sursă le publică și alta nu. Înainte de deduplicare se
#: completează între ele, altfel rândul care supraviețuiește pierde ce știa
#: celălalt — de exemplu `Fonduri UE`, publicat doar în PDF-urile de pe
#: fonduri-ue.ro, niciodată în fișierele Excel de pe data.gov.ro.
MERGED_FIELDS = (
    "eu_amount",
    "payments_amount",
    "total_project_amount",
    "total_eligible_amount",
    "beneficiary_cui",
    "project_summary",
    "intervention_code",
    "county",
    "region",
)

DEDUP_KEY = ["program", "_dedup_code", "beneficiary_key"]


def deduplicate(frame: pl.DataFrame) -> pl.DataFrame:
    """Același proiect apare în publicări succesive și în surse diferite.

    Rândurile se combină întâi și abia apoi se reduc la unul singur, ca să nu
    se piardă câmpurile pe care doar una dintre surse le publică. Se păstrează
    cea mai recentă publicare pentru fiecare (program, cod proiect, beneficiar).
    """
    if frame.height == 0:
        return frame
    keyed = frame.with_columns(
        pl.coalesce(
            pl.col("project_code"),
            pl.col("project_title"),
            pl.col("record_id"),
        ).alias("_dedup_code")
    )
    fills = [
        pl.coalesce(pl.col(column), pl.col(column).drop_nulls().first().over(DEDUP_KEY)).alias(
            column
        )
        for column in MERGED_FIELDS
        if column in keyed.columns
    ]
    if fills:
        keyed = keyed.with_columns(fills)
    return (
        keyed.sort("fetched_at", descending=True)
        .unique(subset=DEDUP_KEY, keep="first")
        .drop("_dedup_code")
    )


def build(source_ids: list[str] | None = None) -> pl.DataFrame:
    ensure_dirs()
    frame = read_interim(source_ids)
    frame = add_identity(frame)
    frame = deduplicate(frame)
    frame = normalize_geo(frame)
    frame = normalize_status_column(frame)
    frame = derive_eu_amount(frame)
    frame = classify(frame)
    ordered = [*REGISTRY_COLUMNS, "beneficiary_key"]
    frame = frame.select([column for column in ordered if column in frame.columns])
    frame.write_parquet(REGISTRY_PARQUET)
    _write_duckdb()
    return frame


def _write_duckdb() -> None:
    """DuckDB pentru distribuție: un singur fișier, interogabil cu SQL."""
    REGISTRY_DUCKDB.unlink(missing_ok=True)
    connection = duckdb.connect(str(REGISTRY_DUCKDB))
    try:
        connection.execute(
            "CREATE TABLE registru AS SELECT * FROM read_parquet(?)",
            [str(REGISTRY_PARQUET)],
        )
        connection.execute(
            """
            CREATE VIEW software AS
            SELECT * FROM registru WHERE is_software
            """
        )
        connection.execute(
            """
            CREATE VIEW beneficiari AS
            SELECT
                beneficiary_key,
                any_value(beneficiary_name)      AS beneficiary_name,
                any_value(beneficiary_cui)       AS beneficiary_cui,
                count(*)                         AS proiecte,
                sum(total_eligible_amount)       AS eligibil_total,
                sum(eu_amount)                   AS finantare_ue,
                sum(CASE WHEN is_software THEN 1 ELSE 0 END) AS proiecte_software
            FROM registru
            GROUP BY beneficiary_key
            """
        )
    finally:
        connection.close()


def read_interim_calls() -> pl.DataFrame:
    ensure_dirs()
    paths = sorted(INTERIM_DIR.glob("*.call.parquet"))
    frames = [conform_calls(pl.read_parquet(path)) for path in paths]
    if not frames:
        return empty_calls()
    return pl.concat(frames, how="vertical_relaxed")


def build_calls() -> pl.DataFrame:
    """Registrul apelurilor. Tabelă separată, deduplicată pe identitatea sursei."""
    ensure_dirs()
    frame = read_interim_calls()
    if frame.height:
        frame = frame.unique(subset=["source", "call_id"], keep="first")
        frame = classify_calls(frame)
    frame = frame.select([column for column in CALLS_COLUMNS if column in frame.columns])
    frame.write_parquet(CALLS_PARQUET)
    _attach_calls()
    return frame


def _attach_calls() -> None:
    """Apelurile intră în același fișier DuckDB, ca tabelă proprie."""
    if not CALLS_PARQUET.exists() or not REGISTRY_DUCKDB.exists():
        return
    connection = duckdb.connect(str(REGISTRY_DUCKDB))
    try:
        connection.execute("DROP TABLE IF EXISTS apeluri")
        connection.execute(
            "CREATE TABLE apeluri AS SELECT * FROM read_parquet(?)", [str(CALLS_PARQUET)]
        )
        connection.execute(
            "CREATE OR REPLACE VIEW apeluri_active AS SELECT * FROM apeluri WHERE status = 'Activ'"
        )
    finally:
        connection.close()
