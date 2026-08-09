"""Legături către proiect, în afara registrului.

Realitatea neplăcută: pentru listele naționale 2014-2020 nu există o pagină
publică per proiect. Autoritățile publică fișiere Excel, atât. Un link către
fișier nu ajută pe nimeni — descarcă 900 KB de tabel ca să vezi un rând.

Deci registrul își face propria pagină de proiect, iar de acolo trimite mai
departe către ce se poate verifica: fișa Kohesio unde există, o căutare Kohesio
unde nu, și datele fiscale ale beneficiarului la ANAF.
"""

from __future__ import annotations

from urllib.parse import quote

KOHESIO_PROJECT = "https://kohesio.ec.europa.eu/en/projects/{item}"
KOHESIO_SEARCH = "https://kohesio.ec.europa.eu/en/projects?keywords={query}&country=Q218"
ANAF_LOOKUP = "https://mfinante.gov.ro/ro/web/site/info-fiscale?cui={cui}"


def project_url(source: str, project_code: str | None) -> str | None:
    """Pagina oficială a proiectului, dacă sursa are una.

    Doar Kohesio are. `project_code` este acolo identificatorul de entitate
    (`Q7417504`), verificat: `https://kohesio.ec.europa.eu/en/projects/Q7417504`
    răspunde 200.
    """
    if source == "kohesio" and project_code:
        return KOHESIO_PROJECT.format(item=project_code)
    return None


def kohesio_search_url(*terms: str | None) -> str:
    """Căutare Kohesio pentru un proiect care nu are fișă proprie.

    Nu este un link către proiect, este o încercare de a-l găsi. Rezultatele
    sunt zgomotoase; interfața trebuie să spună asta.
    """
    query = " ".join(term for term in terms if term)[:120]
    return KOHESIO_SEARCH.format(query=quote(query))


def anaf_url(cui: str | None) -> str | None:
    """Fișa fiscală a beneficiarului, când listele publică un CUI."""
    if not cui:
        return None
    return ANAF_LOOKUP.format(cui=quote(str(cui)))
