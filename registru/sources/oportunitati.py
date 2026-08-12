"""Adaptor pentru oportunitati-ue.gov.ro — apelurile de finanțare deschise.

Un apel nu este un proiect: este o oportunitate, nu un contract semnat. Merge
într-o tabelă separată. Restul registrului spune cine a luat bani; apelurile
spun de unde se mai pot lua.

Site-ul este WordPress cu API REST public. Un WAF respinge clienții fără
antete de browser, deci se trimit antete normale de navigator și un
`User-Agent` care spune cine suntem. `robots.txt` nu este servit, dar apelurile
sunt informație publică, iar ritmul este de o rulare pe lună.

Ce dă API-ul: identitate, titlu, link, taxonomii, data ultimei modificări.
Ce nu dă: bugetul și calendarul, care stau în câmpuri ACF neexpuse. Acelea se
citesc din pagina apelului, și numai pentru apelurile noi sau modificate.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from html import unescape
from pathlib import Path

import polars as pl

from registru.config import RAW_DIR
from registru.schema import conform_calls, empty_calls
from registru.sources.base import (
    Client,
    FetchedFile,
    http_client,
    now_iso,
    read_manifest,
    sha256_file,
    write_manifest,
)

BASE = "https://oportunitati-ue.gov.ro"
API = f"{BASE}/wp-json/wp/v2"
PER_PAGE = 100

#: Taxonomiile atașate unui apel, cu numele câmpului din răspuns.
TAXONOMIES = {
    "beneficiar": "beneficiaries",
    "domeniu": "domains",
    "tip_apel": "call_types",
    "zona_geografica": "geo_areas",
}

MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


def browser_client() -> Client:
    """WAF-ul respinge cererile fără antete de navigator, inclusiv pe robots.txt."""
    return http_client({"Referer": f"{BASE}/apeluri/"})


class Oportunitati:
    id = "oportunitati"
    name = "oportunitati-ue.gov.ro (apeluri)"
    kind = "call"

    #: Câte pagini de apel se citesc pentru buget și calendar la o rulare.
    #: Bugetul și termenul limită sunt tot ce contează pentru cineva care caută
    #: finanțare, iar ele stau doar în pagină, deci merită descărcate toate.
    #: Prima rulare durează; următoarele iau doar ce s-a schimbat.
    detail_budget = int(os.environ.get("REGISTRU_DETALII_APEL", "6000"))

    #: Câte fișe se descarcă în paralel. Mic dinadins: este un site public al
    #: administrației, nu o țintă de test de sarcină.
    workers = int(os.environ.get("REGISTRU_FIRE", "6"))

    # ------------------------------------------------------------------ fetch

    def fetch(self, *, limit: int | None = None) -> list[FetchedFile]:
        fetched: list[FetchedFile] = []
        with browser_client() as client:
            fetched.extend(self._fetch_terms(client))
            calls = self._fetch_calls(client, limit)
            fetched.extend(calls)
            fetched.extend(self._fetch_details(client, calls, limit))
        write_manifest(self.id, fetched)
        return fetched

    def _fetch_terms(self, client: Client) -> list[FetchedFile]:
        """Taxonomiile vin ca liste de identificatori; aici se aduc numele."""
        out: list[FetchedFile] = []
        for taxonomy in TAXONOMIES:
            terms: list[dict] = []
            for page in range(1, 21):
                response = client.get(
                    f"{API}/{taxonomy}", params={"per_page": PER_PAGE, "page": page}
                )
                if response.status_code != 200:
                    break
                batch = response.json()
                terms.extend(batch)
                if len(batch) < PER_PAGE:
                    break
            out.append(self._save(f"terms/{taxonomy}.json", terms, str(response.url)))
        return out

    def _fetch_calls(self, client: Client, limit: int | None) -> list[FetchedFile]:
        out: list[FetchedFile] = []
        max_pages = limit if limit is not None else 100
        for page in range(1, max_pages + 1):
            response = client.get(
                f"{API}/apel",
                params={
                    "per_page": PER_PAGE,
                    "page": page,
                    "orderby": "modified",
                    "order": "desc",
                    "_fields": "id,slug,link,title,date,modified," + ",".join(TAXONOMIES),
                },
            )
            if response.status_code != 200:
                break
            batch = response.json()
            if not batch:
                break
            out.append(self._save(f"apel/page-{page:04d}.json", batch, str(response.url)))
            if len(batch) < PER_PAGE:
                break
        return out

    def _fetch_details(
        self, client: Client, calls: list[FetchedFile], limit: int | None
    ) -> list[FetchedFile]:
        """Pagina fiecărui apel, pentru buget și calendar.

        Sunt peste 5.000 de apeluri, deci nu se descarcă tot la fiecare rulare.
        Se ia doar ce lipsește sau ce s-a schimbat de la ultima descărcare, în
        ordinea modificării. Rulările lunare completează arhiva de la sine, iar
        un apel prelungit se reîmprospătează pentru că i-a crescut `modified`.
        """
        budget = self.detail_budget if limit is None else min(self.detail_budget, limit * 20)

        wanted: list[str] = []
        for entry in sorted(calls, key=lambda item: item.path):
            payload = json.loads((RAW_DIR / entry.path).read_text("utf-8"))
            for item in payload:
                slug = item.get("slug")
                if slug and self._detail_is_stale(slug, item.get("modified")):
                    wanted.append(slug)
                if len(wanted) >= budget:
                    break
            if len(wanted) >= budget:
                break

        if not wanted:
            return []
        print(f"  {len(wanted)} fișe de apel de descărcat", flush=True)

        # Secvențial ar dura ore pentru 5.000 de pagini. Câteva fire ajung —
        # nu este nevoie de un cadru de crawling pentru o listă de adrese
        # cunoscute dinainte. Numărul este mic intenționat: un site public al
        # administrației nu trebuie lovit cu zeci de cereri simultane.
        out: list[FetchedFile] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._fetch_one, client, slug): slug for slug in wanted}
            for done, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                if result is not None:
                    out.append(result)
                if done % 250 == 0:
                    print(f"  {done}/{len(wanted)}", flush=True)
        return out

    def _fetch_one(self, client: Client, slug: str) -> FetchedFile | None:
        url = f"{BASE}/apel/{slug}/"
        try:
            response = client.get(url)
        except Exception:  # noqa: BLE001 — o fișă lipsă nu oprește descărcarea
            return None
        if response.status_code != 200:
            return None
        return self._save_text(f"detail/{slug}.html", response.text, url)

    def _detail_is_stale(self, slug: str, modified: str | None) -> bool:
        path = _detail_path(slug)
        if path is None:
            return True
        if not modified:
            return False
        try:
            changed = datetime.fromisoformat(modified)
        except ValueError:
            return False
        return changed.timestamp() > path.stat().st_mtime

    # ------------------------------------------------------------------ disc

    def _save(self, relative: str, payload: object, url: str) -> FetchedFile:
        return self._save_text(relative, json.dumps(payload, ensure_ascii=False), url)

    def _save_text(self, relative: str, text: str, url: str) -> FetchedFile:
        # Fișele sunt pagini WordPress de ~150 KB fiecare, iar sunt peste 5.000:
        # 785 MB necomprimate, sub 100 MB comprimate. Pe un volum de server,
        # diferența contează. Conținutul rămâne neatins — doar învelișul se schimbă.
        path = RAW_DIR / self.id / (relative + ".gz" if relative.endswith(".html") else relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".gz":
            path.write_bytes(gzip.compress(text.encode("utf-8"), compresslevel=6))
        else:
            path.write_text(text, "utf-8")
        return FetchedFile(
            source=self.id,
            dataset="apeluri",
            url=url,
            path=str(path.relative_to(RAW_DIR)),
            sha256=sha256_file(path),
            bytes=path.stat().st_size,
            fetched_at=now_iso(),
        )

    # ---------------------------------------------------------------- extract

    def extract(self) -> pl.DataFrame:
        terms = self._term_names()
        details = self._details()
        rows: list[dict] = []
        for entry in read_manifest(self.id):
            if not entry.path.startswith(f"{self.id}/apel/"):
                continue
            path = RAW_DIR / entry.path
            if not path.exists():
                continue
            for item in json.loads(path.read_text("utf-8")):
                rows.append(_row(item, terms, details.get(item.get("slug", "")), entry))
        if not rows:
            return empty_calls()
        frame = pl.DataFrame(rows, infer_schema_length=None)
        return conform_calls(frame).unique(subset=["call_id"], keep="first")

    def _term_names(self) -> dict[str, dict[int, str]]:
        names: dict[str, dict[int, str]] = {}
        for taxonomy in TAXONOMIES:
            path = RAW_DIR / self.id / "terms" / f"{taxonomy}.json"
            if not path.exists():
                names[taxonomy] = {}
                continue
            names[taxonomy] = {
                term["id"]: unescape(term.get("name") or "")
                for term in json.loads(path.read_text("utf-8"))
            }
        return names

    def _details(self) -> dict[str, dict]:
        folder = RAW_DIR / self.id / "detail"
        if not folder.exists():
            return {}
        out: dict[str, dict] = {}
        for path in sorted(folder.iterdir()):
            if path.suffix == ".gz":
                slug, html = (
                    path.name[: -len(".html.gz")],
                    gzip.decompress(path.read_bytes()).decode("utf-8", "replace"),
                )
            elif path.suffix == ".html":
                slug, html = path.stem, path.read_text("utf-8", errors="replace")
            else:
                continue
            out[slug] = parse_detail(html)
        return out


# ------------------------------------------------------------------ parsare


_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\xa0]+")


def _detail_path(slug: str) -> Path | None:
    """Fișa unui apel, comprimată sau nu. Descărcările vechi rămân valabile."""
    folder = RAW_DIR / "oportunitati" / "detail"
    for name in (f"{slug}.html.gz", f"{slug}.html"):
        candidate = folder / name
        if candidate.exists():
            return candidate
    return None


def _plain(html: str) -> str:
    """Pagina, redusă la text, cu marcatori `|` între elemente."""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    text = _TAG.sub("|", text)
    text = unescape(_SPACE.sub(" ", text))
    return re.sub(r"(\s*\|\s*)+", "|", text)


def _list_after(text: str, label: str, stop: tuple[str, ...], width: int = 1200) -> list[str]:
    """Elementele enumerate după o etichetă, până la următoarea secțiune.

    Fișa apelului listează „Beneficiari eligibili” și „Domenii” separate prin
    virgulă și marcatori de element; API-ul le lasă goale pentru multe apeluri,
    deci pagina este sursa mai bogată.
    """
    index = text.find(label)
    if index < 0:
        return []
    tail = text[index + len(label) : index + len(label) + width]
    for marker in stop:
        cut = tail.find(marker)
        if cut > 0:
            tail = tail[:cut]
    items: list[str] = []
    for chunk in tail.replace("|", ",").split(","):
        value = chunk.strip(" .:;")
        if len(value) > 2 and value.lower() not in {"domenii", "share"}:
            items.append(value)
    return list(dict.fromkeys(items))[:20]


def _after(text: str, label: str, width: int = 260) -> str | None:
    """Valoarea care urmează unei etichete din fișa apelului."""
    index = text.find(label)
    if index < 0:
        return None
    tail = text[index + len(label) : index + len(label) + width]
    parts = [part.strip() for part in tail.split("|") if part.strip()]
    return parts[0] if parts else None


def parse_date_ro(value: str | None) -> date | None:
    """`31 decembrie 2026 23:59` sau `31.12.2026`."""
    if not value:
        return None
    text = value.strip().lower()
    match = re.search(r"(\d{1,2})\s+([a-zăîâșț]+)\s+(\d{4})", text)
    if match and match.group(2) in MONTHS:
        return date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: str | None) -> tuple[float | None, str | None]:
    """`33.435.294 EUR` -> (33435294.0, "EUR")."""
    if not value:
        return None, None
    currency = None
    for symbol in ("EUR", "RON", "LEI"):
        if symbol in value.upper():
            currency = "RON" if symbol == "LEI" else symbol
            break
    digits = re.sub(r"[^0-9,.]", "", value)
    if not digits:
        return None, currency
    if "," in digits and "." in digits:
        digits = digits.replace(".", "").replace(",", ".")
    else:
        digits = digits.replace(".", "")
    try:
        return float(digits), currency
    except ValueError:
        return None, currency


def parse_detail(html: str) -> dict:
    """Bugetul, calendarul și obiectivul, din fișa apelului."""
    text = _plain(html)
    amount, currency = parse_amount(_after(text, "Buget UE:"))
    opens = parse_date_ro(_after(text, "Data deschiderii:"))
    closes = parse_date_ro(_after(text, "Data închiderii:"))
    call_type = _after(text, "Tip Apel:", width=200)
    programs = _after(text, "Programe pentru care se aplică apelul", width=300)
    return {
        "specific_objective": _after(text, "Obiectivul specific:", width=400),
        "call_type": call_type,
        "budget_amount": amount,
        "budget_currency": currency,
        "opens_at": opens,
        "closes_at": closes,
        "continuous": bool(call_type and "fără termen" in call_type.lower()),
        "programs": [programs] if programs else [],
        "beneficiaries": _list_after(
            text, "Beneficiari eligibili", ("Criterii de eligibilitate", "Activități", "Buget")
        ),
        "domains": _list_after(text, "Domenii Apel:", ("Zone Geografice", "Share", "Calendar")),
        "documents": sorted(set(re.findall(r'href="(https?://[^"]+\.pdf)"', html)))[:10],
    }


def call_status(opens: date | None, closes: date | None, continuous: bool, today: date) -> str:
    """Statusul se deduce din calendar, nu se citește dintr-un câmp.

    Site-ul îl ține într-un câmp ACF pe care API-ul nu îl expune, dar datele de
    deschidere și de închidere spun același lucru și nu pot fi în contradicție
    cu ele însele.
    """
    # Termenul trecut bate orice altceva. „Depunere continuă” cu data de
    # închidere în 2024 înseamnă închis, nu continuu — altfel registrul ar
    # recomanda apeluri la care nu se mai poate depune, ceea ce este mai rău
    # decât să nu le arate deloc.
    if closes and closes < today:
        return "Închis"
    if opens and opens > today:
        return "Urmează"
    if closes and closes >= today:
        return "Activ"
    if continuous and (opens is None or opens <= today):
        return "Activ"
    return "Necunoscut"


def _row(item: dict, terms: dict[str, dict[int, str]], detail: dict | None, entry) -> dict:
    detail = detail or {}
    today = date.today()
    opens = detail.get("opens_at")
    closes = detail.get("closes_at")
    continuous = bool(detail.get("continuous"))
    row = {
        "call_id": str(item.get("id")),
        "title": unescape(_TAG.sub("", (item.get("title") or {}).get("rendered") or "")).strip(),
        "url": f"{BASE}/apel/{item.get('slug')}/",
        "external_url": item.get("link"),
        "specific_objective": detail.get("specific_objective"),
        "call_type": detail.get("call_type"),
        "status": call_status(opens, closes, continuous, today),
        "opens_at": opens,
        "closes_at": closes,
        "continuous": continuous,
        "budget_amount": detail.get("budget_amount"),
        "budget_currency": detail.get("budget_currency"),
        "programs": detail.get("programs") or [],
        "documents": detail.get("documents") or [],
        "published_at": item.get("date"),
        "modified_at": item.get("modified"),
        "source": entry.source,
        "source_url": row_url(item),
        "fetched_at": entry.fetched_at,
    }
    for taxonomy, field in TAXONOMIES.items():
        ids = item.get(taxonomy) or []
        names = [terms.get(taxonomy, {}).get(term_id, "") for term_id in ids]
        row[field] = [name for name in names if name]
        # Fișa apelului este mai bogată decât API-ul: multe apeluri au
        # taxonomiile goale acolo, dar listate în pagină.
        if not row[field] and detail.get(field):
            row[field] = detail[field]
    return row


def row_url(item: dict) -> str:
    return f"{BASE}/apel/{item.get('slug')}/"
