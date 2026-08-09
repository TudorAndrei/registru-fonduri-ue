"""Construiește registrul din rândurile extrase.

Pași: identitate stabilă -> deduplicare -> clasificare -> scriere Parquet și DuckDB.
"""

from __future__ import annotations

import hashlib

import duckdb
import polars as pl

from registru.config import INTERIM_DIR, REGISTRY_DUCKDB, REGISTRY_PARQUET, ensure_dirs
from registru.pipeline.classify import classify
from registru.schema import REGISTRY_COLUMNS, conform, empty_frame
from registru.text import normalize_company


def interim_path(source_id: str):
    return INTERIM_DIR / f"{source_id}.parquet"


def write_interim(source_id: str, frame: pl.DataFrame) -> None:
    ensure_dirs()
    conform(frame).write_parquet(interim_path(source_id))


def read_interim(source_ids: list[str] | None = None) -> pl.DataFrame:
    ensure_dirs()
    paths = sorted(INTERIM_DIR.glob("*.parquet"))
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


def deduplicate(frame: pl.DataFrame) -> pl.DataFrame:
    """Același proiect apare în publicări succesive ale aceleiași liste.

    Se păstrează rândul cel mai recent descărcat pentru fiecare
    (program, cod proiect, beneficiar).
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
    return (
        keyed.sort("fetched_at", descending=True)
        .unique(subset=["program", "_dedup_code", "beneficiary_key"], keep="first")
        .drop("_dedup_code")
    )


def build(source_ids: list[str] | None = None) -> pl.DataFrame:
    ensure_dirs()
    frame = read_interim(source_ids)
    frame = add_identity(frame)
    frame = deduplicate(frame)
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
