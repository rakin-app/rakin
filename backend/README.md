# Rakin API

FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2. ORM models live in `app/models`, API schemas in `app/schemas`, and the two are never mixed.

```sh
cd backend
uv sync                                    # install deps into .venv
uv run uvicorn --factory app.main:create_app --reload
curl -i localhost:8000/healthz             # 200 when Postgres answers, 503 otherwise
```

Settings come from environment variables, or from the repo-root `.env` (copy `../.env.example`). Every variable is listed there with a working local default.

Logs are one JSON object per line on stdout. Each request gets an `X-Request-ID` (the caller's, if it is safe to log, otherwise a fresh one), returned in the response header and attached to every log line written while the request runs.

## Checks

```sh
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest
TEST_DATABASE_URL=postgresql+asyncpg://rakin:rakin@localhost:5432/rakin uv run pytest -m postgres
```

Tests marked `postgres` skip unless `TEST_DATABASE_URL` points at a reachable database. With `REQUIRE_POSTGRES=1` (as in CI) a missing `TEST_DATABASE_URL` fails them instead.

## Migrations

```sh
uv run alembic revision -m "describe the change"
uv run alembic upgrade head
```

Alembic connects with `MIGRATION_DATABASE_URL`, the role that owns the tables. The API connects with `DATABASE_URL`, a login user in the `rakin_app` role that migration 0001 creates. `rakin_app` owns nothing and has no `BYPASSRLS`, so row-level security always applies to the API. After the first migration, create the login user once:

```sh
psql -U rakin -d rakin -c "CREATE ROLE rakin_api LOGIN PASSWORD 'rakin_api' IN ROLE rakin_app"
```

Every table with a `gym_id` (and `gym` itself) is isolated by an RLS policy on `current_setting('app.gym_id')`. With `app.gym_id` unset, those tables return no rows. `person` and `job_run` are global.

The migration tests create and drop a throwaway database on the `TEST_DATABASE_URL` server, so that user needs `CREATEDB`.
