"""Căile de pe disc. Un singur loc care știe unde stau datele."""

from __future__ import annotations

import os
from pathlib import Path

# Rădăcina depozitului, sau ce spune REGISTRU_DATA_DIR.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("REGISTRU_DATA_DIR", REPO_ROOT / "data")).resolve()

# Fișierele descărcate, exact cum au venit. Nu se modifică niciodată.
RAW_DIR = DATA_DIR / "raw"
# Rânduri extrase, o schemă per sursă, încă needuplicate.
INTERIM_DIR = DATA_DIR / "interim"
# Registrul propriu-zis.
REGISTRY_DIR = DATA_DIR / "registry"

REGISTRY_PARQUET = REGISTRY_DIR / "registru.parquet"
REGISTRY_DUCKDB = REGISTRY_DIR / "registru.duckdb"

USER_AGENT = "registru-fonduri-ue/0.1 (+https://github.com/TudorAndrei/registru-fonduri-ue)"
HTTP_TIMEOUT = 120.0


def ensure_dirs() -> None:
    for path in (RAW_DIR, INTERIM_DIR, REGISTRY_DIR):
        path.mkdir(parents=True, exist_ok=True)
