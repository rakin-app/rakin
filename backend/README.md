# Rakin API

FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2. ORM models live in `app/models`, API schemas in `app/schemas`, and the two are never mixed.

The membership and ledger-entry state machines live in `app/domain` as pure functions with no I/O; `tests/domain` is their contract, and the ORM models build on them ([spec](../docs/technical.md#core-state-machines)).

```sh
cd backend
uv sync                                    # install deps into .venv
uv run python -m app.db_bootstrap postgresql://rakin:rakin@localhost:5432/rakin   # once; see Database roles
uv run alembic upgrade head
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
(cd .. && docker compose --profile selfhost run --rm garage-init)   # Garage on :3900
TEST_S3_ENDPOINT_URL=http://localhost:3900 uv run pytest -m s3
```

Tests marked `postgres` skip unless `TEST_DATABASE_URL` points at a reachable database. With `REQUIRE_POSTGRES=1` (as in CI) a missing `TEST_DATABASE_URL` fails them instead. Tests marked `s3` do the same with `TEST_S3_ENDPOINT_URL` and `REQUIRE_S3`; they use the `S3_*` access key and bucket defaults, which `garage-init` creates.

## Integrations

Every external service sits behind an interface in `app/integrations`, and a setting picks the implementation. The defaults need no network and no account, so a self-hosted instance works offline with none configured ([spec](../docs/technical.md#architecture)).

| Interface | Setting | Implementations (default first) |
| --- | --- | --- |
| `Mailer` | `MAILER` | `console`: logs each message, sends nothing · `smtp`: any SMTP server (`SMTP_*`, `MAIL_FROM`) |
| `Messenger` | `MESSENGER` | `wame`: a `wa.me` link the admin sends from their own phone |
| `BlobStore` | `BLOB_STORE` | `local`: files under `BLOB_LOCAL_DIR` · `s3`: any S3-compatible store (`S3_*`) |
| `PaymentRail` | `PAYMENT_RAIL` | `none`: no online payment; students transfer and upload a proof |
| `BankFeed` | `BANK_FEED` | `none`: no transactions; payments are validated by hand |

`create_app` builds them once into `app.state.integrations`; an endpoint takes them with `Depends(get_integrations)`. A `BlobStore` only presigns: the browser PUTs and GETs the bytes itself, so files never pass through the API. The `local` store signs its URLs with `SECRET_KEY` and serves them at `/api/blobs/…`, where the signature, not a session, is the authorisation, as it is for S3.

Uploads take only the types a transfer proof can be (`ALLOWED_CONTENT_TYPES`: JPEG, PNG, WebP, HEIC, PDF). The content type is signed into every upload URL, so S3 enforces the list too. Anything a browser renders as a page, such as HTML or SVG, is refused, because the local store serves downloads from the app's own origin. Those downloads also go out as `Content-Disposition: attachment` with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`. Keys are paths, so one key cannot nest under another (`a` and `a/b`): the second upload gets a 409.

`tests/integrations` is the contract: each interface's tests run against every implementation, and a new one (SES, the WhatsApp Business API, Fintoc) joins the parametrised list and must pass them. The `BlobStore` contract runs against real Garage, since most of it is about what the server refuses.

## Database roles

Three roles, none of them a superuser:

| Role | Setting | What it is |
| --- | --- | --- |
| `rakin_owner` | `MIGRATION_DATABASE_URL` | owns the database and every table; Alembic runs as it |
| `rakin_api` | `DATABASE_URL` | the API's login user, a member of `rakin_app` |
| `rakin_app` | (none) | holds the table privileges; cannot log in, owns nothing, no `BYPASSRLS` |

Migrations never create roles, so the owner needs no `CREATEROLE`. A superuser creates the roles once per database, before the first migration, taking each user's name and password from the two settings:

```sh
uv run python -m app.db_bootstrap postgresql://<superuser>:<password>@localhost:5432/rakin
```

Without the URL it connects with the standard libpq variables (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`), which is how Compose's `migrate` runs it: the password needs no URL escaping and stays out of the process arguments.

Locally that superuser is the Postgres image's `POSTGRES_USER` (`rakin:rakin`). In production, run it once from an admin shell; the API and Alembic never see the superuser's credentials. Re-running is safe: it resets passwords and attributes to what the settings and this table say. It refuses to turn an existing superuser into either user, and refuses one user for both.

## Tenancy

Every gym-scoped endpoint takes a `TenantSession` (`app/tenancy.py`):

```python
@router.get("/plans")
async def list_plans(session: TenantSession) -> list[PlanOut]: ...
```

It opens one transaction per request and sets `app.gym_id` for that transaction only (`set_config('app.gym_id', …, true)`, the bound-parameter form of `SET LOCAL`), so RLS limits every query to the gym and a missed `WHERE` returns nothing. It commits before the response is sent and rolls back if the endpoint raises. The gym comes from `request.state.tenant`, which the auth layer sets; with none, the request is a 401 and no session is opened. `tests/test_tenancy.py` calls every operation in the OpenAPI schema without a tenant and fails on any that answers something other than 401, outside `PUBLIC_PATHS`.

A person joins a gym through `join_gym_by_phone(phone, name, email, rut, dob)`, which `POST /api/people` calls: it finds or creates the person with that phone and writes the gym's `gym_person` record, and returns `(person_id, joined)`. `joined` is false only when the person was already in this gym, which the API answers with a 409 naming them; a phone known only to other gyms answers exactly like a new one (migration `0004`). The API never reads or writes `person`'s other columns: `rakin_app` may select only `id` and `phone`, and may not update it.

## People API

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/people` | add a person by phone; 201 with this gym's record, 409 `{"detail": {"code": "phone_in_gym", "person_id": …}}` if the phone is already in this gym |
| `GET` | `/api/people/{id}` | this gym's record; 404 for anyone not in the gym, known elsewhere or not |
| `PATCH` | `/api/people/{id}` | change `name`, `email`, `rut`, `dob` in this gym's record only; `null` clears an optional field |

Phones are normalised to E.164 Chilean mobiles and RUTs to `76123456-0`; anything else is a 422. The phone is set on create and not editable here, since changing it moves the gym's record to another identity.

## Migrations

```sh
uv run alembic revision -m "describe the change"
uv run alembic upgrade head
```

Every table with a `gym_id` (and `gym` itself) is isolated by an RLS policy on `current_setting('app.gym_id')`. With `app.gym_id` unset, those tables return no rows. `person` is global but not globally readable: a read sees only people with a `gym_person`, `membership` or `staff` row in the current gym (migrations `0003`, `0004`), and the API sees only their `id` and `phone`. `job_run` is global.

RLS is **forced**, so it applies to `rakin_owner` as well, not only to the API. A table owner is normally exempt from its own policies; forcing them means a backfill, seed or one-off script run with the owner's credentials sees and writes only the gym in `app.gym_id`, so a missed `SET` returns nothing there too. Work that spans gyms (the nightly jobs, a gym switcher) sets `app.gym_id` per gym or goes through a `SECURITY DEFINER` function written for it. Only a superuser skips RLS.

`ledger_entry` is append-only for every role, the owner and superusers included: triggers reject `DELETE` and `TRUNCATE`, and an `UPDATE` may change only `status`, `validated_by`, `validated_at` and `note`, and only while the entry is `pending`. Violations raise `restrict_violation` (SQLSTATE 23001). A correction is a new entry.

Grants name each table; `rakin_app` has no privilege on `alembic_version`. A new table gets its `GRANT` (and, if it carries `gym_id`, its RLS policy) in the migration that creates it.

The Postgres tests create, bootstrap and drop a throwaway database on the `TEST_DATABASE_URL` server, so that URL must be a superuser.

## Seed data

```sh
uv run python -m app.seed                      # as of today in the gym's timezone
uv run python -m app.seed --today 2026-11-08   # the day the UI design depicts
make seed                                      # from the repo root, inside Compose
```

`app.seed` loads Academia Sur, the demo gym that dev, the 90-day simulation and the self-host demo start from. `app/seed/data.py` is the roster: the members the [UI design](../docs/design/ui-design.html) names, in the standing it shows them in (Felipe Díaz 9 days overdue, Diego Morales's proof waiting, Camila Ortiz paying for Mateo and Sofía), plus filler drawn from a fixed random sequence. `app/seed/build.py` turns it into rows for a seed date with no I/O, so tests check it without a database. The design's numbers hold on any seed date: 64 active memberships and 2 frozen, 6 overdue for $270.000, 3 proofs for $162.000. `gym.settings` carries the BJJ grading scheme (white to black with 4 stripes, and the grey-to-green kids ladder), the custom-field definitions, the bank account and `grace_days` (10).

Loading again inserts nothing: every row's id is a UUIDv5 of its natural key, and rows already there are skipped, never updated, which the append-only ledger requires anyway. The first load stores its date in `gym.settings["seed"]["as_of"]`, and later loads build for that date again, ignoring `--today`. To reseed for another date, start from an empty database (`docker compose down -v`).

The loader connects as the owner (`MIGRATION_DATABASE_URL`) with `app.gym_id` set to the demo gym. Ranks and guardian links have no tables yet (#48, #19): ranks live in `data.py`, checked against the grading scheme, and a guardian is the payer (`claimed_by`) of their dependents' payments. Every person gets a `gym_person` row with the same name, email, RUT and date of birth. Every guardian also trains, so the roster's payers are members too. Drop-ins have a plan but no memberships, since a drop-in is a single attendance.
