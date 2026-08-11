"""Normalizări care nu aparțin unui singur adaptor.

Textul geografic vine la fel de dezordonat din orice sursă, deci se curăță o
singură dată, aici, după ce toate sursele au fost aduse la schema comună.
"""

from __future__ import annotations

import polars as pl

from registru.geo import parse_counties, parse_regions, regions_for
from registru.status import normalize_status


def normalize_status_column(frame: pl.DataFrame) -> pl.DataFrame:
    """Adaugă `status`, coloana brută `project_status` rămâne neatinsă."""
    if frame.height == 0 or "project_status" not in frame.columns:
        return frame
    values = [normalize_status(value) for value in frame["project_status"].to_list()]
    return frame.with_columns(pl.Series("status", values, dtype=pl.Utf8))


def normalize_geo(frame: pl.DataFrame) -> pl.DataFrame:
    """Adaugă `counties` și `regions`, parsate din `county`, `region` și `locality`.

    Coloanele originale rămân neatinse: ele sunt ce a publicat autoritatea, iar
    registrul nu rescrie sursa.
    """
    if frame.height == 0:
        return frame

    columns = [column for column in ("county", "region", "locality") if column in frame.columns]
    if not columns:
        return frame

    counties: list[list[str]] = []
    regions: list[list[str]] = []
    for row in frame.select(columns).iter_rows():
        parsed = parse_counties(*row)
        counties.append(parsed)
        # Când rândul numește doar regiunea („Sud-Vest Oltenia”), se citește de acolo.
        regions.append(regions_for(parsed) or parse_regions(*row))

    return frame.with_columns(
        pl.Series("counties", counties, dtype=pl.List(pl.Utf8)),
        pl.Series("regions", regions, dtype=pl.List(pl.Utf8)),
    )


def derive_eu_amount(frame: pl.DataFrame) -> pl.DataFrame:
    """Completează contribuția UE acolo unde autoritatea nu a publicat-o.

    Rata de cofinanțare este publicată în 99% din rânduri, iar suma UE este
    produsul ei cu cheltuiala eligibilă — asta spune regulamentul. Rezultatul
    stă în `eu_amount_derived`, nu în `eu_amount`, iar `eu_amount_source` spune
    de fiecare dată care este care. Cine adună trebuie să știe ce adună.

    Rata vine când ca procent (85), când ca fracție (0,85); se aduce la fracție.
    """
    if frame.height == 0 or "cofinancing_rate" not in frame.columns:
        return frame

    # Rata vine când ca procent (85), când ca fracție (0,85). Peste 100 sau sub
    # zero nu este o rată, ci o coloană citită greșit — sunt 158 de rânduri cu
    # valori până la 8.580. Acelea nu se folosesc.
    bruta = pl.col("cofinancing_rate")
    valida = (bruta > 0) & (bruta <= 100)
    rata = pl.when(~valida).then(None).when(bruta > 1).then(bruta / 100).otherwise(bruta)
    calculat = (pl.col("total_eligible_amount") * rata).round(2)
    # Invariantul care nu poate fi încălcat: contribuția Uniunii este o parte
    # din cheltuiala eligibilă, deci nu o poate depăși. Ce iese mai mare vine
    # dintr-o rată greșită, oricât de plauzibilă ar părea.
    calculat = pl.when(calculat > pl.col("total_eligible_amount")).then(None).otherwise(calculat)

    combinat = pl.coalesce(pl.col("eu_amount"), calculat)
    # Invariantul se aplică și sumelor publicate. O valoare mai mare decât
    # cheltuiala eligibilă nu devine corectă pentru că a tipărit-o autoritatea:
    # înseamnă că acea coloană nu conține ce scrie în capul ei.
    peste = combinat > pl.col("total_eligible_amount")
    combinat = pl.when(peste).then(None).otherwise(combinat)

    return frame.with_columns(
        combinat.alias("eu_amount_derived"),
        pl.when(peste)
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(pl.col("eu_amount").is_not_null())
        .then(pl.lit("publicat"))
        .when(calculat.is_not_null())
        .then(pl.lit("calculat"))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
        .alias("eu_amount_source"),
    )
