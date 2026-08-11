"""Schema canonică a registrului.

Câmpurile de bază nu sunt inventate: sunt cele impuse de articolul 49 alineatul (3)
din Regulamentul (UE) 2021/1060, pe care fiecare Autoritate de Management este
obligată să le publice. Restul sunt câmpuri de proveniență și câmpuri derivate.

https://eur-lex.europa.eu/eli/reg/2021/1060/oj?locale=ro
"""

from __future__ import annotations

import polars as pl
from polars.datatypes import DataTypeClass

#: Tipurile Polars sunt clase, nu instanțe.
PolarsType = DataTypeClass | pl.DataType

#: Câmpurile cerute de art. 49 alin. (3), în ordinea din regulament.
ART49_FIELDS: dict[str, PolarsType] = {
    "beneficiary_name": pl.Utf8,  # denumirea beneficiarului
    "beneficiary_cui": pl.Utf8,  # cod de identificare fiscală (nu e cerut, dar e esențial)
    "beneficiary_type": pl.Utf8,
    "project_code": pl.Utf8,  # cod SMIS / MySMIS
    "project_title": pl.Utf8,  # denumirea operațiunii
    "project_summary": pl.Utf8,  # scopul operațiunii
    "start_date": pl.Date,  # data de început
    "end_date": pl.Date,  # data de sfârșit
    "total_eligible_amount": pl.Float64,  # cheltuiala eligibilă totală
    "total_project_amount": pl.Float64,  # valoarea totală, eligibil plus neeligibil
    "eu_amount": pl.Float64,  # contribuția Uniunii, așa cum a publicat-o autoritatea
    "payments_amount": pl.Float64,  # plăți efectuate către beneficiar
    "currency": pl.Utf8,
    "cofinancing_rate": pl.Float64,  # rata de cofinanțare
    "fund": pl.Utf8,  # FEDR, FSE+, FC, FTJ, FEADR ...
    "specific_objective": pl.Utf8,  # obiectivul specific
    "intervention_code": pl.Utf8,  # codul tipului de intervenție
    "country": pl.Utf8,
    "region": pl.Utf8,  # NUTS 2
    "county": pl.Utf8,  # județ
    "locality": pl.Utf8,
    "latitude": pl.Float64,
    "longitude": pl.Float64,
}

#: Din ce program și din ce perioadă vine rândul.
CONTEXT_FIELDS: dict[str, PolarsType] = {
    "program": pl.Utf8,  # POC, POIM, POCU, PCIDIF ...
    "programming_period": pl.Utf8,  # "2014-2020" | "2021-2027"
    "project_status": pl.Utf8,
}

#: Proveniența. Fără ea, registrul nu poate fi nici contestat, nici apărat.
PROVENANCE_FIELDS: dict[str, PolarsType] = {
    "source": pl.Utf8,  # id-ul adaptorului, ex. "datagovro"
    "source_dataset": pl.Utf8,
    "source_url": pl.Utf8,  # de unde s-a descărcat fișierul
    "source_file": pl.Utf8,  # calea locală relativă
    "source_sha256": pl.Utf8,  # amprenta fișierului descărcat
    "source_row": pl.Int64,  # rândul din fișierul original, de la 0
    "fetched_at": pl.Utf8,  # ISO 8601, UTC
}

#: Câmpuri calculate de pipeline.
DERIVED_FIELDS: dict[str, PolarsType] = {
    # `county` și `region` sunt text liber în fișierele oficiale; acestea sunt
    # variantele parsate pe lista închisă din `registru.geo`.
    # Contribuția UE calculată din rata de cofinanțare, pentru rândurile unde
    # autoritatea nu a publicat suma. Stă separat de `eu_amount` dinadins: una
    # este publicată, cealaltă este dedusă, iar registrul nu are voie să le
    # amestece.
    "eu_amount_derived": pl.Float64,
    "eu_amount_source": pl.Utf8,  # "publicat" | "calculat" | null
    "status": pl.Utf8,  # `project_status` adus la lista din `registru.status`
    "counties": pl.List(pl.Utf8),
    "regions": pl.List(pl.Utf8),
    "software_score": pl.Float64,
    "software_label": pl.Utf8,  # produs | digitalizare | infrastructura | cdi | necunoscut
    "software_evidence": pl.Utf8,  # de ce a primit scorul
    "is_software": pl.Boolean,
    "record_id": pl.Utf8,  # amprentă stabilă peste (sursă, fișier, rând)
}

REGISTRY_SCHEMA: dict[str, PolarsType] = {
    **{"record_id": DERIVED_FIELDS["record_id"]},
    **CONTEXT_FIELDS,
    **ART49_FIELDS,
    **{k: v for k, v in DERIVED_FIELDS.items() if k != "record_id"},
    **PROVENANCE_FIELDS,
}

REGISTRY_COLUMNS: list[str] = list(REGISTRY_SCHEMA)

#: Apelurile de finanțare sunt altă entitate decât proiectele: un apel este o
#: oportunitate deschisă, un proiect este un contract semnat. Nu se amestecă.
CALLS_SCHEMA: dict[str, PolarsType] = {
    "call_id": pl.Utf8,
    "title": pl.Utf8,
    "url": pl.Utf8,  # pagina apelului
    "external_url": pl.Utf8,  # linkul original, când apelul e al Comisiei
    "programs": pl.List(pl.Utf8),
    "specific_objective": pl.Utf8,
    "call_type": pl.Utf8,
    "call_types": pl.List(pl.Utf8),
    "status": pl.Utf8,  # Activ | Urmează | Închis | Necunoscut
    "opens_at": pl.Date,
    "closes_at": pl.Date,
    "continuous": pl.Boolean,  # depunere continuă, fără termen limită
    "budget_amount": pl.Float64,
    "budget_currency": pl.Utf8,
    "beneficiaries": pl.List(pl.Utf8),
    "domains": pl.List(pl.Utf8),
    "geo_areas": pl.List(pl.Utf8),
    "documents": pl.List(pl.Utf8),
    "software_score": pl.Float64,
    "software_label": pl.Utf8,
    "software_evidence": pl.Utf8,
    "is_software": pl.Boolean,
    "published_at": pl.Utf8,
    "modified_at": pl.Utf8,
    "source": pl.Utf8,
    "source_url": pl.Utf8,
    "fetched_at": pl.Utf8,
}

CALLS_COLUMNS: list[str] = list(CALLS_SCHEMA)


def empty_calls() -> pl.DataFrame:
    return pl.DataFrame(schema=CALLS_SCHEMA)


def conform_calls(df: pl.DataFrame) -> pl.DataFrame:
    return _conform(df, CALLS_SCHEMA)


def empty_frame() -> pl.DataFrame:
    """Un cadru gol cu schema completă, ca punct de plecare pentru concatenări."""
    return pl.DataFrame(schema=REGISTRY_SCHEMA)


def conform(df: pl.DataFrame) -> pl.DataFrame:
    """Adaugă coloanele lipsă ca null și pune coloanele în ordinea canonică.

    Un adaptor produce doar ce găsește în fișierul lui. Aici se aliniază.
    """
    return _conform(df, REGISTRY_SCHEMA)


def _conform(df: pl.DataFrame, schema: dict[str, PolarsType]) -> pl.DataFrame:
    exprs = []
    for name, dtype in schema.items():
        if name in df.columns:
            exprs.append(pl.col(name).cast(dtype, strict=False).alias(name))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(name))
    return df.select(exprs)
