"""Normalizări care nu aparțin unui singur adaptor.

Textul geografic vine la fel de dezordonat din orice sursă, deci se curăță o
singură dată, aici, după ce toate sursele au fost aduse la schema comună.
"""

from __future__ import annotations

import polars as pl

from registru.geo import parse_counties, parse_regions, regions_for


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
