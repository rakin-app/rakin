# One image for `api`, `jobs` and the one-shot `migrate` container.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv

# The venv lives outside /srv so the dev bind mount of ./backend never hides it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# For `app.backup` and deploy/restore.sh: pg_dump at the hosted Postgres's major
# version (deploy/docker-compose.yml), and age to encrypt and decrypt the dumps.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 age \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

EXPOSE 8000
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
