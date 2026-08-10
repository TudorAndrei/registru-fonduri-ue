"""Adaptor pentru fonduri-ue.ro, prin arhiva Internet Archive.

Site-ul stă în spatele unui challenge Cloudflare care respinge orice client
automat, inclusiv un browser fără interfață. `robots.txt` permite colectarea
(`User-agent: * / Allow: /`), deci blocajul este tehnic, nu de politică — dar a
construi ocolirea unui sistem anti-bot nu este o soluție.

Arhiva Wayback rezolvă problema fără niciun ocol: are aceleași fișiere, este
publică, nu blochează pe nimeni, și în plus păstrează **instantanee la date
diferite**. Asta dă exact ce nu dă nicio sursă curentă: cum s-a schimbat starea
unui proiect în timp — contractat, în implementare, finalizat, reziliat.

Fișierele sunt PDF-uri de câteva megaocteți și XLSX-uri. PDF-urile sunt cele mai
bogate: publică `Fonduri UE`, coloana pe care listele Excel o lasă goală.

Pentru ce nu este arhivat există `data/raw/fondurieue/manual/`: pui acolo un
fișier descărcat cu browserul tău, și adaptorul îl citește la fel.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path

import httpx
import polars as pl
import wayback

from registru.config import HTTP_TIMEOUT, INTERIM_DIR, RAW_DIR, USER_AGENT
from registru.schema import conform, empty_frame
from registru.sources.base import FetchedFile, now_iso, read_manifest, sha256_file, write_manifest
from registru.tabular import clean_frame, frame_from_rows, read_tabular

DOMAIN = "fonduri-ue.ro"
CDX_API = "https://web.archive.org/cdx/search/cdx"

#: Ce fișiere ne interesează. Arhiva are peste 5.000 de documente, dintre care
#: majoritatea sunt ghiduri, ordine și liste de participanți la dezbateri.
LIST_PATTERN = re.compile(
    r"(lista[_ -]?(proiectelor|contracte|contractate|beneficiar)"
    r"|proiecte[_ -]?contractate"
    r"|contracte[_ -]?semnate"
    r"|contractate[_ -]?semnate[_ -]?finalizate)",
    re.IGNORECASE,
)

#: Ce nu este o listă de proiecte, deși are „lista” în nume.
EXCLUDE_PATTERN = re.compile(
    r"(documente[_ .-]de[_ .-]interes|categorii[_ .-]documente|inscrieri|dezbatere"
    r"|selectie|contestatii|indicativa|respins|neeligibil|retras)",
    re.IGNORECASE,
)

DOCUMENT_SUFFIXES = (".pdf", ".xlsx", ".xls")

#: Plafon de pagini per PDF. Peste el, citirea devine mai scumpă decât valoarea
#: rândurilor în plus, iar rularea lunară trebuie să se termine.
MAX_PDF_PAGES = int(os.environ.get("REGISTRU_PAGINI_PDF", "150"))

PROGRAM_PATTERN = re.compile(
    r"\b(poim|pocu|poca|poat|poad|por|poc|pcidif|pocidif|regio|podca)\b", re.IGNORECASE
)


def _program(name: str) -> str | None:
    match = PROGRAM_PATTERN.search(name)
    return match.group(1).upper() if match else None


def _snapshot_date(url: str) -> str | None:
    """Data instantaneului, din adresa Wayback: `/web/20240515125245id_/...`."""
    match = re.search(r"/web/(\d{8})", url)
    if not match:
        return None
    stamp = match.group(1)
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"


class FonduriUe:
    id = "fondurieue"
    kind = "project"
    name = "fonduri-ue.ro (prin arhiva Wayback)"

    #: Fișierele sunt de câțiva MB. Fără plafon, prima rulare ar aduce gigaocteți.
    budget = int(os.environ.get("REGISTRU_FISIERE_ARHIVA", "60"))

    # ------------------------------------------------------------------ fetch

    def fetch(self, *, limit: int | None = None) -> list[FetchedFile]:
        budget = min(self.budget, limit) if limit is not None else self.budget
        client = wayback.WaybackClient()
        fetched: list[FetchedFile] = []
        seen: set[str] = set()

        for stamp, original in self._discover():
            if len(fetched) >= budget:
                break
            name = Path(urllib.parse.unquote(original).split("?")[0]).name
            relative = Path(self.id) / stamp[:4] / f"{stamp}-{name}"
            if str(relative) in seen:
                continue
            seen.add(str(relative))
            target = RAW_DIR / relative
            if not target.exists():
                try:
                    memento = client.get_memento(
                        f"https://web.archive.org/web/{stamp}id_/{original}",
                        mode=wayback.Mode.original,
                    )
                    payload = memento.content
                except Exception as error:  # noqa: BLE001 — un instantaneu lipsă nu oprește restul
                    print(f"  ! {name}: {type(error).__name__}: {error}")
                    continue
                if not payload or len(payload) < 4096:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            fetched.append(
                FetchedFile(
                    source=self.id,
                    dataset=_program(original) or "necunoscut",
                    url=f"https://web.archive.org/web/{stamp}/{original}",
                    path=str(relative),
                    sha256=sha256_file(target),
                    bytes=target.stat().st_size,
                    fetched_at=now_iso(),
                    meta={
                        "original_url": original,
                        "snapshot": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}",
                    },
                )
            )
            print(f"  {len(fetched)}/{budget} {name[:70]}", flush=True)

        write_manifest(self.id, fetched)
        return fetched

    def _discover(self) -> list[tuple[str, str]]:
        """Instantaneele de liste de proiecte, cele mai noi întâi.

        Descoperirea se face cu un singur apel la API-ul CDX, nu prin
        `WaybackClient.search`: acesta paginează, iar domeniul are peste 20.000
        de instantanee, ceea ce ia zece minute. Biblioteca rămâne pentru
        descărcarea propriu-zisă, unde se ocupă de redirectări și de reîncercări.
        """
        response = httpx.get(
            CDX_API,
            params={
                "url": f"{DOMAIN}/*",
                "output": "json",
                "fl": "timestamp,original",
                "filter": "statuscode:200",
                "collapse": "urlkey",
                "limit": "60000",
            },
            timeout=HTTP_TIMEOUT * 3,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        rows = response.json()[1:]

        found: list[tuple[str, str]] = []
        for timestamp, original in rows:
            url = urllib.parse.unquote(original).split("?")[0]
            if not url.lower().endswith(DOCUMENT_SUFFIXES):
                continue
            name = Path(url).name
            if not LIST_PATTERN.search(name) or EXCLUDE_PATTERN.search(name):
                continue
            found.append((timestamp, original))
        found.sort(reverse=True)
        print(f"  {len(found)} liste găsite în arhivă", flush=True)
        return found

    # ---------------------------------------------------------------- extract

    def extract(self) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        entries = list(read_manifest(self.id)) + list(self._manual())
        for entry in entries:
            path = RAW_DIR / entry.path
            if not path.exists():
                continue
            try:
                frame = self._extract_file(entry, path)
            except Exception as error:  # noqa: BLE001 — un fișier stricat nu oprește restul
                print(f"  ! {entry.path}: {type(error).__name__}: {error}")
                continue
            if frame is not None and frame.height:
                frames.append(frame)
        if not frames:
            return empty_frame()
        return pl.concat(frames, how="vertical_relaxed")

    def _parsed(self, entry: FetchedFile, path: Path) -> pl.DataFrame | None:
        """Rândurile brute ale unui fișier, memorate pe amprenta lui.

        Un PDF de 38 de pagini ia zeci de secunde cu `pdfplumber`, iar rularea
        lunară l-ar reciti de fiecare dată degeaba: fișierele descărcate nu se
        schimbă niciodată. Cheia este SHA-256, deci un fișier nou reparsează,
        unul vechi nu.
        """
        cache = INTERIM_DIR / "cache" / f"{entry.sha256[:16]}.parquet"
        if cache.exists():
            return pl.read_parquet(cache)
        raw = read_pdf(path) if path.suffix.lower() == ".pdf" else read_tabular(path)
        if raw is not None and raw.height:
            cache.parent.mkdir(parents=True, exist_ok=True)
            raw.write_parquet(cache)
        return raw

    def _manual(self):
        """Fișierele puse de mână, pentru ce nu este în arhivă."""
        folder = RAW_DIR / self.id / "manual"
        if not folder.exists():
            return
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in DOCUMENT_SUFFIXES:
                continue
            yield FetchedFile(
                source=self.id,
                dataset=_program(path.name) or "necunoscut",
                url=f"manual:{path.name}",
                path=str(path.relative_to(RAW_DIR)),
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
                fetched_at=now_iso(),
                meta={"manual": True},
            )

    def _extract_file(self, entry: FetchedFile, path: Path) -> pl.DataFrame | None:
        raw = self._parsed(entry, path)
        if raw is None or raw.height == 0:
            return None

        from registru.headers import map_columns

        mapping = map_columns(raw.columns)
        if "beneficiary_name" not in mapping.values():
            return None

        frame = raw.rename(mapping).select(list(mapping.values()))
        frame = frame.with_row_index("source_row").with_columns(
            pl.col("source_row").cast(pl.Int64),
            pl.lit(self.id).alias("source"),
            pl.lit(entry.dataset).alias("source_dataset"),
            pl.lit(entry.url).alias("source_url"),
            pl.lit(entry.path).alias("source_file"),
            pl.lit(entry.sha256).alias("source_sha256"),
            # Data instantaneului, nu data descărcării: deduplicarea trebuie să
            # păstreze cea mai recentă publicare a unui proiect, nu ultima
            # descărcare, altfel o listă din 2018 ar putea bate una din 2025.
            pl.lit(entry.meta.get("snapshot") or entry.fetched_at).alias("fetched_at"),
            pl.lit("RO").alias("country"),
            pl.lit("RON").alias("currency"),
            pl.lit("2014-2020").alias("programming_period"),
        )
        # Numele fișierului spune rar programul; calea originală îl spune
        # aproape întotdeauna: /images/files/programe/POIM/2024/...
        program = entry.dataset
        if program == "necunoscut":
            program = _program(entry.meta.get("original_url") or "") or _program(entry.path)
        if program and "program" not in frame.columns:
            frame = frame.with_columns(pl.lit(program).alias("program"))
        return conform(clean_frame(frame))


# ---------------------------------------------------------------------- PDF


def read_pdf(path: Path, max_pages: int = MAX_PDF_PAGES) -> pl.DataFrame | None:
    """Tabelul dintr-un PDF, adunat din toate paginile.

    Antetul apare o singură dată, de obicei pe a doua pagină, pentru că prima
    poartă bannerul. Se caută în primele pagini, apoi restul paginilor sunt
    tratate ca rânduri de date.

    `pdfplumber` face analiză de aspect pentru fiecare pagină, deci un PDF de
    câteva sute de pagini ia minute. De aceea există un plafon — și de aceea
    plafonul anunță când taie: o listă trunchiată în tăcere arată exact ca una
    completă.
    """
    import pdfplumber

    header: list[str] | None = None
    rows: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages) > max_pages:
            print(
                f"  ! {path.name}: {len(pdf.pages)} pagini, se citesc primele {max_pages}",
                flush=True,
            )
        for page in pdf.pages[:max_pages]:
            for table in page.extract_tables():
                if not table:
                    continue
                if header is None:
                    frame = frame_from_rows([[_text(c) for c in row] for row in table])
                    if frame is not None:
                        header = list(frame.columns)
                        rows.extend([list(row) for row in frame.iter_rows()])
                    continue
                for row in table:
                    values = [_text(cell) for cell in row]
                    if any(values):
                        rows.append(values[: len(header)] + [""] * max(0, len(header) - len(row)))
    if not header or not rows:
        return None
    width = len(header)
    data: dict[str, list[str]] = {name: [] for name in header}
    for row in rows:
        padded = list(row[:width]) + [""] * max(0, width - len(row))
        for name, value in zip(header, padded, strict=True):
            data[name].append(value)
    return pl.DataFrame(data)


def _text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())
