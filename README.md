# Registru fonduri UE — România

**Ce finanțări europene mai poți lua în România**, și cine le-a luat până acum. Accent pe software, digitalizare și IT.

Două registre, construite din același pipeline:

- **Apeluri deschise** (`/`) — ce se mai poate depune, cu termen, buget și cine este eligibil. Sursa: oportunitati-ue.gov.ro.
- **Proiecte finanțate** (`/proiecte`) — cine a luat bani și pentru ce. Util ca să vezi ce trece la evaluare. Sursele: data.gov.ro și Kohesio.

Datele sunt publice, dar fragmentate: fiecare Autoritate de Management publică propria listă, în propriul format, pe propriul site. Depozitul acesta le adună, le aduce la o schemă comună, le clasifică și le face interogabile — cu SQL, cu CSV, sau cu un tablou de bord.

## Ce răspunde

- Ce firme de software au luat finanțare europeană și pentru ce?
- Cât s-a alocat pe digitalizare, pe program, pe județ, pe an?
- Cine sunt beneficiarii repetitivi?

## Instalare

```bash
uv sync --extra dashboard
```

## Folosire

```bash
uv run registru sources                       # ce adaptoare există
uv run registru fetch                          # descarcă fișierele brute
uv run registru extract                        # le aduce la schema canonică
uv run registru build                          # deduplică, clasifică, scrie registrele
uv run registru calls                          # apelurile deschise acum
uv run registru stats                          # sinteza proiectelor
uv run registru query "SELECT * FROM apeluri_active ORDER BY closes_at"
uv run registru export software.csv --software
```

Rulare periodică, cu jurnal:

```bash
uv run registru schedule --once     # o rulare completă acum
uv run registru schedule            # buclă: lunar, ziua 1 la 03:00 UTC
uv run registru runs                # jurnalul rulărilor
```

Tabloul de bord:

```bash
uv run reflex run          # http://localhost:3000
```

## Sursele

| Adaptor | Sursă | Ce aduce | Licență |
| --- | --- | --- | --- |
| `oportunitati` | [oportunitati-ue.gov.ro](https://oportunitati-ue.gov.ro/apeluri/), API WordPress | **Apelurile de finanțare**, cu termen, buget și eligibilitate | date publice |
| `datagovro` | [data.gov.ro](https://data.gov.ro/dataset/proiecte-contractate), API CKAN | Liste proiecte contractate 2014-2020 (POIM, POC, POCU, POR, POCA, POAT), trimestrial | OGL-ROU-1.0 |
| `kohesio` | [Kohesio](https://kohesio.ec.europa.eu/), API REST | Descrieri și coordonate geografice, toate statele | CC BY 4.0 |
| `fondurieue` | [fonduri-ue.ro](https://www.fonduri-ue.ro/), prin [arhiva Wayback](https://web.archive.org/) | Liste istorice POIM/POCU/POC, în PDF și XLSX, cu **contribuția UE** | date publice |

Note de acces, verificate în august 2026:

- **Kohesio**: parametrul este `countryCode`; `country=RO` întoarce HTTP 400.
- **oportunitati-ue.gov.ro**: un WAF respinge clienții fără antete de navigator, inclusiv pe `robots.txt`. Cu antete normale, API-ul REST răspunde. Bugetul și calendarul stau în câmpuri ACF neexpuse prin API, deci se citesc din pagina fiecărui apel — o dată, apoi doar ce s-a schimbat.
- **fonduri-ue.ro**: `robots.txt` permite colectarea (`User-agent: * / Allow: /`), dar un challenge Cloudflare blochează orice client automat, inclusiv un browser fără interfață. Adaptorul citește deci din **arhiva Internet Archive**, care are aceleași fișiere, nu blochează pe nimeni, și în plus păstrează instantanee la date diferite. Descoperirea se face cu un apel la API-ul CDX; descărcarea, cu biblioteca [`wayback`](https://pypi.org/project/wayback/). Ce nu este arhivat se poate pune de mână în `data/raw/fondurieue/manual/`.

  PDF-urile de acolo publică `Fonduri UE`, coloana pe care fișierele Excel o lasă goală: acoperirea contribuției UE a urcat de la 15 rânduri la 2.621.

Următorul adaptor de scris este cel pentru listele operațiunilor 2021-2027, publicate pe site-urile Autorităților de Management. Acolo este efortul real și, în același timp, valoarea.

Notă de API: la Kohesio parametrul este `countryCode`. `country=RO` întoarce HTTP 400.

## Schema

Câmpurile de bază nu sunt inventate. Sunt cele impuse de **articolul 49 alineatele (3)-(5) din [Regulamentul (UE) 2021/1060](https://eur-lex.europa.eu/eli/reg/2021/1060/oj?locale=ro)**, pe care fiecare Autoritate de Management este obligată să le publice, într-un format care poate fi citit automat, cel puțin o dată la patru luni. Vezi `registru/schema.py`.

Peste ele se adaugă câmpurile de proveniență și cele derivate de clasificator.

## Cum se identifică proiectele „de tip software”

Un singur criteriu nu ajunge. Se combină trei semnale, cu ponderi (`registru/pipeline/classify.py`):

1. **Codul de intervenție** din anexa I la regulament — digitalizare și TIC.
2. **Codul CAEN al beneficiarului** — 62xx, 63xx, 58xx.
3. **Textul** titlului și al descrierii — potrivire de cuvinte-cheie, deocamdată.

Al treilea semnal rezolvă cazul frecvent în care o fabrică de mobilă implementează un ERP: CAEN-ul spune „mobilă”, dar proiectul este software. Fiecare rând păstrează motivul scorului, în `software_evidence`.

## Arhitectura

```
data/raw/        fișiere descărcate, byte-cu-byte cum au venit — dovada
data/interim/    rânduri extrase, o schemă comună, un Parquet per sursă
data/registry/   registru.parquet + registru.duckdb
```

Reguli care nu se încalcă:

- **Un adaptor per sursă, prost și explicit.** Fiecare AM își schimbă coloanele; adaptorul deține acea urâțenie.
- **Nimic descărcat nu se rescrie.** Un fișier brut este dovadă, nu cache.
- **Proveniență la nivel de rând.** Fiecare rând știe din ce fișier, de la ce URL, cu ce amprentă SHA-256 și de la ce dată vine. Fără asta, registrul nu poate fi nici contestat, nici apărat.
- **Export integral, gratuit, fără cont.** Altfel devine încă un portal închis, adică exact problema.

## Verificări

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

## Licență

MIT pentru cod. Datele rămân sub licența sursei lor.


## Desfășurare pe Coolify

Două servicii, aceeași imagine, același volum. Comanda le diferențiază, nu imaginea — altfel ar putea ajunge pe versiuni de cod diferite fără să bage nimeni de seamă.

```
scheduler   -> registru schedule      aduce datele, reconstruiește registrele
dashboard   -> reflex run --env prod  servește interfața, nu scrie nimic
volum       -> /data                  fișiere descărcate, registre, jurnal
```

În Coolify: **New Resource → Docker Compose**, indică depozitul. Domeniul se pune pe serviciul `dashboard`, portul **3000**. În modul `prod`, Reflex servește interfața și partea de server pe același port, deci este un singur domeniu de configurat.

Variabile de mediu:

| Variabilă | Implicit | Ce face |
| --- | --- | --- |
| `REGISTRU_CRON` | `0 3 1 * *` | Când rulează pipeline-ul. Ziua 1 a lunii, 03:00 UTC. |
| `REGISTRU_DATA_DIR` | `/data` | Unde stau datele. Trebuie să fie volum persistent. |
| `REGISTRU_DETALII_APEL` | `6000` | Câte fișe de apel se descarcă la o rulare. |
| `REGISTRU_FIRE` | `6` | Câte descărcări în paralel. Mic dinadins. |

Prima pornire: containerul `scheduler` vede că nu există registru și rulează imediat, ca să nu aștepți până la 1 ale lunii ca să afli dacă merge. Prima rulare durează ~15 minute, aproape tot în descărcarea fișelor de apel; următoarele iau doar ce s-a schimbat.

Fără Coolify:

```bash
docker compose up -d --build
docker compose exec scheduler registru runs
```

## De ce lunar

Listele naționale de proiecte se publică trimestrial. Apelurile se schimbă mai des, dar un termen de depunere se anunță cu săptămâni înainte, deci o rulare pe lună nu ratează nimic. Dacă vrei mai des, `REGISTRU_CRON="0 3 * * 1"` face o rulare în fiecare luni.

Jurnalul rulărilor stă în `data/runs/`. Fiecare rulare notează ce a adus, cât a durat și ce a eșuat — o rulare care nu aduce nimic nou și una care crapă arată la fel din afară, dacă nimeni nu notează diferența.
