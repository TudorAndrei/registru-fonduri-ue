"""Scorul „proiect de tip software”.

Un singur criteriu nu ajunge. Codul CAEN al beneficiarului ratează fabrica de
mobilă care își pune un ERP; textul singur ratează proiectele descrise birocratic.
Se combină trei semnale, cu ponderi, și se păstrează motivul scorului.

Semnalul al treilea este, deocamdată, potrivire de cuvinte-cheie. Locul unde
intră un model de limbaj este `score_row`, fără schimbări în restul pipeline-ului.
"""

from __future__ import annotations

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

#: Peste acest scor, rândul intră în vederea „software” a registrului.
THRESHOLD = 0.5


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
        best = 0.0
        for keyword, (label, weight) in KEYWORDS.items():
            if keyword in text:
                labels[label] = labels.get(label, 0) + weight
                best = max(best, weight)
                evidence.append(keyword)
        score += WEIGHT_TEXT * best
        for keyword, penalty in NEGATIVE.items():
            if keyword in text:
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


def classify_calls(frame: pl.DataFrame) -> pl.DataFrame:
    """Același scor, aplicat apelurilor.

    Un apel nu are cod CAEN — nu există încă un beneficiar — deci rămân două
    semnale: textul (titlu, obiectiv specific) și domeniile declarate de site,
    dintre care „Digitalizare” și „Cercetare, dezvoltare, inovare” contează.
    """
    if frame.height == 0:
        return frame

    verdicts = []
    for row in frame.select("title", "specific_objective", "domains").to_dicts():
        domains = " ".join(row.get("domains") or [])
        context = f"{row['specific_objective'] or ''} {domains}"
        verdicts.append(score_row(row["title"], context, None, None))
    return frame.with_columns(
        pl.Series("software_score", [v.score for v in verdicts], dtype=pl.Float64),
        pl.Series("software_label", [v.label for v in verdicts], dtype=pl.Utf8),
        pl.Series("software_evidence", [v.evidence for v in verdicts], dtype=pl.Utf8),
    ).with_columns((pl.col("software_score") >= THRESHOLD).alias("is_software"))
