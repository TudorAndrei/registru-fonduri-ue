# Imagine unică pentru ambele servicii: tabloul de bord și programatorul.
# Diferența o face comanda, nu imaginea — altfel cele două ar putea ajunge pe
# versiuni de cod diferite fără să bage nimeni de seamă.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    REGISTRU_DATA_DIR=/data

# `unzip` și `curl` sunt pentru Reflex, care își aduce singur bun-ul la prima
# compilare a interfeței.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Întâi dependențele, ca stratul lor să rămână în cache când se schimbă codul.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra dashboard

COPY . .
RUN uv sync --frozen --extra dashboard

# `/data` este volumul persistent: fișierele descărcate, registrul și jurnalul
# rulărilor. Fără el, fiecare redesfășurare ar reporni de la zero.
VOLUME ["/data"]

# ---------------------------------------------------------------- programator

FROM base AS scheduler
# O rulare pe lună, ziua 1 la 03:00 UTC. Se schimbă cu REGISTRU_CRON.
ENV REGISTRU_CRON="0 3 1 * *"
CMD ["registru", "schedule"]

# -------------------------------------------------------------- tablou de bord

FROM base AS dashboard
ENV REFLEX_ENV_MODE=prod
EXPOSE 3000
# Marjă largă dinadins. Schedulerul rulează pe aceeași mașină și îi ia
# procesorul cu citit PDF-uri și cu modelul de clasificare, iar un răspuns
# lent nu înseamnă aplicație moartă — înseamnă mașină ocupată. Cu cinci
# secunde, containerul era declarat bolnav degeaba, iar proxy-ul nu mai
# ruta spre el: de acolo veneau 503-urile.
HEALTHCHECK --interval=30s --timeout=20s --start-period=300s --retries=10 \
    CMD curl -fsS -o /dev/null --max-time 18 http://127.0.0.1:3000/ || exit 1
# În modul `prod`, Reflex servește interfața și partea de server pe același
# port — altfel refuză să pornească. Un singur port simplifică și Coolify.
# Interfața se compilează la prima pornire; de aceea `start-period` este lung.
CMD ["reflex", "run", "--env", "prod", "--frontend-port", "3000", "--backend-port", "3000"]
