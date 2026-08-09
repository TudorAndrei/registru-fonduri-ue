"""Coduri CAEN și coduri de intervenție relevante pentru software.

Codurile de intervenție sunt cele din anexa I la Regulamentul (UE) 2021/1060,
domeniul de intervenție. Lista de mai jos acoperă digitalizarea și TIC; nu este
exhaustivă și se completează pe măsură ce apar fișiere reale.
"""

from __future__ import annotations

#: CAEN Rev. 2, activități de software și servicii informatice.
CAEN_SOFTWARE: dict[str, str] = {
    "5821": "Activități de editare a jocurilor de calculator",
    "5829": "Activități de editare a altor produse software",
    "6201": "Activități de realizare a soft-ului la comandă",
    "6202": "Activități de consultanță în tehnologia informației",
    "6203": "Activități de management al facilităților de calcul",
    "6209": "Alte activități de servicii privind tehnologia informației",
    "6311": "Prelucrarea datelor, administrarea paginilor web",
    "6312": "Activități ale portalurilor web",
}

#: Cercetare-dezvoltare, unde se ascund multe proiecte de produs software.
CAEN_RD: dict[str, str] = {
    "7211": "Cercetare-dezvoltare în biotehnologie",
    "7219": "Cercetare-dezvoltare în alte științe naturale și inginerie",
}

#: Telecomunicații și hardware — vecinătate, nu software.
CAEN_ADJACENT: dict[str, str] = {
    "2611": "Fabricarea subansamblurilor electronice",
    "2620": "Fabricarea calculatoarelor și a echipamentelor periferice",
    "6110": "Activități de telecomunicații prin rețele cu cablu",
    "6120": "Activități de telecomunicații prin rețele fără cablu",
    "6190": "Alte activități de telecomunicații",
}

#: Coduri de domeniu de intervenție 2021-2027 legate de digitalizare și TIC.
INTERVENTION_DIGITAL: dict[str, str] = {
    "013": "Digitalizarea IMM-urilor",
    "016": "Soluții TIC, servicii electronice, aplicații pentru administrație",
    "017": "Soluții TIC, servicii electronice, aplicații pentru IMM-uri",
    "018": "Servicii și aplicații de e-sănătate",
    "019": "Servicii și aplicații de competențe digitale și incluziune digitală",
    "020": "Servicii și aplicații de e-guvernare",
    "021": "Dezvoltarea competențelor pentru specializare inteligentă",
    "036": "TIC: rețele de foarte mare capacitate",
}


def caen_bucket(code: str | None) -> str | None:
    """Din codul CAEN, categoria pe care o folosește clasificatorul."""
    if not code:
        return None
    key = str(code).strip()[:4]
    if key in CAEN_SOFTWARE:
        return "software"
    if key in CAEN_RD:
        return "cdi"
    if key in CAEN_ADJACENT:
        return "adiacent"
    return None
