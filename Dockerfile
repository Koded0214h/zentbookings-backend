# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# uv for fast, locked installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# --- deps layer (cached unless lockfile/pyproject change) ---
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- app ---
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Run migrations, then serve. PORT overridable by the platform.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips '*'"]
