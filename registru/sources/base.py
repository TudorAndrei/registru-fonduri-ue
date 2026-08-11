"""Contractul comun al adaptoarelor de sursă.

Un adaptor face două lucruri și nimic mai mult:

1. `fetch()` — aduce fișierele brute pe disc și scrie un manifest cu proveniența.
2. `extract()` — citește fișierele descărcate și produce rânduri pe schema canonică.

Toată urâțenia unei surse (coloane care se schimbă, arhive, PDF-uri) rămâne în
adaptorul ei. Restul pipeline-ului vede o singură schemă.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import polars as pl

from registru.config import HTTP_TIMEOUT, RAW_DIR, USER_AGENT


@dataclass(slots=True)
class FetchedFile:
    """Un fișier descărcat, plus tot ce trebuie ca să-l poți justifica mai târziu."""

    source: str
    dataset: str
    url: str
    path: str  # relativ la RAW_DIR
    sha256: str
    bytes: int
    fetched_at: str
    meta: dict = field(default_factory=dict)


class Source(Protocol):
    id: str
    name: str
    #: "project" pentru contracte semnate, "call" pentru apeluri deschise.
    kind: str

    def fetch(self, *, limit: int | None = None) -> list[FetchedFile]: ...

    def extract(self) -> pl.DataFrame: ...


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


#: Mai multe site-uri publice românești au adrese IPv6 (`mfe.gov.ro`,
#: `oportunitati-ue.gov.ro`), iar un container fără rută IPv6 primește
#: `[Errno 101] Network is unreachable` înainte să apuce să încerce IPv4.
#: Legarea pe o adresă locală IPv4 rezolvă din prima cerere.
FORTEAZA_IPV4 = os.environ.get("REGISTRU_IPV4", "1") not in {"0", "", "false"}


def transport() -> httpx.HTTPTransport:
    return httpx.HTTPTransport(
        local_address="0.0.0.0" if FORTEAZA_IPV4 else None,  # noqa: S104 — legare, nu ascultare
        retries=2,
    )


def http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        transport=transport(),
    )


def download(client: httpx.Client, url: str, target: Path) -> bool:
    """Descarcă în `target`. Întoarce False dacă fișierul era deja acolo.

    Nu se rescrie nimic: un fișier descărcat este dovadă, nu cache.
    """
    if target.exists() and target.stat().st_size > 0:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 16):
                handle.write(chunk)
    tmp.rename(target)
    return True


def manifest_path(source_id: str) -> Path:
    return RAW_DIR / source_id / "manifest.json"


def write_manifest(source_id: str, files: list[FetchedFile]) -> Path:
    """Manifestul este cumulativ: descărcările vechi rămân înregistrate."""
    path = manifest_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    known: dict[str, dict] = {}
    if path.exists():
        known = {item["path"]: item for item in json.loads(path.read_text("utf-8"))}
    for item in files:
        known[item.path] = asdict(item)
    payload = sorted(known.values(), key=lambda item: item["path"])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return path


def read_manifest(source_id: str) -> list[FetchedFile]:
    path = manifest_path(source_id)
    if not path.exists():
        return []
    return [FetchedFile(**item) for item in json.loads(path.read_text("utf-8"))]
