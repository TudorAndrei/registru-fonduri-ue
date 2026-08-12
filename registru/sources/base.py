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
import socket
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

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
FORTEAZA_IPV4 = os.environ.get("REGISTRU_IPV4", "1") not in {"0", "", "false"}

_getaddrinfo_original = socket.getaddrinfo


def _numai_ipv4(
    host,
    port,
    family=0,
    type=0,  # noqa: A002 — semnătura trebuie să fie a lui `socket.getaddrinfo`
    proto=0,
    flags=0,
):
    return _getaddrinfo_original(host, port, socket.AF_INET, type, proto, flags)


def forteaza_ipv4() -> None:
    """Face rezolvarea de nume să întoarcă numai adrese IPv4.

    Prima încercare a fost `local_address="0.0.0.0"`, care leagă socket-ul pe
    IPv4 — dar rezolvarea întorcea în continuare adrese IPv6, iar nepotrivirea
    dădea `[Errno -9] Address family for hostname not supported`. Legarea
    trebuie deci făcută la rezolvare, nu la socket.

    Este o modificare la nivel de proces, dar procesul acesta nu face altceva
    decât să descarce fișiere. Are și avantajul că prinde bibliotecile care nu
    lasă transportul la vedere, cum e `wayback`, care merge pe `requests`.
    """
    if FORTEAZA_IPV4 and socket.getaddrinfo is not _numai_ipv4:
        socket.getaddrinfo = _numai_ipv4  # ty: ignore[invalid-assignment]


forteaza_ipv4()


def proxy() -> dict[str, str]:
    """Ieșirea prin care se fac cererile, dacă este configurată una.

    Mai multe site-uri publice ale administrației resping adresele de centru de
    date: `mfe.gov.ro` și `oportunitati-ue.gov.ro` lasă conexiunea să expire,
    Kohesio răspunde 403. De pe o rețea obișnuită, toate răspund în jumătate de
    secundă. Nu este ceva ce se poate repara din cod.

    `REGISTRU_PROXY` spune pe unde să iasă cererile. Alege o ieșire pe care o
    controlezi — un tunel către rețeaua ta, sau o mașină a ta. Un proxy public
    anonim poate rescrie răspunsul, iar atunci amprenta SHA-256 pe care o
    păstrăm ar certifica ce a livrat proxy-ul, nu ce a publicat autoritatea.
    Proveniența este singurul lucru care face registrul verificabil.
    """
    adresa = os.environ.get("REGISTRU_PROXY", "").strip()
    if not adresa:
        return {}
    return {"http": adresa, "https": adresa}


#: Cum se prezintă clientul. `curl_cffi` reproduce amprenta TLS a unui Chrome
#: real, nu doar antetele lui. Fără ea, mai multe surse răspund 403 cererilor
#: venite dintr-un centru de date, deși datele sunt publice și reutilizabile.
IMPERSONARE = os.environ.get("REGISTRU_IMPERSONARE", "chrome")

#: Antete de navigator, plus cine suntem. `User-Agent` spune și numele
#: proiectului, și adresa lui: nu ascundem cine face cererea.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 {USER_AGENT}"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


class _StreamResponse:
    """Răspuns în flux, cu numele de metode pe care le folosește restul codului."""

    def __init__(self, response) -> None:
        self._response = response

    def raise_for_status(self):
        return self._response.raise_for_status()

    def iter_bytes(self, chunk_size: int = 1 << 16):
        return self._response.iter_content(chunk_size)

    def __getattr__(self, name):
        return getattr(self._response, name)


class Client:
    """Clientul HTTP al proiectului: `curl_cffi` pe dinăuntru, `httpx` pe dinafară.

    `curl_cffi` merge pe libcurl și reproduce amprenta TLS a unui browser, nu
    doar antetele. Interfața rămâne cea a lui `httpx` — `get` și `stream` — ca
    adaptoarele să nu știe pe ce merg.

    IPv4 se cere prin libcurl (`IPRESOLVE`), nu prin `socket`: libcurl are
    propria rezolvare, deci petecul pe `getaddrinfo` nu îl atinge. Petecul
    rămâne totuși pentru `wayback`, care merge pe `requests`.
    """

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        from curl_cffi import CurlOpt
        from curl_cffi import requests as curl_requests

        optiuni = {CurlOpt.IPRESOLVE: 1} if FORTEAZA_IPV4 else {}
        self._session = curl_requests.Session(
            impersonate=IMPERSONARE,
            headers={**BROWSER_HEADERS, **(headers or {})},
            timeout=HTTP_TIMEOUT,
            curl_options=optiuni,
            proxies=proxy() or None,  # ty: ignore[invalid-argument-type]
        )

    def get(self, url: str, **kwargs):
        return self._session.get(url, **kwargs)

    @contextmanager
    def stream(self, method: str, url: str, **kwargs):
        # `curl_cffi` tipează metoda ca literal; noi o primim ca text de la
        # apelanți, iar singura folosită este "GET".
        with self._session.stream(method, url, **kwargs) as response:  # ty: ignore[invalid-argument-type]
            yield _StreamResponse(response)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def http_client(headers: dict[str, str] | None = None) -> Client:
    return Client(headers)


def download(client: Client, url: str, target: Path) -> bool:
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
