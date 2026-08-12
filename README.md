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

În Coolify: **New Resource → Public Repository**, apoi la **Build Pack** alege **Docker Compose**. Implicit este Nixpacks, care ar ghici o singură aplicație Python și ar porni-o pe ea — aici sunt două servicii care împart un volum. Restul câmpurilor rămân cum sunt: ramura `main`, „Base Directory” `/`, „Docker Compose Location” `/docker-compose.yaml` — fișierul poartă extensia `.yaml` tocmai ca să se potrivească cu ce completează Coolify singur. Câmpul de port dispare odată cu schimbarea: porturile vin din fișier.

**`docker-compose.yaml` ține aproape toată configurația** — serviciile, volumul, portul, variabilele de mediu. Coolify le citește din el; volumele apar în interfață marcate „read-only”.

**Domeniul este singura excepție, și îl deține interfața.** Un FQDN fixat cu valoare în compose nu ține: Coolify îl reconciliază spre gol la următoarea desfășurare, adică șterge exact domeniul pe care voiai să-l fixezi. `SERVICE_FQDN_DASHBOARD_3000` se declară deci fără valoare — îi spune doar ce port să lege — iar domeniul dorit se pune o dată, din interfață.

Tot acolo se pune și `REGISTRU_API_URL`, cu aceeași adresă publică și fără port: Reflex are nevoie de ea ca interfața din browser să știe unde e partea de server.

Domeniul stă în `SERVICE_FQDN_DASHBOARD_3000`, cu portul din container în chiar numele variabilei. Pentru altă instalare se schimbă cu variabila de mediu `REGISTRU_DOMENIU`, fără să se atingă nimeni de fișier. Acele variabile se **declară fără valoare** — atunci le generează Coolify și, pentru FQDN, configurează și rutarea. `API_URL`, de care are nevoie Reflex ca interfața să știe unde e partea de server, se construiește din același domeniu — nu din `SERVICE_URL_`, care e generat de Coolify și nu e limpede dacă mai apare când FQDN-ul e fixat cu o valoare. Se poate suprascrie direct cu `REGISTRU_API_URL`.

În modul `prod`, Reflex servește interfața și partea de server pe același port, deci este un singur domeniu de configurat.

Variabile de mediu:

| Variabilă | Implicit | Ce face |
| --- | --- | --- |
| `REGISTRU_CRON` | `0 3 1 * *` | Când rulează pipeline-ul. Ziua 1 a lunii, 03:00 UTC. |
| `REGISTRU_DATA_DIR` | `/data` | Unde stau datele. Trebuie să fie volum persistent. |
| `REGISTRU_DETALII_APEL` | `6000` | Câte fișe de apel se descarcă la o rulare. |
| `REGISTRU_FIRE` | `6` | Câte descărcări în paralel. Mic dinadins. |
| `REGISTRU_PROXY` | — | Pe unde ies cererile. Vezi mai jos. |

Prima pornire, ca să nu pară blocată: containerul `scheduler` vede volumul gol și rulează imediat, în loc să aștepte până la 1 ale lunii ca să afli dacă merge. Durează 45-60 de minute — descărcarea celor 5.233 de fișe de apel, arhiva, și parsarea PDF-urilor. Rulările următoare iau doar ce s-a schimbat, fiindcă parsarea se memorează pe amprenta fișierului. În paralel, `dashboard` își compilează interfața la prima pornire, de unde `start_period` de 300 de secunde în healthcheck; până termină schedulerul, va arăta gol.

Volumul are nevoie de câțiva GB: datele brute ajung la ~350 MB, iar modelul de clasificare mai descarcă 0,22 GB la prima rulare.

Fără Coolify:

```bash
docker compose up -d --build
docker compose exec scheduler registru runs
```

## De ce lunar

Listele naționale de proiecte se publică trimestrial. Apelurile se schimbă mai des, dar un termen de depunere se anunță cu săptămâni înainte, deci o rulare pe lună nu ratează nimic. Dacă vrei mai des, `REGISTRU_CRON="0 3 * * 1"` face o rulare în fiecare luni.

Jurnalul rulărilor stă în `data/runs/`. Fiecare rulare notează ce a adus, cât a durat și ce a eșuat — o rulare care nu aduce nimic nou și una care crapă arată la fel din afară, dacă nimeni nu notează diferența.


## Când sursele resping serverul

Verificat în august 2026, de pe un server Hetzner: `mfe.gov.ro` și
`oportunitati-ue.gov.ro` lasă conexiunea să expire după 120 de secunde, iar
Kohesio răspunde 403. De pe o rețea obișnuită, toate trei răspund 200 în
jumătate de secundă. `data.gov.ro` și arhiva Wayback merg de oriunde.

Un timp de așteptare depășit înseamnă că pachetele sunt aruncate înainte de
orice dialog, deci nu are ce repara clientul: nici antetele, nici amprenta TLS
nu apucă să conteze. Este filtrare după adresă.

`REGISTRU_PROXY` spune pe unde să iasă cererile:

```bash
REGISTRU_PROXY=http://ieșirea-mea:3128
```

**Alege o ieșire pe care o controlezi** — un tunel către rețeaua ta, sau o
mașină a ta. Nu un proxy public: acela vede și poate rescrie răspunsul, iar
amprenta SHA-256 pe care o păstrăm ar certifica atunci ce a livrat proxy-ul, nu
ce a publicat autoritatea. Proveniența este singurul lucru care face registrul
verificabil, și nu merită dat pe comoditate.

Alternativa fără proxy: colectarea rulează unde nu este blocată — pe calculatorul
tău, sau într-un job de GitHub Actions — iar pe server ajung doar cele două
fișiere Parquet.
