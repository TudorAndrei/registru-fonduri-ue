"""Scorul „proiect de tip software”.

Un singur criteriu nu ajunge. Codul CAEN al beneficiarului ratează fabrica de
mobilă care își pune un ERP; textul singur ratează proiectele descrise birocratic.
Se combină trei semnale, cu ponderi, și se păstrează motivul scorului.

Semnalul al treilea este, deocamdată, potrivire de cuvinte-cheie. Locul unde
intră un model de limbaj este `score_row`, fără schimbări în restul pipeline-ului.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import polars as pl

from registru.caen import INTERVENTION_DIGITAL, caen_bucket
from registru.text import slug

#: cuvânt-cheie -> (etichetă, pondere). Cuvintele sunt fără diacritice.
KEYWORDS: dict[str, tuple[str, float]] = {
    # produs software
    "aplicatie software": ("produs", 0.9),
    "produs software": ("produs", 0.9),
    "platforma software": ("produs", 0.9),
    "dezvoltare software": ("produs", 0.85),
    "aplicatie mobila": ("produs", 0.8),
    "aplicatie web": ("produs", 0.8),
    "platforma online": ("produs", 0.7),
    "solutie informatica": ("produs", 0.7),
    "sistem informatic": ("produs", 0.65),
    "software": ("produs", 0.6),
    "saas": ("produs", 0.8),
    "api": ("produs", 0.4),
    # digitalizare internă
    "digitalizare": ("digitalizare", 0.7),
    # Formulările din ghidurile 2021-2027. „Digital” singur ar prinde orice apel
    # de mediu sau de transport care pomenește o componentă digitală, deci se
    # potrivesc doar expresiile care numesc chiar o lucrare de software.
    "solutii digitale": ("produs", 0.7),
    "solutie digitala": ("produs", 0.7),
    "servicii publice digitale": ("digitalizare", 0.8),
    "servicii digitale": ("digitalizare", 0.65),
    "instrumente digitale": ("digitalizare", 0.6),
    "hub de inovare digitala": ("digitalizare", 0.6),
    "interoperabilitate": ("digitalizare", 0.6),
    "prelucrarea datelor": ("cdi", 0.55),
    # Familia PoCIDIF: „Dezvoltarea de noi servicii/aplicații/produse prin
    # inovare și adoptarea de tehnologii avansate”. Fiecare bucată e slabă
    # singură — „aplicații” poate fi orice — dar două împreună trec pragul.
    # Formularea proprie familiei: „servicii/aplicații/produse”, care după
    # normalizare devine „servicii aplicatii produse”. E precisă, deci cântărește
    # mult. „Aplicații” singur rămâne slab: poate fi orice fel de aplicație.
    "servicii aplicatii produse": ("produs", 0.8),
    "aplicatii": ("produs", 0.5),
    "platforme informatice": ("produs", 0.8),
    "tehnologii avansate": ("cdi", 0.5),
    "inovare digitala": ("cdi", 0.6),
    "transformare digitala": ("digitalizare", 0.7),
    "erp": ("digitalizare", 0.75),
    "crm": ("digitalizare", 0.75),
    "automatizare proces": ("digitalizare", 0.6),
    "arhivare electronica": ("digitalizare", 0.6),
    "semnatura electronica": ("digitalizare", 0.6),
    "e guvernare": ("digitalizare", 0.7),
    "servicii electronice": ("digitalizare", 0.6),
    "ghiseu unic": ("digitalizare", 0.5),
    # cercetare-dezvoltare cu componentă software
    "inteligenta artificiala": ("cdi", 0.85),
    "invatare automata": ("cdi", 0.85),
    "machine learning": ("cdi", 0.85),
    "big data": ("cdi", 0.7),
    "blockchain": ("cdi", 0.7),
    "internet of things": ("cdi", 0.6),
    "iot": ("cdi", 0.5),
    "algoritm": ("cdi", 0.5),
    # infrastructură IT — se numără, dar nu e software
    "centru de date": ("infrastructura", 0.4),
    "cloud": ("infrastructura", 0.45),
    "infrastructura it": ("infrastructura", 0.45),
    "echipamente it": ("infrastructura", 0.3),
    "retea de calculatoare": ("infrastructura", 0.3),
    "banda larga": ("infrastructura", 0.35),
}

#: Cuvinte care scad scorul: apar des în proiecte care nu au nimic software.
NEGATIVE = {
    "reabilitare": 0.3,
    "modernizare drum": 0.4,
    "canalizare": 0.4,
    "alimentare cu apa": 0.4,
    "eficienta energetica": 0.25,
    "constructie": 0.25,
}

WEIGHT_CAEN = 0.45
WEIGHT_INTERVENTION = 0.35
# Calibrat astfel încât un titlu explicit („platformă software”, „digitalizare”,
# „ERP”) să treacă singur pragul, dar un cuvânt slab („cloud”, „API”) să nu.
WEIGHT_TEXT = 0.75

#: Cât adaugă al doilea indiciu din text, ca fracție din greutatea lui.
SECOND_HINT = 0.4

#: Peste acest scor, rândul intră în vederea „software” a registrului.
THRESHOLD = 0.5

#: Potrivirea se face pe cuvinte, nu pe subșiruri. `"api" in text` se potrivea
#: în „capitalizare”, `"erp"` în „interpretare”, `"iot"` în „biotehnologie” — și
#: fiecare adăuga scor unui proiect care nu are nimic software.
#:
#: Româna este flexionară, iar flexiunea nu stă doar la coadă: „digitalizare”
#: trebuie să prindă „digitalizarea” și „digitalizării”, iar „soluție
#: informatică” trebuie să prindă „soluții informatice”, unde se schimbă ambele
#: cuvinte. Deci fiecare cuvânt lung se caută după rădăcină, cu o terminație
#: liberă. Cuvintele scurte („api”, „erp”, „iot”) se caută exact, altfel „api”
#: ar prinde „apicultură”.
STEM_MIN_LENGTH = 5
STEM_MAX_SUFFIX = 4


def _word_pattern(word: str) -> str:
    if len(word) < STEM_MIN_LENGTH:
        return re.escape(word)
    return re.escape(word[:-1]) + f"[a-z]{{0,{STEM_MAX_SUFFIX}}}"


def _pattern(keyword: str) -> re.Pattern[str]:
    """Expresie pentru un cuvânt-cheie, cu rădăcini pentru fiecare cuvânt lung."""
    body = "[ -]+".join(_word_pattern(word) for word in keyword.split())
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


_PATTERNS: dict[str, re.Pattern[str]] = {word: _pattern(word) for word in KEYWORDS}
_NEGATIVE_PATTERNS: dict[str, re.Pattern[str]] = {word: _pattern(word) for word in NEGATIVE}


@dataclass(slots=True)
class Verdict:
    score: float
    label: str
    evidence: str


def score_row(
    title: str | None,
    summary: str | None,
    caen: str | None,
    intervention: str | None,
) -> Verdict:
    text = slug(f"{title or ''} {summary or ''}")
    score = 0.0
    labels: dict[str, float] = {}
    evidence: list[str] = []

    bucket = caen_bucket(caen)
    if bucket == "software":
        score += WEIGHT_CAEN
        labels["produs"] = labels.get("produs", 0) + WEIGHT_CAEN
        evidence.append(f"CAEN {caen}")
    elif bucket == "cdi":
        score += WEIGHT_CAEN * 0.6
        labels["cdi"] = labels.get("cdi", 0) + WEIGHT_CAEN * 0.6
        evidence.append(f"CAEN {caen} (C-D)")

    if intervention:
        code = str(intervention).strip().zfill(3)[:3]
        if code in INTERVENTION_DIGITAL:
            score += WEIGHT_INTERVENTION
            labels["digitalizare"] = labels.get("digitalizare", 0) + WEIGHT_INTERVENTION
            evidence.append(f"intervenție {code}")

    if text:
        hits: list[float] = []
        for keyword, (label, weight) in KEYWORDS.items():
            if _PATTERNS[keyword].search(text):
                labels[label] = labels.get(label, 0) + weight
                hits.append(weight)
                evidence.append(keyword)
        # Cel mai puternic indiciu, plus o parte din al doilea. Două indicii
        # moderate și independente spun mai mult decât unul singur: „aplicații”
        # poate fi orice, „tehnologii avansate” la fel, dar împreună descriu un
        # apel de produs. Al treilea nu mai adaugă: e de obicei același lucru
        # spus altfel.
        hits.sort(reverse=True)
        if hits:
            score += WEIGHT_TEXT * (hits[0] + SECOND_HINT * (hits[1] if len(hits) > 1 else 0.0))
        for keyword, penalty in NEGATIVE.items():
            if _NEGATIVE_PATTERNS[keyword].search(text):
                score -= penalty
                evidence.append(f"-{keyword}")

    score = max(0.0, min(1.0, score))
    label = max(labels, key=lambda name: labels[name]) if labels else "necunoscut"
    return Verdict(round(score, 3), label, "; ".join(evidence[:8]))


def classify(frame: pl.DataFrame) -> pl.DataFrame:
    """Adaugă `software_score`, `software_label`, `software_evidence`, `is_software`."""
    if frame.height == 0:
        return frame

    # `caen` apare abia după pasul de îmbogățire ANAF; până atunci lipsește.
    columns = ["project_title", "project_summary", "intervention_code"]
    if "caen" in frame.columns:
        columns.append("caen")
    verdicts = [
        score_row(
            row["project_title"],
            row["project_summary"],
            row.get("caen"),
            row["intervention_code"],
        )
        for row in frame.select(columns).to_dicts()
    ]
    return frame.with_columns(
        pl.Series("software_score", [v.score for v in verdicts], dtype=pl.Float64),
        pl.Series("software_label", [v.label for v in verdicts], dtype=pl.Utf8),
        pl.Series("software_evidence", [v.evidence for v in verdicts], dtype=pl.Utf8),
    ).with_columns((pl.col("software_score") >= THRESHOLD).alias("is_software"))


#: Cât adaugă eticheta de domeniu pusă de portal. Sub prag intenționat: singură
#: nu ajunge. Portalul etichetează larg — un apel de infrastructură spitalicească
#: poartă „Digitalizare” lângă „Sănătate” și „Infrastructură”, pentru că are și o
#: componentă digitală, nu pentru că este un apel de software.
WEIGHT_DOMAIN = 0.35


def classify_calls(frame: pl.DataFrame) -> pl.DataFrame:
    """Același scor, aplicat apelurilor.

    Un apel nu are cod CAEN — nu există încă un beneficiar — deci rămân două
    semnale: textul propriu (titlu și obiectiv specific) și eticheta de domeniu
    pusă de portal.

    Cele două se numără o singură dată fiecare. Domeniile **nu** se lipesc în
    textul dat clasificatorului: altfel „Digitalizare” ar fi numărat și ca
    potrivire de cuvânt, și ca etichetă, iar suma trece pragul de una singură.
    """
    if frame.height == 0:
        return frame

    verdicts = []
    for row in frame.select("title", "specific_objective", "domains").to_dicts():
        domains = row.get("domains") or []
        verdict = score_row(row["title"], row["specific_objective"], None, None)
        if "Digitalizare" in domains:
            verdict = Verdict(
                round(min(1.0, verdict.score + WEIGHT_DOMAIN), 3),
                verdict.label if verdict.label != "necunoscut" else "digitalizare",
                "; ".join(filter(None, ["domeniu: Digitalizare", verdict.evidence])),
            )
        verdicts.append(verdict)
    return frame.with_columns(
        pl.Series("software_score", [v.score for v in verdicts], dtype=pl.Float64),
        pl.Series("software_label", [v.label for v in verdicts], dtype=pl.Utf8),
        pl.Series("software_evidence", [v.evidence for v in verdicts], dtype=pl.Utf8),
    ).with_columns((pl.col("software_score") >= THRESHOLD).alias("is_software"))
