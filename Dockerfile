# syntax=docker/dockerfile:1

# Slim Python base. psycopg[binary] bundles libpq, so no compiler or apt build
# dependencies are needed in the image (keeps it small and the surface narrow).
FROM python:3.12-slim

# uv for reproducible, lockfile-pinned installs. Pinned to a specific version so
# image builds are deterministic (dependency versions come from uv.lock + --frozen).
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer, cached on the lockfile alone (re-used until deps change):
#   --frozen             fail if uv.lock is out of date (no silent drift)
#   --no-dev             skip the dev group (pytest, bandit) — not needed to serve
#   --no-install-project deps only; the app runs from source (no build backend)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code last, since it changes most often.
COPY app ./app

# Run as an unprivileged user (container hardening; research §12).
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Put the venv's executables on PATH.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# `python -m` puts the working directory on sys.path so the `app` package
# (run from source, not installed) is importable. Startup creates tables and
# idempotently seeds the default categories (app.main), then serves the API.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
