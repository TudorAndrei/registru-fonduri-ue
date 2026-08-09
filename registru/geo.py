"""Geografia, adusă la o listă închisă.

Coloana `Județ` din fișierele oficiale nu conține un județ. Conține text liber:
listele de județe ale unui proiect național, cu și fără diacritice, cu punct și
virgulă sau cu virgulă, uneori cu abrevieri de două litere, uneori cu numele
regiunii lipit peste. Prima extragere a dat 1.410 valori distincte pentru 42 de
județe, ceea ce face orice filtru inutilizabil.

Aici se parsează textul acela într-o listă de județe canonice. Regiunea nu se
mai citește din text: fiecare județ aparține exact unei regiuni de dezvoltare,
deci se deduce, ceea ce este și mai corect, și mai simplu.
"""

from __future__ import annotations

import re

from registru.text import strip_diacritics

NATIONAL = "Național"

#: județ canonic -> (cod din două litere, regiune de dezvoltare)
COUNTIES: dict[str, tuple[str, str]] = {
    "Alba": ("AB", "Centru"),
    "Arad": ("AR", "Vest"),
    "Argeș": ("AG", "Sud-Muntenia"),
    "Bacău": ("BC", "Nord-Est"),
    "Bihor": ("BH", "Nord-Vest"),
    "Bistrița-Năsăud": ("BN", "Nord-Vest"),
    "Botoșani": ("BT", "Nord-Est"),
    "Brăila": ("BR", "Sud-Est"),
    "Brașov": ("BV", "Centru"),
    "București": ("B", "București-Ilfov"),
    "Buzău": ("BZ", "Sud-Est"),
    "Caraș-Severin": ("CS", "Vest"),
    "Călărași": ("CL", "Sud-Muntenia"),
    "Cluj": ("CJ", "Nord-Vest"),
    "Constanța": ("CT", "Sud-Est"),
    "Covasna": ("CV", "Centru"),
    "Dâmbovița": ("DB", "Sud-Muntenia"),
    "Dolj": ("DJ", "Sud-Vest Oltenia"),
    "Galați": ("GL", "Sud-Est"),
    "Giurgiu": ("GR", "Sud-Muntenia"),
    "Gorj": ("GJ", "Sud-Vest Oltenia"),
    "Harghita": ("HR", "Centru"),
    "Hunedoara": ("HD", "Vest"),
    "Ialomița": ("IL", "Sud-Muntenia"),
    "Iași": ("IS", "Nord-Est"),
    "Ilfov": ("IF", "București-Ilfov"),
    "Maramureș": ("MM", "Nord-Vest"),
    "Mehedinți": ("MH", "Sud-Vest Oltenia"),
    "Mureș": ("MS", "Centru"),
    "Neamț": ("NT", "Nord-Est"),
    "Olt": ("OT", "Sud-Vest Oltenia"),
    "Prahova": ("PH", "Sud-Muntenia"),
    "Sălaj": ("SJ", "Nord-Vest"),
    "Satu Mare": ("SM", "Nord-Vest"),
    "Sibiu": ("SB", "Centru"),
    "Suceava": ("SV", "Nord-Est"),
    "Teleorman": ("TR", "Sud-Muntenia"),
    "Timiș": ("TM", "Vest"),
    "Tulcea": ("TL", "Sud-Est"),
    "Vaslui": ("VS", "Nord-Est"),
    "Vâlcea": ("VL", "Sud-Vest Oltenia"),
    "Vrancea": ("VN", "Sud-Est"),
}

COUNTY_NAMES: list[str] = sorted(COUNTIES)

REGIONS: list[str] = sorted({region for _, region in COUNTIES.values()})

#: Scrieri alternative întâlnite în fișiere, aduse la forma canonică.
ALIASES: dict[str, str] = {
    "bistrita nasaud": "Bistrița-Năsăud",
    "bistrita-nasaud": "Bistrița-Năsăud",
    "caras severin": "Caraș-Severin",
    "caras-severin": "Caraș-Severin",
    "satu-mare": "Satu Mare",
    "municipiul bucuresti": "București",
    "muncipiul bucuresti": "București",  # scris greșit în fișierele POCU
    "bucuresti ilfov": "București",
}

#: Cuvinte care înseamnă „toată țara”, nu un județ.
NATIONAL_MARKERS = ("nivel national", "national", "intreaga tara", "toate judetele")


def _pattern(name: str) -> re.Pattern[str]:
    """Nume de județ, fără diacritice, cu spațiu sau cratimă interschimbabile."""
    plain = strip_diacritics(name).lower()
    body = re.escape(plain).replace(r"\ ", "[ -]").replace(r"\-", "[ -]")
    return re.compile(rf"(?<![a-z]){body}(?![a-z])")


_COUNTY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, _pattern(name)) for name in COUNTY_NAMES
]
_ALIAS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (canonical, _pattern(alias)) for alias, canonical in ALIASES.items()
]

#: Codurile se caută pe textul original: doar majuscule izolate contează,
#: altfel „CS” din „CSA” sau „B” din orice inițială ar produce potriviri false.
_CODE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])"))
    for name, (code, _) in COUNTIES.items()
    if len(code) == 2
]


def parse_counties(*texts: str | None) -> list[str]:
    """Din text liber, lista de județe canonice, în ordine alfabetică.

    Textul care spune „nivel național” întoarce `["Național"]`, nu toate cele 42:
    un proiect național nu este un proiect al fiecărui județ în parte.
    """
    joined = " ".join(text for text in texts if text)
    if not joined.strip():
        return []

    plain = strip_diacritics(joined).lower()
    found: set[str] = set()

    for name, pattern in _COUNTY_PATTERNS:
        if pattern.search(plain):
            found.add(name)
    for name, pattern in _ALIAS_PATTERNS:
        if pattern.search(plain):
            found.add(name)

    # Abrevierile apar amestecate cu numele întregi: „Bihor,BN, Cluj, MM, SM, SJ”.
    for name, pattern in _CODE_PATTERNS:
        if pattern.search(joined):
            found.add(name)

    if not found and any(marker in plain for marker in NATIONAL_MARKERS):
        return [NATIONAL]

    return sorted(found)


#: Regiunile compuse se caută înaintea celor dintr-un cuvânt, altfel „Vest” ar
#: înghiți „Nord-Vest” și „Sud-Vest Oltenia”.
_REGION_COMPOUND: list[tuple[str, re.Pattern[str]]] = [
    ("București-Ilfov", re.compile(r"bucuresti[ -]ilfov")),
    ("Sud-Vest Oltenia", re.compile(r"sud[ -]vest")),
    ("Nord-Vest", re.compile(r"nord[ -]vest")),
    ("Nord-Est", re.compile(r"nord[ -]est")),
    ("Sud-Est", re.compile(r"sud[ -]est")),
    ("Sud-Muntenia", re.compile(r"sud[ -]munten")),
]
_REGION_SIMPLE: list[tuple[str, re.Pattern[str]]] = [
    ("Centru", re.compile(r"(?<![a-z])centru(?![a-z])")),
    ("Vest", re.compile(r"(?<![a-z-])vest(?![a-z])")),
]


def parse_regions(*texts: str | None) -> list[str]:
    """Regiuni de dezvoltare citite direct din text.

    Se folosește doar ca rezervă, pentru rândurile care numesc regiunea fără
    niciun județ — de exemplu „Sud-Vest Oltenia”.
    """
    joined = " ".join(text for text in texts if text)
    if not joined.strip():
        return []
    plain = strip_diacritics(joined).lower()
    found = {name for name, pattern in _REGION_COMPOUND if pattern.search(plain)}
    for name, pattern in _REGION_SIMPLE:
        if pattern.search(plain):
            found.add(name)
    return sorted(found)


def regions_for(counties: list[str]) -> list[str]:
    """Regiunile de dezvoltare ale unei liste de județe.

    Nu se citesc din coloana `Regiune` a fișierului, care este la fel de
    dezordonată ca cea de județ. Fiecare județ aparține exact unei regiuni.
    """
    return sorted({COUNTIES[county][1] for county in counties if county in COUNTIES})
