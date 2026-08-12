"""Aducerea registrelor gata construite, pentru mașinile care nu pot colecta.

Sursele publice resping adresele de centru de date. Verificat în august 2026:
`oportunitati-ue.gov.ro` și `mfe.gov.ro` lasă conexiunea să expire, Kohesio
răspunde 403 — de pe un server Hetzner **și** de pe un agent GitHub Actions,
care mai adaugă și un 503 de la arhivă. De pe o conexiune obișnuită, toate
răspund în jumătate de secundă.

Deci colectarea rulează unde merge — pe calculatorul tău — și publică cele două
fișiere Parquet în depozit. Serverul le ia de acolo și atât: nu mai are nevoie
să ajungă la nicio sursă.

Se descarcă numai rezultatul, nu și dovada. Cine vrea să verifice un rând are
în el adresa, amprenta SHA-256 și data descărcării.
"""

from __future__ import annotations

import os
from pathlib import Path

from registru.config import CALLS_PARQUET, DATA_DIR, REGISTRY_PARQUET, ensure_dirs
from registru.sources.base import http_client, sha256_file

#: De unde se iau registrele. Implicit, chiar depozitul acesta.
#: `os.environ.get` cu implicit nu ajută aici: o variabilă definită dar goală
#: întoarce șirul gol, nu implicitul, iar compose-ul chiar o definește goală.
SURSA = (
    os.environ.get("REGISTRU_SURSA", "").strip()
    or "https://raw.githubusercontent.com/TudorAndrei/registru-fonduri-ue/main/data"
).rstrip("/")

#: Ce se aduce. Jurnalul vine și el, ca interfața să poată spune când a fost
#: ultima colectare — altfel ar arăta date proaspete fără să spună cât de vechi.
FISIERE: dict[str, Path] = {
    "registry/registru.parquet": REGISTRY_PARQUET,
    "registry/apeluri.parquet": CALLS_PARQUET,
    "runs/latest.json": DATA_DIR / "runs" / "latest.json",
}


def sync() -> list[tuple[str, str]]:
    """Aduce registrele publicate. Întoarce ce s-a schimbat și ce nu.

    Se scrie întâi într-un fișier alăturat și abia apoi se mută peste cel vechi:
    o descărcare întreruptă nu are voie să lase în urmă un registru pe jumătate,
    pe care interfața l-ar citi în aceeași clipă.
    """
    ensure_dirs()
    rezultat: list[tuple[str, str]] = []

    with http_client() as client:
        for nume, tinta in FISIERE.items():
            adresa = f"{SURSA}/{nume}"
            vechi = sha256_file(tinta) if tinta.exists() else None
            temporar = tinta.with_suffix(tinta.suffix + ".nou")
            tinta.parent.mkdir(parents=True, exist_ok=True)
            try:
                with client.stream("GET", adresa) as raspuns:
                    raspuns.raise_for_status()
                    with temporar.open("wb") as fisier:
                        for bucata in raspuns.iter_bytes(1 << 16):
                            fisier.write(bucata)
            except Exception as eroare:  # noqa: BLE001 — un fișier lipsă nu oprește restul
                temporar.unlink(missing_ok=True)
                rezultat.append((nume, f"eroare: {type(eroare).__name__}"))
                continue

            nou = sha256_file(temporar)
            if nou == vechi:
                temporar.unlink(missing_ok=True)
                rezultat.append((nume, "neschimbat"))
                continue
            temporar.replace(tinta)
            rezultat.append((nume, f"actualizat, {tinta.stat().st_size / 1e6:.1f} MB"))

    return rezultat
