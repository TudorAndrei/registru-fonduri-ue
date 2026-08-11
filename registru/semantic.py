"""Clasificare pe înțeles, nu pe cuvinte.

Lista de cuvinte-cheie din `pipeline.classify` este precisă când se potrivește,
dar nu are cum să acopere formulările pe care nu le-a văzut nimeni încă. A fost
corectată de două ori într-o singură zi, de fiecare dată după ce un apel real a
scăpat pe lângă ea.

Aici textul se compară cu descrieri de referință, prin apropiere de înțeles. Un
model mic de încorporare (0,22 GB, ONNX) rulează pe procesor, fără PyTorch și
fără placă video — poate rula deci și într-un container de câțiva sute de
megaocteți, o dată pe lună.

Modelul nu înlocuiește vocabularul, ci se adaugă la el: unul aduce precizie,
celălalt acoperire, iar motivul scorului spune care dintre ele a vorbit.
"""

from __future__ import annotations

import functools
import os

MODEL = os.environ.get(
    "REGISTRU_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

#: Ce înseamnă „proiect de software”, spus în propoziții, nu în cuvinte-cheie.
REFERINTE_DA = (
    "dezvoltarea unui produs software sau a unei platforme informatice",
    "digitalizarea unei organizații prin sisteme informatice",
    "servicii publice digitale și e-guvernare",
    "cercetare în inteligență artificială și prelucrarea datelor",
    "aplicații mobile și web pentru clienți",
    "automatizarea proceselor prin soluții digitale",
)

#: Și ce nu înseamnă. Fără contraexemple, orice text ar semăna cu orice.
REFERINTE_NU = (
    "construcția sau modernizarea unei infrastructuri fizice",
    "investiții în clădiri, drumuri, rețele de apă și canalizare",
    "producerea de energie și eficiență energetică",
    "achiziția de utilaje și echipamente de producție",
    "formare profesională și incluziune socială",
    "servicii medicale și infrastructură sanitară",
    "agricultură, silvicultură și dezvoltare rurală",
)

#: Diferența de apropiere de la care textul înclină spre software. Sub ea,
#: semnalul nu spune nimic; peste ea, crește până la saturare.
PRAG = 0.03
SATURARE = 0.30


class Indisponibil(RuntimeError):
    """Modelul nu este instalat. Pipeline-ul merge mai departe fără el."""


@functools.lru_cache(maxsize=1)
def _model():
    try:
        from fastembed import TextEmbedding
    except ImportError as eroare:  # pragma: no cover — depinde de instalare
        raise Indisponibil("fastembed nu este instalat; `uv sync --extra clasificare`") from eroare
    return TextEmbedding(MODEL)


@functools.lru_cache(maxsize=1)
def _referinte():
    import numpy as np

    model = _model()
    vectori = np.array(list(model.embed([*REFERINTE_DA, *REFERINTE_NU])))
    vectori = vectori / np.linalg.norm(vectori, axis=1, keepdims=True)
    return vectori[: len(REFERINTE_DA)], vectori[len(REFERINTE_DA) :]


def disponibil() -> bool:
    try:
        _model()
    except Indisponibil:
        return False
    return True


def scoruri(texte: list[str]) -> list[float]:
    """Cât de mult înclină fiecare text spre software, între 0 și 1.

    Se compară cu ambele seturi de referințe și contează diferența: un text
    care seamănă cu „platformă informatică” dar și cu „construcție de drum” nu
    spune nimic, iar diferența exprimă exact asta.
    """
    import numpy as np

    curatate = [text.strip() if text else "" for text in texte]
    indici = [i for i, text in enumerate(curatate) if text]
    if not indici:
        return [0.0] * len(texte)

    model = _model()
    da, nu = _referinte()
    vectori = np.array(list(model.embed([curatate[i] for i in indici])))
    vectori = vectori / np.linalg.norm(vectori, axis=1, keepdims=True)

    delta = (vectori @ da.T).max(axis=1) - (vectori @ nu.T).max(axis=1)
    normalizat = np.clip((delta - PRAG) / (SATURARE - PRAG), 0.0, 1.0)

    rezultat = [0.0] * len(texte)
    for pozitie, valoare in zip(indici, normalizat, strict=True):
        rezultat[pozitie] = round(float(valoare), 3)
    return rezultat
