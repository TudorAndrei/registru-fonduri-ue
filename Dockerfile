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
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=10 \
    CMD curl -fsS http://localhost:3000/ >/dev/null || exit 1
# În modul `prod`, Reflex servește interfața și partea de server pe același
# port — altfel refuză să pornească. Un singur port simplifică și Coolify.
# Interfața se compilează la prima pornire; de aceea `start-period` este lung.
CMD ["reflex", "run", "--env", "prod", "--frontend-port", "3000", "--backend-port", "3000"]
