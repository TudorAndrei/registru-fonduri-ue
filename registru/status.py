"""Stadiul proiectului, adus la o listă închisă.

Coloana `Stadiu proiect` are 44 de valori distincte pentru vreo șase stări reale:
`Finalizat`, `finalizat`, `FINALIZAT`, `fINALIZAT`, `FINALIZAT ` și
`Proiect finalizat` sunt același lucru. Se mai strecoară și rânduri de antet
(`Project status`) și numere (`22`).

Ordinea regulilor contează: `nefinalizat` conține `finalizat`, iar
`în curs de reziliere` nu înseamnă `reziliat`.
"""

from __future__ import annotations

from registru.text import slug

UNKNOWN = "Necunoscut"

#: (fragment căutat în textul fără diacritice, stadiu canonic), în ordine.
RULES: tuple[tuple[str, str], ...] = (
    ("curs de reziliere", "În reziliere"),
    ("proces de reziliere", "În reziliere"),
    ("reziliat", "Reziliat"),
    ("incetat", "Reziliat"),
    ("revocat", "Reziliat"),
    ("nefinalizat", "Nefinalizat"),
    ("finalizat", "Finalizat"),
    ("implementare", "În implementare"),
    ("etapiza", "Etapizat"),  # acoperă „etapizat”, „etapizabil”, „etapizate”
    ("nefunctional", "Nefuncțional"),
    ("suspenda", "Suspendat"),
    ("indicatori", "Indicatori la zero"),
)

#: Ordinea în care apar în filtru: de la „mergem bine” la „nu a ieșit”.
STATUSES: list[str] = [
    "Finalizat",
    "În implementare",
    "Etapizat",
    "Nefinalizat",
    "În reziliere",
    "Reziliat",
    "Suspendat",
    "Nefuncțional",
    "Indicatori la zero",
    UNKNOWN,
]


def normalize_status(value: str | None) -> str:
    """Textul brut al stadiului -> una dintre stările din `STATUSES`."""
    key = slug(value)
    if not key:
        return UNKNOWN
    for fragment, status in RULES:
        if fragment in key:
            return status
    return UNKNOWN
