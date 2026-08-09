"""Maparea antetelor reale din fișierele oficiale pe schema canonică.

Fiecare Autoritate de Management scrie altfel același lucru, iar de la o publicare
la alta se schimbă. Aici stau sinonimele, normalizate fără diacritice și fără
punctuație (vezi `registru.text.normalize_header`).

Când apare un antet nou, se adaugă aici — nu în adaptor.
"""

from __future__ import annotations

from registru.text import normalize_header

#: câmp canonic -> antete întâlnite în fișiere, în ordinea preferinței.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "project_code": (
        "cod smis",
        "codsmis",
        "cod smis proiect",
        "cod smis cod proiect",
        "cod my smis",
        "cod mysmis",
        "cod proiect",
        "cod smis 2014",
        "numar contract",
        "cod apel",
    ),
    "beneficiary_name": (
        "beneficiar",
        "denumire beneficiar",
        "nume beneficiar",
        "denumirea beneficiarului",
        "solicitant",
        "denumire solicitant",
    ),
    "beneficiary_cui": (
        "cui",
        "cui beneficiar",
        "cod fiscal",
        "cod unic de inregistrare",
        "cif",
        "cui cif",
    ),
    "project_title": (
        "titlu proiect",
        "denumire proiect",
        "titlul proiectului",
        "denumirea proiectului",
        "titlu",
        "denumire operatiune",
        "denumirea operatiunii",
    ),
    "project_summary": (
        "rezumat",
        "obiectivul proiectului",
        "scopul operatiunii",
        "descriere proiect",
        "rezumatul proiectului",
        "sinteza proiectului",
    ),
    "start_date": (
        "data inceput",
        "data de incepere",
        "data inceput proiect",
        "data semnarii contractului",
        "data de start",
    ),
    "end_date": (
        "data sfarsit",
        "data de finalizare",
        "data finalizare",
        "data sfarsit proiect",
        "data de incheiere",
    ),
    "total_eligible_amount": (
        "valoarea eligibila a proiectului",
        "valoare eligibila a proiectului",
        "valoare totala eligibila",
        "valoare eligibila totala",
        "cheltuiala eligibila totala",
        "valoare eligibila",
    ),
    "total_project_amount": (
        "total valoare proiect",
        "valoarea totala a proiectului",
        "valoare totala proiect",
        "valoare totala",
    ),
    "payments_amount": (
        "plati catre beneficiari",
        "plati efectuate",
        "valoare plati",
    ),
    "beneficiary_type": ("tip beneficiar", "tipul beneficiarului"),
    "eu_amount": (
        "valoare ue",
        "contributie ue",
        "finantare ue",
        "valoare finantare ue",
        "contributia uniunii europene",
        "valoare nerambursabila ue",
        "fonduri ue",
    ),
    "cofinancing_rate": (
        "rata de cofinantare",
        "procent cofinantare",
        "rata cofinantare ue",
    ),
    "fund": ("fond", "fondul", "sursa de finantare"),
    "program": ("program", "program operational", "denumire program", "po"),
    "specific_objective": (
        "obiectiv specific",
        "os",
        "prioritate",
        "axa prioritara",
        "domeniu major de interventie",
    ),
    "intervention_code": (
        "categorie de interventie",
        "cod interventie",
        "tip interventie",
        "domeniu de interventie",
        "cod domeniu de interventie",
    ),
    "region": ("regiune", "regiunea", "regiune de dezvoltare"),
    "county": ("judet", "judetul", "judet implementare"),
    "locality": ("localitate", "localitatea", "uat", "oras", "comuna"),
    "project_status": ("stadiu", "stare proiect", "status", "stadiu implementare"),
    "currency": ("moneda", "valuta"),
}

#: antet normalizat -> câmp canonic
_LOOKUP: dict[str, str] = {}
for _field, _aliases in HEADER_SYNONYMS.items():
    for _alias in _aliases:
        _LOOKUP.setdefault(normalize_header(_alias), _field)


def match_header(header: str | None) -> str | None:
    """Câmpul canonic pentru un antet, sau None dacă nu îl recunoaștem.

    Se încearcă potrivirea exactă, apoi cea prin prefix — fișierele reale conțin
    antete de tipul `Valoare eligibila (lei)` sau `Judet implementare proiect`.
    """
    key = normalize_header(header)
    if not key:
        return None
    if key in _LOOKUP:
        return _LOOKUP[key]
    candidates = [(alias, field) for alias, field in _LOOKUP.items() if key.startswith(alias)]
    if candidates:
        # cel mai lung alias care se potrivește este cel mai specific
        return max(candidates, key=lambda pair: len(pair[0]))[1]
    return None


def map_columns(headers: list[str]) -> dict[str, str]:
    """{antet original: câmp canonic}, fără duplicate — primul câștigă."""
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for header in headers:
        field = match_header(header)
        if field and field not in taken:
            mapping[header] = field
            taken.add(field)
    return mapping
