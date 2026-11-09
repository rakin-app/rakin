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

Four roles, none of them a superuser:

| Role | Setting | What it is |
| --- | --- | --- |
| `rakin_owner` | `MIGRATION_DATABASE_URL` | owns the database and every table; Alembic runs as it |
| `rakin_api` | `DATABASE_URL` | the API's login user, a member of `rakin_app` |
| `rakin_app` | (none) | holds the table privileges; cannot log in, owns nothing, no `BYPASSRLS` |
| `rakin_auth` | (none) | owns sign-in's lookups across gyms (see Sign-in); cannot log in, `BYPASSRLS`, reads only `gym_person`, `membership`, `staff` and `auth_session` |

Migrations never create roles, so the owner needs no `CREATEROLE`. A superuser creates the roles once per database, before the first migration, taking each user's name and password from the two settings:

```sh
uv run python -m app.db_bootstrap postgresql://<superuser>:<password>@localhost:5432/rakin
```

Without the URL it connects with the standard libpq variables (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`), which is how Compose's `migrate` runs it: the password needs no URL escaping and stays out of the process arguments.

Locally that superuser is the Postgres image's `POSTGRES_USER` (`rakin:rakin`). In production, run it once from an admin shell; the API and Alembic never see the superuser's credentials. Re-running is safe: it resets passwords and attributes to what the settings and this table say. It refuses to turn an existing superuser into either user, and refuses one user for both. A database bootstrapped before `rakin_auth` existed needs one more run before `alembic upgrade` reaches `0005`, which checks for it; Compose's `migrate` runs bootstrap on every start.

## Tenancy

Every gym-scoped endpoint takes a `TenantSession` (`app/tenancy.py`), through the session for the staff roles it serves (`app/roles.py`):

```python
@router.get("/plans")
async def list_plans(session: StaffSession) -> list[PlanOut]: ...  # owner, admin, coach


@router.get("/ledger")
async def list_entries(session: LedgerSession) -> list[EntryOut]: ...  # owner, admin
```

It opens one transaction per request and sets `app.gym_id` and `app.person_id` for that transaction only (`set_config('app.gym_id', …, true)`, the bound-parameter form of `SET LOCAL`), so RLS limits every query to the gym and a missed `WHERE` returns nothing. It commits before the response is sent and rolls back if the endpoint raises. The gym comes from `request.state.tenant`, which the session middleware sets (see Sign-in); with none, the request is a 401 and no session is opened. `tests/test_tenancy.py` calls every operation in the OpenAPI schema without a tenant and fails on any that answers something other than 401, outside `PUBLIC_PATHS`.

Roles are per gym: a person's role is their `staff` row in the gym the request acts in, read on every request, so the owner of one gym is a plain member at another. A request whose person lacks the role is a 403; a member, with no `staff` row, gets a 403 from every staff endpoint, and `tests/test_roles.py` calls every operation as one to keep it so. Coaches never see the ledger, and RLS holds them to it too (migration `0006`): for `rakin_app`, `ledger_entry` rows need an owner or admin in `app.person_id`, so an endpoint that took the wrong session still returns a coach no entries. A view over the ledger must be created `WITH (security_invoker = true)` for that to reach it.

A person joins a gym through `join_gym_by_phone(phone, name, email, rut, dob)`, which `POST /api/people` calls: it finds or creates the person with that phone and writes the gym's `gym_person` record, and returns `(person_id, joined)`. `joined` is false only when the person was already in this gym, which the API answers with a 409 naming them; a phone known only to other gyms answers exactly like a new one (migration `0004`). The API never reads or writes `person`'s other columns: `rakin_app` may select only `id` and `phone`, and may not update it. `membership` and `staff` reference `gym_person (gym_id, person_id)`, so a gym holds rows only for people it has a record of. The migration's downgrade drops every `gym_person` record; it is for development only.

## People API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/people` | the member list (Alumnos), by name, 50 a page: `{"items": […], "total": n}`; see below |
| `POST` | `/api/people` | add a person by phone; 201 with this gym's record, 409 `{"detail": {"code": "phone_in_gym", "person_id": …}}` if the phone is already in this gym |
| `GET` | `/api/people/{id}` | this gym's record; 404 for anyone not in the gym, known elsewhere or not |
| `PATCH` | `/api/people/{id}` | change `name`, `email`, `rut`, `dob` in this gym's record only; `null` clears an optional field |

Any staff role may use it (`StaffSession`); a member gets a 403. Phones are normalised to E.164 Chilean mobiles and RUTs to `76123456-0`; anything else is a 422. The phone is set on create and not editable here, since changing it moves the gym's record to another identity.

The list holds everyone the gym has a record of except staff with no membership there. Each row carries `id`, `name`, `phone`, `rut` and the `membership` it shows (`id`, `status`, `plan_id`, `plan_name`), or `null`: the person's latest membership that is not cancelled, else their latest. Its parameters:

| Parameter | Matches |
| --- | --- |
| `q` | the name, ignoring case and accents (`martin` finds `Martín`); and when it holds a digit, the phone or the RUT in any format (`9 8765 4321`, `7.654.321`) |
| `status` | the row's membership status; repeatable, any of them (`?status=frozen&status=lapsed`) |
| `plan_id` | the row's membership plan; repeatable, any of them |
| `limit`, `offset` | the page: `limit` 1–200, 50 by default |

Filters combine with AND. Filtering by program waits on class types (#42), which is where programs are defined.

## Plans API

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/plans` | create a plan of one of the five kinds; 201 with the plan |
| `GET` | `/api/plans` | the gym's plans, active first, then by name; `?active=true` (or `false`) to filter |
| `GET` | `/api/plans/{id}` | one plan; 404 for another gym's |
| `PATCH` | `/api/plans/{id}` | change `name`, `price_clp`, the kind's own parameters, or `active` |

The body is told apart by `kind`, and each kind takes exactly its own parameters ([spec](../docs/technical.md#sport-agnostic-design)); anything else is a 422:

| `kind` | parameters |
| --- | --- |
| `monthly` | `price_clp`, `anchor`: `signup` (the member's signup day of the month) or `first` |
| `prepaid` | `price_clp`, `period_months` |
| `credits` | `price_clp`, `credits`, `credit_expiry_days` |
| `dropin` | `price_clp` |
| `trial` | `free_classes`, `free_days`, or both; no price, a trial is free |

`price_clp` is at most 100,000,000 and every count at most 2^31−1, the `integer` column's range. The kind is set on create. A `PATCH` locks the plan's row, so concurrent edits apply one after the other, and is checked as the whole plan it would leave, so `null` on a required parameter or another kind's parameter is a 422 and nothing changes. A plan is never deleted: `PATCH {"active": false}` deactivates it, `true` brings it back. Any staff role may read plans (`StaffSession`); only an owner or admin may create or change one (`AdminSession`).

## Memberships API

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/memberships` | start `person_id` on `plan_id` from `started_on` (default: today in the gym's timezone; at most 5 years either side of it); 201 with the membership |
| `GET` | `/api/memberships?person_id=…` | a person's memberships in this gym, latest first |
| `GET` | `/api/memberships/{id}` | one membership; 404 for another gym's |
| `POST` | `/api/memberships/{id}/plan-change` | `{"plan_id": …}`: move to that plan from the next period; the membership's own plan withdraws a pending change |
| `POST` | `/api/memberships/{id}/cancel` | `{"reason": …}`: cancel for good; a reason of 1 to 500 characters is required |

Dates are calendar dates in the gym's timezone (`app.domain.dates`), and `started_at` is stored as the first instant of `started_on` there. What a membership starts with follows its plan (`app.domain.membership.start`): a monthly or prepaid one is paid through the day before it starts, so its first period falls due on the start date, and a monthly one bills on `anchor_day`, its start day for a `signup` anchor or the 1st for a `first` one. A credits pack starts with its credits and lasts `credit_expiry_days`; a trial starts in `trial` with its free classes and free days. A drop-in is not a membership, and a deactivated plan, or a person or plan this gym does not have, is a 422.

A plan change waits for the next period; proration is v2. Only a monthly or prepaid membership changes plan, to another monthly or prepaid plan (a pack or trial ends, and a trial converts on payment). The change is stored as `next_plan` with the day it `starts_on`: the day after the paid-through date, or after the last billed period if billing has run ahead, so a period already billed keeps its plan and amount. Billing (#31) prices a period starting on or after that day at the new plan and moves it into `plan_id`, recomputing `anchor_day` with `domain.anchor_day(new_terms, next_plan_from)`, so a move to a `first` anchor bills on the 1st and a move to prepaid clears it. Cancelling follows the state machine: an active or lapsed membership can be cancelled, a trial or frozen one cannot (409), and a cancelled one changes no more (409). It drops a pending plan change. Any staff role may read memberships; only an owner or admin may start, change or cancel one.

## Gym settings API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/gym/settings` | the current gym's `name`, `slug`, `timezone`, `grace_days`, `reminder_every_days`, `channels` and `bank_account`; a setting never stored reads as its default (5 grace days, a reminder every 3 days, WhatsApp on, no bank details) |
| `PATCH` | `/api/gym/settings` | change any of those but `slug`; `channels` and `bank_account` are replaced whole, and `bank_account: null` clears the bank details |

Owner and admin only (`AdminSession`); a coach or member gets a 403, since the bank details decide where students send their money. `name` and `timezone` are columns on `gym`; the rest are keys of `gym.settings`, and the grading scheme and custom fields stored beside them are left untouched. `timezone` must be an IANA name, `grace_days` 0 to 60, `reminder_every_days` 1 to 30. `bank_account` takes `bank`, `account_type` (`Cuenta Corriente`, `Cuenta Vista`, `Cuenta RUT` or `Cuenta de Ahorro`), `holder`, `rut` (normalised to `76123456-0`), `number` and an optional `email` for the transfer notice. Email is always on, so `channels` holds only `whatsapp`.

## Sign-in

Students and staff sign in with a magic link ([spec](../docs/technical.md#communications)). `app/magiclink` is the mechanism, self-contained so it can become a package: it imports nothing else from `app`. `app/auth.py` plugs Rakin into it: people by email, Postgres, and the mailer.

| Route | What it does |
| --- | --- |
| `POST /api/auth/link` `{"email": …}` | emails a link to every person a gym has on record at that address (`gym_person.email`) with a membership or staff row there. Always a 202, known address or not; a 429 with `Retry-After` past 5 requests per address or 30 per IP in 15 minutes |
| `GET /api/auth/callback?token=…` | the page the link opens: an "Entrar" button. It does not spend the link, so a mail scanner that fetches it does no harm |
| `POST /api/auth/callback` | the button. Spends the link and sets the session cookie, then redirects to `/` |
| `POST /api/auth/logout` | ends the session and clears the cookie |

A link is a signed token (HMAC with `SECRET_KEY`) that expires after 15 minutes and works once; `auth_link` stores only its SHA-256. The session is a 30-day cookie, `__Host-session`, `HttpOnly`, `Secure`, `SameSite=Lax`, and `auth_session` likewise stores only its hash. Both pages are plain HTML forms with no script, so a link works in any browser tab. Browsers accept `Secure` cookies from `http://localhost`, so sign-in works on the Compose stack as is; open the link on the same host name the app is served on.

On each request with the cookie, the session middleware sets `request.state.person_id` and, when the session has a gym, `request.state.tenant`. It never answers 401 itself: `TenantSession` stays the one place a gym-scoped route refuses. A session ends as soon as its person no longer has a membership or staff row in its gym. A person in exactly one gym signs in to it; a person in several signs in to none yet, and gym routes answer 401 until they pick one (#16).

Sign-in looks across gyms before any gym is set, which RLS forbids even the owner. Migration `0005` does it in `SECURITY DEFINER` functions owned by `rakin_auth`: `auth_people_by_email`, `auth_gyms_of`, `auth_live_session` and `auth_end_session`. `auth_session` is gym-scoped like any table with a `gym_id`, with inserts open, as on `person`.

The rate limits live in the API process's memory, which is right for the single process Rakin runs. They count by client address, so behind a proxy uvicorn must trust its `X-Forwarded-For`: Compose sets `FORWARDED_ALLOW_IPS` on `api`, whose port is not published.

## Migrations

```sh
uv run alembic revision -m "describe the change"
uv run alembic upgrade head
```

Every table with a `gym_id` (and `gym` itself) is isolated by an RLS policy on `current_setting('app.gym_id')`. With `app.gym_id` unset, those tables return no rows. `person` is global but not globally readable: a read sees only people with a `gym_person`, `membership` or `staff` row in the current gym (migrations `0003`, `0004`), and the API sees only their `id` and `phone`. `job_run` is global.

RLS is **forced**, so it applies to `rakin_owner` as well, not only to the API. A table owner is normally exempt from its own policies; forcing them means a backfill, seed or one-off script run with the owner's credentials sees and writes only the gym in `app.gym_id`, so a missed `SET` returns nothing there too. Work that spans gyms (the nightly jobs, a gym switcher) sets `app.gym_id` per gym or goes through a `SECURITY DEFINER` function written for it. Only a superuser skips RLS.

`ledger_entry` is append-only for every role, the owner and superusers included: triggers reject `DELETE` and `TRUNCATE`, and an `UPDATE` may change only `status`, `validated_by`, `validated_at` and `note`, and only while the entry is `pending`. Violations raise `restrict_violation` (SQLSTATE 23001). A correction is a new entry. The API reads and writes it only for an owner or admin of the gym in `app.person_id` (`0006`); the owner role, which the seed and jobs use, is scoped by the gym alone.

`plan` rows are never deleted either: triggers reject `DELETE` and `TRUNCATE` for every role (`0007`), since memberships and the ledger point at them; deactivate one with `active = false`. A check holds each row to its kind's parameters, the rest null. A trial keeps its free classes and free days in `credits` and `credit_expiry_days`, with `price_clp` 0.

A cancelled `membership` is final: a trigger rejects any `UPDATE` of it for every role (`0009`), raising `restrict_violation`. Checks hold `cancel_reason` and `cancelled_at` to exactly the cancelled rows, and `next_plan_id` and `next_plan_from` (a plan change waiting for its period) to being set together, never on a cancelled row.

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

## Nightly jobs

```sh
uv run python -m app.jobs.daily                      # run what is due, once (for cron)
uv run python -m app.jobs.daily --every 3600         # stay up and check hourly (Compose's `jobs`)
uv run python -m app.jobs.daily --today 2026-11-08   # as if it were that date
```

`app/jobs` runs each job once per day ([spec](../docs/technical.md#core-state-machines)). A job is a `Job(name, run)`, where `run(conn, day)` does the day's work on an `asyncpg` connection; `JOBS` in `app/jobs/daily.py` lists them in the order they run on a day, so a later job can rely on an earlier one's work.

`job_run` is the record: a day is done for a job once it holds a `succeeded` row for `(job_name, run_date)`, and a job owes every day from its first row to today that has none. A run that finds nothing owed does nothing; one after downtime catches the missed days up, oldest first, and a job that has never run starts today. Each `(job, day)` is one transaction that also marks its row `succeeded`, so the work and its record commit together. A failure rolls the work back, marks the row `failed`, logs `job failed` with the job and date, and stops the run, since later days and later jobs may depend on it; the next run retries that day first. Run once (no `--every`), it exits 1 on a failure.

Days are dates in `JOBS_TIMEZONE` (`America/Santiago`). One runner works at a time, under a Postgres advisory lock: a second one logs that and does nothing, and a `running` row found under the lock, left by a runner that died, is run again. The runner connects as the owner (`MIGRATION_DATABASE_URL`), as the seed does, so RLS still holds it to one gym: a job that works per gym sets `app.gym_id` for each.

Set `SENTRY_DSN` to report failures to Sentry (`app/sentry.py`): every `ERROR` log line becomes an event, so a failed job, or a run that could not reach the database, arrives there with its traceback. Empty, the default, sends nothing.
