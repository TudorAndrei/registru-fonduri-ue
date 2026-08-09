# Registru fonduri UE — România

Centralizator deschis al proiectelor cu finanțare europeană în România, cu accent pe proiectele de tip **software / digitalizare / IT**.

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
uv run registru fetch datagovro --limit 6     # descarcă fișierele brute
uv run registru extract                       # le aduce la schema canonică
uv run registru build                         # deduplică, clasifică, scrie registrul
uv run registru stats                         # sinteza
uv run registru query "SELECT * FROM software LIMIT 10"
uv run registru export software.csv --software
```

Tabloul de bord:

```bash
uv run reflex run          # http://localhost:3000
```

## Sursele

| Adaptor | Sursă | Ce aduce | Licență |
| --- | --- | --- | --- |
| `datagovro` | [data.gov.ro](https://data.gov.ro/dataset/proiecte-contractate), API CKAN | Liste proiecte contractate 2014-2020 (POIM, POC, POCU, POR, POCA, POAT), trimestrial | OGL-ROU-1.0 |
| `kohesio` | [Kohesio](https://kohesio.ec.europa.eu/), API REST | Descrieri și coordonate geografice, toate statele | CC BY 4.0 |

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
