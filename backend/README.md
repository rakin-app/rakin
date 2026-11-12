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

"Today" is the gym's date, `gym_today(tz)` in `app/domain/dates.py` (`seeded_today()` in `tests/pg.py` for a seeded gym), never the host's: on a UTC host the two differ every night from 00:00 UTC. `tests/test_clock.py` fails on `date.today()`, a zoneless `datetime.now()` and `datetime.now(UTC).date()` in `app`, `tests` and `alembic`; a line that does mean the host's date carries a `# system date: <why>` comment. CI's `backend-midnight` job runs the suite with Postgres and pytest under libfaketime at 00:30 UTC, `TZ=UTC`, without the `s3` tests.

## Integrations

Every external service sits behind an interface in `app/integrations`, and a setting picks the implementation. The defaults need no network and no account, so a self-hosted instance works offline with none configured ([spec](../docs/technical.md#architecture)).

| Interface | Setting | Implementations (default first) |
| --- | --- | --- |
| `Mailer` | `MAILER` | `console`: logs each message, sends nothing · `smtp`: any SMTP server (`SMTP_*`, `MAIL_FROM`); hosted Rakin uses Resend's (`smtp.resend.com`) |
| `Messenger` | `MESSENGER` | `wame`: a `wa.me` link the admin sends from their own phone |
| `BlobStore` | `BLOB_STORE` | `local`: files under `BLOB_LOCAL_DIR` · `s3`: any S3-compatible store (`S3_*`) |
| `PaymentRail` | `PAYMENT_RAIL` | `none`: no online payment; students transfer and upload a proof |
| `BankFeed` | `BANK_FEED` | `none`: no transactions; payments are validated by hand |
| `HumanCheck` | `HUMAN_CHECK` | `none`: the join form's honeypot and rate limits only · `turnstile`: Cloudflare Turnstile on the join form (`TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`) |

`create_app` builds them once into `app.state.integrations`; an endpoint takes them with `Depends(get_integrations)`. A `BlobStore` only presigns: the browser PUTs and GETs the bytes itself, so files never pass through the API. The `local` store signs its URLs with `SECRET_KEY` and serves them at `/api/blobs/…`, where the signature, not a session, is the authorisation, as it is for S3.

Uploads take only the types a transfer proof can be (`ALLOWED_CONTENT_TYPES`: JPEG, PNG, WebP, HEIC, PDF), up to `MAX_UPLOAD_BYTES` (10 MB). The content type and the exact size are signed into every upload URL, so S3 enforces both too: a body of any other size, or a `Content-Type` other than the signed one, is refused. A browser sends the file's size as `Content-Length` on its own. `stat(key)` reads a stored file's size and type back without its bytes (an S3 `HEAD`), which is how the API checks an upload landed. Anything a browser renders as a page, such as HTML or SVG, is refused, because the local store serves downloads from the app's own origin. Those downloads also go out as `Content-Disposition: attachment` with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`. Keys are paths, so one key cannot nest under another (`a` and `a/b`): the second upload gets a 409.

With `BLOB_STORE=s3` the browser PUTs to `S3_PUBLIC_ENDPOINT_URL`, another origin than the app's, so the bucket needs a CORS rule allowing `PUT` (with a `Content-Type` header) and `GET` from `PUBLIC_BASE_URL`. `python -m app.blob_cors` prints that rule, `--apply` sets it through `PutBucketCors` (which Garage, R2 and S3 all take; Garage's CLI has no CORS command, so `garage-init` does not), and `--check` sends the browser's preflight and reports the answer. Setting it needs a key allowed to change the bucket: on Garage the api's key is (`garage-init` makes it the owner), on R2 or S3 pass an admin key for that run ([deploy.md](../docs/deploy.md#first-deploy-only-the-buckets-cors-rule)). The `local` store needs none: its URLs are root-relative (`/api/blobs/…`), so the browser sends them to the host the page is on, `PUBLIC_BASE_URL`'s or a gym's own.

`tests/integrations` is the contract: each interface's tests run against every implementation, and a new one (the WhatsApp Business API, Fintoc) joins the parametrised list and must pass them. The `BlobStore` contract runs against real Garage, since most of it is about what the server refuses.

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

Roles are per gym: a person's role is their `staff` row in the gym the request acts in, read on every request, so the owner of one gym is a plain member at another. A request whose person lacks the role is a 403; a member, with no `staff` row, gets a 403 from every staff endpoint, and `tests/test_roles.py` calls every operation as one to keep it so. Coaches never see the ledger, and RLS holds them to it too (migration `0006`): for `rakin_app`, `ledger_entry` rows need an owner or admin in `app.person_id`, so an endpoint that took the wrong session still returns a coach no entries but their own (migration `0010` lets anyone read the entries of their own memberships and their dependents'). A view over the ledger must be created `WITH (security_invoker = true)` for that to reach it. Nor do coaches see money anywhere else (#205): the plans and memberships they read come without `price_clp` and `discount_pct` (`SeesMoney` in `app/roles.py`), and `tests/test_coach_money.py` calls every staff GET as the demo gym's coach and fails on any amount, price, discount, balance or ledger key in the answer.

A person joins a gym through `join_gym(rut, email, name, phone, dob)` (migration `0036`), which `POST /api/people` calls: with a RUT it finds or creates the person that RUT is; with none, the person this gym already has under the email, if any; otherwise, and always for a dependent with neither, someone new. It writes the gym's `gym_person` record and returns `(person_id, joined)`. `joined` is false only when the person was already in this gym, which the API answers with a 409 naming them; a RUT known only to other gyms answers exactly like a new one, and an email never links two gyms' people. The phone is a contact on the gym's record and finds nobody. The API never reads or writes `person`'s other columns: `rakin_app` may select only `id`, may not update it, and may not insert into it, so no unique violation can tell it a RUT is taken. `membership` and `staff` reference `gym_person (gym_id, person_id)`, so a gym holds rows only for people it has a record of. The migration's downgrade drops every `gym_person` record; it is for development only.

## People API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/people` | the member list (Alumnos), by name, 50 a page: `{"items": […], "total": n}`; see below |
| `POST` | `/api/people` | add a person by `rut`, or by `email` with none (one of the two is required); 201 with this gym's record, 409 `{"detail": {"code": "rut_in_gym", "person_id": …}}` if the RUT is already in this gym, `email_in_gym` if the email is someone's here with no RUT of their own |
| `GET` | `/api/people/{id}` | this gym's record, with `left_on` once they have left; 404 for anyone not in the gym, known elsewhere or not |
| `PATCH` | `/api/people/{id}` | change `name`, `email`, `phone`, `no_whatsapp`, `rut`, `dob` in this gym's record only; `null` clears an optional field; checked before anything is written: 409 `rut_in_gym` or `email_in_gym` for a RUT or email someone else in the gym has; 422 for leaving someone who is nobody's dependent with neither a RUT nor an email, and for a member whose phone is cleared, or "No tiene WhatsApp" unticked, with no phone in its place |
| `POST` | `/api/people/enrol` | "Nuevo alumno": the record (by RUT or email, or by name for a dependent), the `phone` or `no_whatsapp`, the guardian a minor needs (whose phone, or `no_whatsapp`, is required instead), custom `fields`, a `membership` (`plan_id`, `started_on`) and `send_welcome`, all or nothing; 201 with the record, 409 as `POST /api/people`, or `one_level` for a guardian who is a dependent. The welcome goes after the answer, to them or their guardian, with their sign-in link: about the plan, or with none that they are on the gym's list (#246); with no email, nothing goes |
| `GET` | `/api/people/{id}/welcome` | "Acceso" on the ficha (#246): `{to, guardian, last}`, the address their welcome goes to (`null` with none), the guardian's name when it is theirs, and the latest welcome about them as `message_log` has it, `{status: "sent" \| "failed", sent_at, to}` or `null`. Owner and admin |
| `POST` | `/api/people/{id}/welcome` | "Enviar link para entrar": sends the welcome now, about the plan they are on and not yet cancelled or with none, and answers as `GET`, saying whether it went. 422 `no_email`, 409 for someone who has left. Owner and admin |
| `POST` | `/api/people/{id}/leave` | "Dar de baja" from `left_on` (today by default, never later): every membership they hold ends, reason `dado de baja`; 409 if they already left |
| `POST` | `/api/people/{id}/return` | "Reactivar": back on the list, on `membership`'s plan if given; 409 if they have not left |
| `GET` | `/api/people/{id}/deletion` | `{"refused": null}`, or why `DELETE` would keep them: `ledger`, `staff`, `guardian` |
| `DELETE` | `/api/people/{id}` | "Eliminar": this gym's records of them, gone; 204, or 409 with the refusal |

Any staff role may use the first four (`StaffSession`); a member gets a 403. Enrolling, leaving and returning are the owner's and admins' (`AdminSession`), since they start or end what a member is charged, and deleting is the owner's alone (`OwnerSession`). Phones are normalised to E.164 Chilean mobiles and RUTs to `76123456-0`; anything else is a 422. The phone is a contact, editable like the email. A member needs one, since the gym reaches them on WhatsApp, unless `no_whatsapp` ("No tiene WhatsApp") is set, which also hides every WhatsApp link for them; a minor's guardian's is the one required, and staff need none. Each record carries `no_whatsapp` and `missing_phone`, "Falta teléfono": a member, neither staff nor someone's dependent, with no phone and the box unticked; and `missing_rut`, "Falta RUT": no RUT and no email, as an old sheet's row leaves them. A RUT edited here changes this gym's record, and becomes who the person is when they had none and nobody else has it (`claim_rut`, 0036); when someone in another gym has it, nothing else changes and the answer is the same, since linking two people is a merge this API does not do.

The list holds everyone the gym has a record of except staff with no membership there. `?missing_phone=true` keeps only the "Falta teléfono" rows, `?missing_rut=true` the "Falta RUT" ones, and `?away=true` those away 14 days or more, as the inactive list counts them ("A quién llamar" in full, #178). Each row carries `id`, `name`, `phone`, `no_whatsapp`, `missing_phone`, `missing_rut`, `rut`, the `membership` it shows (`id`, `status`, `plan_id`, `plan_name`), or `null`: the person's latest membership that is not cancelled, else their latest; and their family: `guardian` (`id`, `name`) or `null`, and `dependents`, how many they pay for. Its parameters:

| Parameter | Matches |
| --- | --- |
| `q` | the name, ignoring case and accents (`martin` finds `Martín`); and when it holds a digit, the phone or the RUT in any format (`9 8765 4321`, `7.654.321`) |
| `status` | the row's membership status; repeatable, any of them (`?status=frozen&status=lapsed`) |
| `plan_id` | the row's membership plan; repeatable, any of them |
| `rank` | the person's current rank, their latest promotion, by key; repeatable, any of them (`?rank=blue`) |
| `rank_min` | that rank or any above it on its own ladder, by the order of the gym's grading scheme: "Azul o superior" (#219). Kyu count down then dan up, so `kyu-1` finds the dan grades too; a kids belt is on another ladder, so neither counts as above an adult one. A key the scheme does not have is a 422 `unknown_rank` |
| `left` | who has left the gym: `no` (the default) leaves them out, `only` is the "Dados de baja" list, `any` everyone, as the Pagos picker asks, since they still owe what they owe |
| `limit`, `offset` | the page: `limit` 1–200, 50 by default |

Filters combine with AND. Filtering by program waits on class types (#42), which is where programs are defined.

Leaving ends each membership whatever its state, a trial or a frozen one too, which `POST /api/memberships/{id}/cancel` would refuse (`app.domain.membership.leave`): a booked freeze is called off and a running one ends today. Billing, the roster, the inactive list and "Hoy" read memberships, so they stop counting them; the periods already billed stay owed. A day later than today is refused: a member leaves on the day they are dado de baja, or a day already past.

Deleting goes through `forget_gym_person` (migration `0032`), a `SECURITY DEFINER` function the owner role runs under forced RLS, so `rakin_app` gets no `DELETE` on any of the tables it empties. It keeps anyone with ledger entries or a cobro extra line in the gym (accounting has to), on its staff or the coach of a session there, or a guardian of someone there, and otherwise deletes their memberships and all that hangs off them, their family link, field values, unsubscribe and sign-in sessions and groups here, and last the `gym_person` row. The global `person` row and `message_log` stay; erasing them is #69's.

## Guardians and dependents

One payer, N dependents: a parent who pays for their kids, who have no phone ([spec](../docs/product.md#users)). `guardian_link` (migration `0010`) records who answers for whom in one gym, isolated by `gym_id`, so a family one gym records is never seen by another gym that shares the parent or a kid.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/people/{id}/family` | `{"guardian": {id, name} \| null, "dependents": [{id, name}, …]}`; 404 for anyone not in the gym |
| `POST` | `/api/people/{id}/dependents` | `{"person_id": …}` links someone already in the gym; `{"name", "email"?, "rut"?, "dob"?}` adds a new person with no phone. 201 with the guardian's family |
| `DELETE` | `/api/people/{id}/dependents/{dependent_id}` | unlinks; both stay in the gym. 204, or 404 if they were not linked |
| `GET` | `/api/me/dependents` | the signed-in person's dependents, each with the `membership` it shows and a `balance`: `owed_clp`, outstanding on periods already due, and `pending_clp`, payments sent but not validated |

The family routes take any staff role, like the rest of the people API. A dependent has one guardian in a gym, and links are one level deep: a guardian is nobody's dependent and a dependent nobody's guardian. Either refusal is a 409, `{"detail": {"code": "has_guardian"}}` or `{"detail": {"code": "one_level"}}`; linking someone to themselves is a 422. A new dependent with their own RUT is the person that RUT is, as anyone is; one with neither a RUT nor an email is a new person, in this gym only.

`/api/me` answers only about the person acting, so any session in a gym may use it, member or staff; it is the one group `tests/test_roles.py` lets a member reach. A guardian reads their dependents' ledger entries through `ledger_entry_own` (migration `0010`), which lets anyone read the entries of their own memberships and their dependents', and nothing more; every other entry and every write stays with an owner or admin (`0006`), but for the pending payment a person claims with a transfer proof (`0012`, see Transfer proofs). `owed_clp` settles each period the way `app.domain.billing` does. It is not `v_balance`, which nets every validated entry, so a charge written ahead of its due date already counts there. A dependent's attendance (`0023`) and rank (`grade_event`, `0018`) join it when the student page shows a dependent's.

Every notice about someone goes through `app.contacts.contact_for`, which answers with the guardian's own record in this gym when there is one: kids never receive messages, and may have no phone or email to send to.

## Transfer proofs

A student who paid by transfer uploads the proof, and the payment waits, pending, for an admin to validate or reject it (#36). Proofs never pass through the API process ([spec](../docs/technical.md#architecture)): the API presigns a PUT, the browser sends the file straight to the `BlobStore`, and only then is the payment claimed.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/me/periods` | billing periods the signed-in person can pay, theirs and their dependents', earliest due first: each with `person_name`, `plan_name`, dates, `amount_due_clp`, `paid_clp`, `outstanding_clp` and `pending_clp` (claimed by a proof, not yet reviewed). Only periods not yet paid in full |
| `POST` | `/api/me/proofs` | `{"content_type", "size_bytes"}`: 201 with `{key, url, headers, expires_in_seconds}`. PUT the file to `url` with `headers` and a body of exactly `size_bytes`. A type outside `ALLOWED_CONTENT_TYPES` or a size over 10 MB is a 422. Records nothing |
| `POST` | `/api/me/payments` | `{"billing_period_id", "amount_clp", "proof_key"}`, or `extra_line_id` in place of `billing_period_id` for a cobro extra line (see Cobros extra): 201 with a `pending` `transfer` payment, `claimed_by` the person acting and `proof_object_key` the key. 422 if the key is not one of the person's own uploads or the file is not there, or for neither or both of the two ids, 404 for a period or line that is not theirs or a dependent's, 409 for one paid in full or a proof already claimed |
| `GET` | `/api/ledger/pending` | `{"count"}`: payments waiting for review in the gym, the admin's badge. Owner and admin only |
| `GET` | `/api/me/role` | `{"role", "person_id"}`: the signed-in person's staff role here, `owner`, `admin` or `coach`, or `null` for a member, and who they are. The admin nav asks for the pending count only for an owner or admin, so a coach never polls a 403; the session screen offers the class timer only to the session's coach (`coach_id` is `person_id`), an owner or an admin |
| `GET` | `/api/me/page` | the student page, "Mi página" (#65): `gym_name`, `timezone`, `person_id`, `name`; `next_payment`, the first of `/api/me/periods` with a `status` (`in_review` when a proof claims it, `overdue` past its due date, else `due`), or `null` when nothing is owed, and then `paid_through`, the day the earliest paid up of their and their dependents' running memberships is paid through (#196), `null` with none paid yet; the gym's `bank_account` (`null` until set); and `payments`, the person's and their dependents' payments, refunds and adjustments (#210), so the list adds up to `next_payment`, newest first, at most 12, each with its `kind`, `status`, `period_start`, `claimed_at`, `validated_at` and `note`, which is only ever the one written for the student: a rejection's, or a carried credit's; `rank`, their current rank as `GET /api/people/{id}/grades` gives it, or `null`; and `attendance`, `{"this_month", "total"}`, their classes over every membership here, this calendar month in the gym's timezone and in all |

Keys are `proofs/<gym_id>/<person_id>/<uuid>`, so a claim takes only a key from the person's own prefix, and the API checks with `stat` that the file arrived before it records anything: a failed or abandoned upload leaves no pending entry. A claim does not settle the period; validating it does (#36). `amount_clp` is capped at the price ceiling (100,000,000), not at what is outstanding: an overpayment is allowed and becomes a credit when validated. The browser names the type from the file's extension when the picker gives none, as a desktop Chrome does for `.heic`. After the entry commits, `app.contacts.contact_for` decides who gets the "Recibimos tu comprobante" email: the student, or their guardian for a dependent. A failed send is logged and never undoes the claim.

Migration `0012` holds the database to the same rules. `ledger_entry_claim` lets anyone insert exactly one kind of entry, and only for a membership `ledger_entry_own` lets them read, or a cobro line of theirs or a dependent's that is not cancelled (`0037`): a `pending` `transfer` `payment`, claimed by `app.person_id`, validated by nobody, with a proof under their own prefix. A unique index on `proof_object_key` means one proof backs one entry. An upload that is never claimed stays in storage; sweeping those is left to the retention job.

### Reviewing proofs

An admin validates or rejects each pending proof in one tap ("Validar comprobante", #36). Owner and admin only (`LedgerSession`).

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/ledger/proofs` | the pending proofs, oldest claim first. Each carries the claim (`amount_clp`, `method`, `claimed_at`, `claimed_by_name`), the `period` it pays (dates, `amount_due_clp`, `paid_clp`, `outstanding_clp`), `proof_url` (a presigned GET) and `proof_content_type`, both `null` if the file is missing, the plan (`plan_name`, `plan_kind`, `anchor_day`), `prior_balance_clp` (outstanding on the membership's other periods already due), `last_payments` (its latest three validated payments, newest first) and `attendance_30d`, the person's classes here today and in the 29 days before it |
| `POST` | `/api/ledger/proofs/{id}/validate` | 200 with `{payment, credit, period}`, as `POST /api/ledger/payments` answers: the entry turns `validated`, the period closes once paid in full, and an overpayment becomes a validated credit adjustment with no period. 409 if the period is already paid in full: reject the proof instead |
| `POST` | `/api/ledger/proofs/{id}/reject` | `{"note"}`, required: 200 with the `rejected` entry carrying the note. The period stays open. The student, or their guardian, is emailed "Revisa tu comprobante" with the note. A note the claim already carried is kept ahead of it, as `<claim note> — rechazado: <note>`; the email carries the admin's note only |

Both record the reviewing admin in `validated_by` and `validated_at`, the ledger's audit columns, and both are terminal (`0002`): a proof already reviewed is a 409, and one that is not a pending proof in this gym a 404. Validating locks the membership, its period and then the entry, the order recording a payment and the nightly `lapse` job take them in: a lapse run waits for it, a payment recorded for the period meanwhile settles before or after it, never beside it, and two admins reviewing one proof settle it once.

Validating a proof, or recording a payment (`POST /api/ledger/payments`), emails the student or their guardian a "Pago validado" receipt after the payment commits: what was paid, the period it covers, what is left of that period, and the membership's running balance from `v_balance` (owed, credit, or up to date).

### A membership's ledger

The member detail ("Ficha de alumno", #60) reads one membership's money. Owner and admin only (`LedgerSession`); a coach sees the member and their plan through the people and memberships APIs, never this.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/ledger/memberships/{id}` | `{open_periods, owed_clp, entries, freezes, periods, refundable_payments}`. `open_periods`: every period validated payments and credit leave short, oldest first (the one a payment settles next), each with dates, `amount_due_clp`, `paid_clp`, `outstanding_clp`, `due` (due today or before in the gym's timezone) and `days_overdue` (0 on or before the due date). `owed_clp`: what the `due` ones still owe. `entries`: the membership's latest 100 entries, newest first, each with its `kind`, `status`, `amount_clp`, `method`, the `period_start` of its period (`null` for a carried credit), `note`, who reviewed it (`validated_by_name`, `validated_at`, `null` while pending) and `refund_of` (the payment a refund gives back). `freezes`: a line where each of its freezes started and one where it ended, once it has, newest first, each with `freeze_id`, `edge` (`start` or `end`), the `day`, the freeze's `from_date`, `to_date` and `reason`; they move no money and carry no amount. `periods`: every period, newest first, with `id`, `period_start`, `period_end` and `outstanding_clp` (0 once paid), what "Ajuste" offers. `refundable_payments`: every validated payment with something left to give back, newest first, with `id`, `billing_period_id`, `period_start`, `amount_clp`, `method`, `validated_at` and `refundable_clp`, what "Devolver" offers. Neither is cut to the latest 100 entries. `paid_through`: the end of the latest period with none owing before it, "Pagado hasta" (#196), `null` with no period or with the first still owing. 404 for a membership not in this gym |

A pending claim counts towards nothing until it is validated, as everywhere else (`app.domain.billing`).

### Paying ahead

A member who is up to date pays the next 1 to 12 periods at once (#196). They are billed on the spot as the nightly job would bill them later (`app.domain.billing.periods_ahead`, written by the job's own `app.jobs.billing.write_billing`), each with its charge, and each paid in full by a validated payment of its own, so the book and "Cobrado" count the money on the day it was received, a refund gives back a month as it gives back any payment, and the job, which picks up after the latest period, bills on after them. A pending plan change is applied when a period paid ahead reaches its day; a plan change made after paying ahead waits for the periods already billed, so what was paid keeps its price. A freeze moves the periods paid ahead as it moves any period not yet started. Refunding a period that starts after its membership was cancelled (a baja after paying ahead) also writes a validated adjustment of as much, "Período posterior a la baja: no se cobra", so the period is not a debt once it falls due; it comes back as `waived` on `POST /api/ledger/refunds`.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/ledger/memberships/{id}/ahead` | `{periods}`: the next 12 periods after the last one billed, oldest first, each with `period_start`, `period_end` and `amount_due_clp`, priced as billing will price them. Empty when the membership cannot pay ahead: not Active, not monthly or prepaid, or with a period still open, which is paid with `POST /api/ledger/payments` first. 404 for a membership not in this gym |
| `POST` | `/api/ledger/payments/ahead` | `{"membership_id", "periods", "amount_clp", "method", "note"?}`, `periods` 1 to 12: 201 with `{payments, periods, paid_through}`, one payment per period, oldest first, and the day they leave it paid through. `amount_clp` must be what those periods cost, as the quote says: anything else is a 409 `amount_changed`, so a price changed since is not recorded unseen. 409 `cannot_pay_ahead` when it cannot pay ahead, and `already_billed` if a period it would bill is there already. Each 409's `detail` is `{code, message}`. One receipt is emailed, for the total, from the first period's start to the last one's end |

### Adjustments and refunds

An admin corrects the ledger with new entries, never by editing one (#38). Both are created `validated` by the admin making them, take the membership's lock and then the period's as a payment does, and answer with the period as they leave it (`id`, `amount_due_clp`, `paid_clp`, `outstanding_clp`, `closed`). Owner and admin only (`LedgerSession`).

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/ledger/adjustments` | `{"membership_id", "billing_period_id", "amount_clp", "note"}`: 201 with `{adjustment, period}`. The sign says which way it goes: positive is in the member's favour and counts towards the period as a payment does, negative is owed on top of its amount due and opens a period that was paid. `note`, why, is required (422 without one), and `amount_clp` is not zero. 409 for one in the member's favour beyond what the period still owes: credit is a payment's to carry. 404 for a period not of that membership in this gym |
| `POST` | `/api/ledger/refunds` | `{"payment_id", "amount_clp", "method", "note"?}`: 201 with `{refund, period}`. The refund names its payment in `refund_of` and carries its period, which no longer counts what was given back and opens again if that leaves it short. 409 for a payment not validated, or more than is left of it after its earlier refunds. `waived`, an adjustment taking it off what is owed, when the period starts after its membership was cancelled (see Paying ahead), else `null`. 404 for an entry that is not a payment in this gym |

Every settlement in the app counts a period's validated payments and adjustments less its refunds (`app.domain.billing.settled_amount`), so a period's `paid_clp` is below zero while an adjustment against the member outweighs what was paid. Migration `0021` adds `refund_of` (a refund's payment: `(kind = 'refund') = (refund_of IS NOT NULL)`, a foreign key to an entry on the same membership, and the `ledger_entry_refund_target` trigger, which refuses one that is not a validated payment on the refund's own period; how much is left of the payment stays the API's to check, under the lock), holds every amount positive but an adjustment's, which is signed and not zero, and counts refunds in `v_overdue`. Neither sends an email.

### The ledger book

"Libro de pagos" (#39) reads the whole gym's ledger. Owner and admin only (`LedgerSession`); a coach gets a 403 and the screen does not ask.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/ledger/book` | `{month, months, timezone, kpis, items, total, freezes}`: a page of entries newest first by the day each is filed under (a charge's period start, any other entry's own day, #206), with the gym's KPIs. Each item carries its `kind`, `status`, `amount_clp`, `method`, `note`, `created_at`, the membership's `plan_name` and `membership_status` (`null` on a cobro line), its `person` (`id`, `name`) and `guardian` (`id`, `name`, or `null` unless the person is a dependent), its `period` (dates, `outstanding_clp`, settled as the member detail settles it, and `days_overdue`, 0 once paid; `null` for a carried credit) and `validated_by_name`. `freezes`: the month's freeze lines, as the member detail lists them, with the membership's `membership_id`, `plan_name`, `person` and `guardian`; all of them, unpaged, since a month has a handful, for `all` and the dependents' for `kids`, none for `pending` and `overdue`, and not counted in `total` |

| Parameter | Does |
| --- | --- |
| `month` | any day of the month to show, in the gym's timezone; the current month by default. `month` answers its first day, and `months` every month with entries plus the current and the shown one, newest first |
| `filter` | `all` (default): the month's entries, a charge in the month its period starts (so a November charge billed on October 26 is November's, #206) and any other entry in the month it was made. `pending`: payments waiting for review, of any month. `overdue`: the charges of the periods in `v_overdue`, of any month, whatever the membership's status (#207). `kids`: the month's entries on a dependent's membership (`guardian_link`), as `all` dates them |
| `limit`, `offset` | the page: `limit` 1–200, 50 by default. `total` counts what the filter matches across every page |
| `q` | up to 100 characters (#107): keeps, within the filter, the entries and freeze lines of the members the member list's search finds (name, accents and case ignored; phone and RUT in any format), and of the dependents of the guardians it finds. The KPIs stay the gym's |

`kpis`: `collected_clp` and `collected_payments`, the month's row of `v_monthly_income`, net of refunds, with `refunded_clp` and `refunds` beside it ("Cobrado $X · Devuelto $Y"); `expected_clp`, what is owed for the month: the periods falling due in it of `active` and `lapsed` memberships, since a lapsed member still owes what was billed (`cancelled`, `trial` and `frozen` ones are left out); and as the gym stands today, whichever month is shown: `pending_clp` and `pending_payments`, the claims waiting for review; `overdue_clp` and `overdue_members`, outstanding on the `v_overdue` periods of memberships in any status (a lapsed, frozen or cancelled plan still owes what it owed, #207) and the people owing it, and `overdue_avg_days`, per such person the days since their oldest unpaid period fell due, averaged; `active_memberships` and `frozen_memberships`.

### Overdue

The owner's dashboard ("Hoy", #58) lists what is overdue. Owner and admin only (`LedgerSession`).

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/ledger/overdue` | `{total_clp, periods}`: the `v_overdue` rows, longest overdue first, each with `billing_period_id`, `membership_id`, `person_id`, `person_name`, `plan_name`, `membership_status`, `period_start`, `due_date`, `outstanding_clp` and `days_overdue`; `total_clp` is what they still owe together. A lapsed, frozen or cancelled membership's unpaid periods are listed too, with its status for Hoy to say so (#207): a debt stays until it is paid or adjusted. "Pagó" on each row is `POST /api/ledger/payments` for the period's `outstanding_clp` |

## Cobros extra

Besides its plans, a gym charges one-off amounts: a rifa, a seminar, gear, or a cost the team splits, such as the fuel to a final divided among the athletes going (#195). A cobro (`extra_charge`, migration `0037`) has a title, a description, the message its email carries, a category (`rifa`, `seminario`, `equipamiento`, `gasto_compartido`, `otro`), a due date and a target: everyone with an active membership, a program's, a group, or people picked by hand, none of whom have left (picking a leaver is a 422). It charges each of them one line (`extra_line`), which is to the cobro what a billing period is to a membership. In `fixed` mode every line owes `amount_clp`; in `split` mode `amount_clp` is the total, divided in whole pesos with the remainder a peso more for each of the first people alphabetically, accents and case ignored (`app.domain.extra_charges.split`). An override sets one person's amount, a scholarship at 0 included, after the split and without moving the others'.

A line's money is ledger entries like a period's, naming the line in `extra_line_id` instead of a membership's period: a student's proof (`POST /api/me/payments` with `extra_line_id`), Validar comprobante's validate and reject, a payment the admin records, an adjustment, and a refund through `POST /api/ledger/refunds`. Each settles the line as `app.domain.billing` settles a period, under the cobro's lock and then the line's (`app.api.extra_lines`). A student's claim cannot take those locks, so `ledger_entry_line_open` (`0037`) takes the cobro's for it, shared, and refuses an entry on a cancelled line: a claim racing a cancel either lands first and is seen, or after it and is refused (409). An overpayment stays on the line, counted in full, rather than becoming credit, since a cobro has no next period to carry it to; the admin refunds what is beyond it. Proof received, receipt and rejection emails name the cobro instead of a period. A line never touches a membership: the lapse job and `v_overdue` read billing periods only, so an unpaid cobro lapses nothing and is never "Vencido".

A line's status is `open` (pendiente, partly paid included), `in_review` (comprobante enviado), `paid`, `waived` (exento: let off at $0, owing and paying nothing) or `cancelled` (anulado). Owner and admin only (`LedgerSession`); a coach gets a 403 and RLS holds them to it.

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/extra-charges/preview` | the draft so far (`target`, `amount_mode`, `amount_clp`, `overrides`, and `title` and `due_date` once given; anything else the wizard sends is ignored): each person's `amount_clp`, whether it is `overridden`, whom the notice goes to (`contact_name`, `on_behalf` for a guardian), `has_email` and, for someone with no email, a `whatsapp_url` with the cobro's message once it has a title and due date; `total_clp`, and a split's `share_clp` and `remainder_clp`. 422 for a target that names nobody, a split under a peso each, someone picked who is not in the gym or an override for someone not targeted; 404 for a program or group not in the gym |
| `POST` | `/api/extra-charges` | the draft with `title`, `description`, `message`, `category`, `due_date` and `notify` (true by default): 201 with the cobro as `GET` answers it. With `notify`, each person, or their guardian naming the child, is emailed their own amount, the due date, the gym's bank details and a sign-in link to the student page |
| `GET` | `/api/extra-charges` | every cobro, newest first, with `lines` and `paid_lines` (not cancelled, owing something), `waived_lines` (exentos, in neither), `due_clp` and `collected_clp`: "7 de 9 pagaron · $140.000 de $180.000" |
| `GET` | `/api/extra-charges/{id}` | the cobro and its `people`: each line's `person`, `guardian`, `amount_due_clp`, `overridden`, `paid_clp`, `outstanding_clp`, `pending_clp`, `status`, `has_email`, `pending_proof_id`, `refundable_payments` and, on an open line when the gym uses WhatsApp, `whatsapp_url`, a reminder |
| `PATCH` | `/api/extra-charges/{id}/lines/{line_id}` | `{"amount_clp"}`: the person's amount, overridden. 409 below what they have paid, or on a cancelled line |
| `GET` | `/api/extra-charges/{id}/lines/{line_id}/cancel` | `{resplit_allowed, amounts}`: whether cancelling the line could divide the total again among the others, and each one's amount if so, overrides kept. Only a split none of whose lines has a payment, a refund or a pending proof; an adjustment moves no money and does not count. Read under the cobro's lock, shared |
| `POST` | `/api/extra-charges/{id}/lines/{line_id}/cancel` | `{"resplit"?}`: anular. 409 for a line the gym holds money for (its validated payments less their refunds; an adjustment is not money) or a proof waiting (refund it first), or a `resplit` the preview does not allow. Answers the cobro |
| `POST` | `/api/extra-charges/{id}/lines/{line_id}/payments` | `{"amount_clp", "method", "note"?}`: 201 with `{payment, credit, period}` as `POST /api/ledger/payments` answers, `period` being the line and `credit` always `null`; the receipt is emailed. 409 for a line paid in full or cancelled |
| `POST` | `/api/extra-charges/{id}/lines/{line_id}/adjustments` | `{"amount_clp", "note"}`: as `POST /api/ledger/adjustments`, for the line |
| `POST` | `/api/extra-charges/{id}/lines/{line_id}/notify` | email the person their amount again: `{sent, without_email}` |
| `POST` | `/api/extra-charges/{id}/remind` | "Recordar a los pendientes": email every `open` line what is left of it, `{sent, without_email}` |
| `GET` | `/api/people/{id}/extra-lines` | the person's lines still owed, as `/api/me/extra-lines` gives them: "Cobros extra pendientes" on their ficha. 404 for someone not in the gym |
| `GET` | `/api/me/extra-lines` | any session: the lines the signed-in person can pay, theirs and their dependents', earliest due first, each with its cobro's `title`, `category`, `message` and `due_date`. `/api/me/page` carries them as `extra_charges`, and its `payments` name a line's cobro in `charge_title` |

The ledger book lists a line's entries with `extra` (`id`, `title`, `category`) in place of a plan and period, and `membership_id` and `plan_name` `null`; its search and `kids` filter find them by the line's person. Cobrado counts them, as `v_monthly_income` counts every payment, and `kpis.collected_extra_clp` is what of it the cobros brought in, net of their refunds: `v_monthly_income.extra_income_clp`. The proof queue (`GET /api/ledger/proofs`) lists a line's proofs among the periods', oldest claim first, with `extra_line` (`id`, `extra_charge_id`, `title`, `category`, `due_date`, `amount_due_clp`, `paid_clp`, `outstanding_clp`) in place of `period`, and `membership_id`, the plan and `period` `null`, `prior_balance_clp` 0 and no `last_payments`.

### Groups

A group (`charge_group`, `0037`) is a named list of people a cobro can target, "Clasificados final" or "Competidores kids": built from the member list's filters plus people picked by hand and saved as a fixed list, a snapshot rather than a live filter. Names are unique in a gym, ignoring case. Any staff role may list them, a coach for rosters; reading who is in one and changing it is an owner's or admin's (`AdminSession`), and RLS lets only an owner or admin write either table. Deleting a group leaves the cobros that targeted it as they are.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/groups` | every group by name, with its `size` |
| `GET` | `/api/groups/{id}` | `{id, name, members}`, each member's `id` and `name` |
| `POST` | `/api/groups` | `{"name", "person_ids"}`: 201 with the group. 409 for a name the gym has, 422 for someone not in it |
| `PUT` | `/api/groups/{id}` | the same body: renames it and replaces who is in it |
| `DELETE` | `/api/groups/{id}` | 204 |

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
| `POST` | `/api/memberships` | start `person_id` on `plan_id` from `started_on` (default: today in the gym's timezone; at most 5 years either side of it); 201 with the membership, billed at once for what the nightly job would bill it tonight, its first 24 periods at most (`bill_now`, #196: a start back-dated further leaves the rest to the job), so a member who pays on their first day is recorded then. Reactivar on a plan and an accepted join request start one the same way |
| `GET` | `/api/memberships?person_id=…` | a person's memberships in this gym, latest first |
| `GET` | `/api/memberships/{id}` | one membership; 404 for another gym's |
| `POST` | `/api/memberships/{id}/plan-change` | `{"plan_id": …}`: move to that plan from the next period; the membership's own plan withdraws a pending change |
| `POST` | `/api/memberships/{id}/freeze` | `{"from_date"?: …, "to_date": …, "reason": …}`: freeze from `from_date` (today, in the gym's timezone, when omitted; at most 365 days ahead) until `to_date`, the day it is Active again (after `from_date`, at most 365 days on); a reason of 1 to 500 characters is required. 200 with the membership: `frozen` with its `freeze` from today, still `active` with the `freeze` booked (`started: false`) from a later day. 409 while another freeze is booked |
| `PATCH` | `/api/memberships/{id}/freeze` | `{"to_date"?: …, "reason"?: …}`, at least one: a new end or reason for the freeze running or booked. A running freeze's new end is after today; a booked one's after its `from_date`; at most 365 days after its first day either way. 409 with no freeze running or booked |
| `POST` | `/api/memberships/{id}/freeze/end` | end the freeze running today, back to `active`, or call off the one booked. 409 with no freeze running or booked |
| `POST` | `/api/memberships/{id}/cancel` | `{"reason": …}`: cancel for good; a reason of 1 to 500 characters is required |

Dates are calendar dates in the gym's timezone (`app.domain.dates`), and `started_at` is stored as the first instant of `started_on` there. What a membership starts with follows its plan (`app.domain.membership.start`): a monthly or prepaid one is paid through the day before it starts, so its first period falls due on the start date, and a monthly one bills on `anchor_day`, its start day for a `signup` anchor or the 1st for a `first` one. A credits pack starts with its credits and lasts `credit_expiry_days`; a trial starts in `trial` with its free classes and free days. A drop-in is not a membership, and a deactivated plan, or a person or plan this gym does not have, is a 422.

A plan change waits for the next period; proration is v2. Only a monthly or prepaid membership changes plan, to another monthly or prepaid plan (a pack or trial ends, and a trial converts on payment). The change is stored as `next_plan` with the day it `starts_on`: the day after the paid-through date, or after the last billed period if billing has run ahead, so a period already billed keeps its plan and amount. Billing (#31) prices a period starting on or after that day at the new plan and moves it into `plan_id`, recomputing `anchor_day` with `domain.anchor_day(new_terms, next_plan_from)`, so a move to a `first` anchor bills on the 1st and a move to prepaid clears it. Starting a membership emails the member, or their guardian, a welcome after it commits: the plan, the gym's bank details (or, with none set, that the student page has them), how to upload a proof, and their first sign-in link. A member with no email gets none. Cancelling follows the state machine: an active or lapsed membership can be cancelled, a trial or frozen one cannot (409), and a cancelled one changes no more (409). It drops a pending plan change. Any staff role may read memberships; only an owner or admin may start, change, freeze or cancel one.

A freeze (#26) is a side trip from Active: only an active membership freezes (a trial, a frozen, a lapsed or a cancelled one is a 409), from today until `to_date`. The days in between are not charged, and the due date moves past them as the freeze starts, so the member reads the day they next pay on all through it: billing resumes after the later of `current_period_end` and the last period that started before today, so that moves by the frozen days; every billing period starting today or later moves by them too, `period_start`, `period_end` and `due_date` alike (a charge already written stays on its period); a monthly plan's `anchor_day` becomes the day after the new `current_period_end`; and a pending plan change's `next_plan_from` moves with them. A credits pack's expiry moves the same way. The freeze is a `membership_freeze` row (`0017`), written with a `frozen` `plan_event`, and a membership read carries it as `freeze` (`id`, `from_date`, `to_date`, `reason`, `started`) while frozen. The nightly `freezes` job returns it to Active on `to_date`. Payments may still be recorded against a frozen membership's periods: what it owed before the freeze, it still owes.

A freeze can change after it is written (#115, migration `0027`); `rakin_app` may update its `to_date` and `reason`, never its first day. Ended early (`POST …/freeze/end`), the membership is Active again today and the due date moves back by the days the freeze no longer lasts: `current_period_end`, the billing periods it moved (those starting on or after its first day), `anchor_day` and `next_plan_from`, all by the same days. Its `to_date` becomes today, and an `unfrozen` `plan_event` records who ended it (`created_by`, null on the job's) and when (`created_at`). Plan events are one per membership, kind and day, deliberately: a freeze ended, frozen again and ended again the same day keeps the first `unfrozen` event, so the member is told once and `created_by` names whoever ended it first. One ended on its first day froze no day: its `to_date` is its `from_date`, it lists no ledger lines, and the membership may freeze again that day. A freeze whose end has passed but that the job has not yet ended ends where it was. A new end (`PATCH …/freeze`) moves the same dates by the days gained or lost. A freeze from a later day is booked: the membership stays Active, nothing moves, and the row waits with `started` false until the `freezes` job starts it on `from_date`, moving the dates then. A booked freeze can change its end or reason, or be called off (`POST …/freeze/end`, which sets its `to_date` to its `from_date`); cancelling the membership calls it off too, and so does the job when the membership is no longer Active on its first day. While one is booked the membership takes no other freeze. A membership read carries a booked freeze as `freeze` while Active.

## Sessions API

One `session` row per class (migration `0020`, [spec](../docs/technical.md#domain-model)). The weekly schedule (below) makes most of them ahead of time; a coach may also start one when the class begins, and writes its topic and notes during or after it. A session may carry `duration_minutes` (1 to 1440, `0035`), and one made by the schedule its `slot_id` and `slot_date`, the gym-local date it was made for, which it keeps when it is moved on its own.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/sessions` | `{"date", "timezone", "sessions": […]}`: the sessions starting on `?date=` (an ISO day; default today), a calendar day in the gym's timezone, earliest first |
| `POST` | `/api/sessions` | start one: `class_type_id`, and optionally `starts_at` (with its offset; default now), `duration_minutes`, `coach_id` (default the person acting), `topic`, `notes`; 201 with the session |
| `GET` | `/api/sessions/unmarked` | `{"since", "timezone", "sessions": […]}`: the sessions already started since `since`, six days before today in the gym's timezone, that no one is marked at, latest first; owner and admin only, for the dashboard's "Sin asistencia" |
| `GET` | `/api/sessions/{id}` | one session; 404 for another gym's |
| `PATCH` | `/api/sessions/{id}` | change `topic`, `notes` or `coach_id`; only what is sent changes |

A session carries its `class_type_id` and `class_type_name`, `program_id` and `program_name`, `starts_at`, `coach_id` and `coach_name` (the gym's record of them), `topic`, `notes`, `created_at` and `updated_at`, and `present`, how many are marked at it: 0 is a class whose attendance was never taken, which the Clases list flags. A topic is up to 200 characters and notes up to 4,000; a blank one, or `null`, is none. The class type must be one of the gym's active ones (422 `unknown_class_type` or `inactive_class_type` on `class_type_id`), and the coach on its staff in any role (422 `unknown_coach`) when a session is started or reassigned: a coach who leaves stays the coach of the sessions they taught, since the row references `gym_person`, not `staff`. Any staff role may read, start and edit sessions, coaches included, but only an owner or admin lists the unmarked ones; there is no delete, since attendance points at a session.

## Weekly schedule API

The gym's timetable (#167, migration `0035`): owner and admin only, reads included.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/schedule` | every slot, ended ones included, by first weekday and start time |
| `POST` | `/api/schedule` | a slot: `class_type_id`, `weekdays` (ISO, 1 is Monday), `start_time` (local, `19:00`), `duration_minutes`, `coach_id`, and optionally `topic`, `valid_from` (default today) and `valid_to`; 201, its classes made at once |
| `PATCH` | `/api/schedule/{id}` | change it from `from_date` on (default today); only what is sent changes, `valid_to: null` makes it open-ended; returns the slot in effect from then |
| `DELETE` | `/api/schedule/{id}` | the slot and its classes that have not started and have no attendance; 204 |
| `GET` | `/api/closed-days` | the closed days from today on: `{"day", "label"}` |
| `PUT` | `/api/closed-days/{day}` | close a day, or relabel it: `{"label"}`, optional |
| `DELETE` | `/api/closed-days/{day}` | reopen it; 204 |

A slot makes one session per date it runs on, from today through 13 days ahead in the gym's timezone (`app.domain.schedule.HORIZON_DAYS`), at its start time on that date's wall clock, with its class type, coach, duration and topic: when it is saved, and every night (`schedule` job). None is made on a closed day, nor by a slot whose class type is deactivated. `UNIQUE (slot_id, slot_date)` makes a second run make nothing, and the nightly run only adds the dates after the last one a slot made, so a class deleted on its own stays deleted.

A change from `from_date` never touches a class before it, or one that has started or has attendance. From after the slot's `valid_from`, it ends the slot the day before and starts a new one with the change, so the timetable before it reads as it was. The classes from `from_date` on that it may change are moved to the new time with the new type, coach and duration, and the new topic where they still had the old one; cancelled ones stay cancelled. Those on a weekday the slot no longer runs, or after its `valid_to`, are deleted, and the dates it now runs on get one. Refused: a `from_date` after the slot ends (422 `after_valid_to`), a `valid_to` before the slot starts (422 `before_valid_from`), the class type and coach as for sessions, and a change to an open mat while one of those classes has a timer plan that does not fit one (422 `open_mat_plan`). "Solo esta clase" is `PATCH /api/sessions/{id}`.

Closing a day deletes that date's classes of the schedule that have not started and have no attendance; reopening one within the horizon makes them again.

## Attendance API

One `attendance` row per membership present at a session, at most once: `(session_id, membership_id)` is its key (migration `0023`). It records `marked_by`, `marked_at` and `credits_consumed`. Rows are added and deleted, never changed: tapping a name marks it and tapping it again unmarks it.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/sessions/{id}/roster` | `{"session_id", "present", "members": […]}`: everyone with a trial, active, lapsed or frozen membership whose plan is in the class type's program or open to any class (no program), one row per person, and anyone already marked; by name |
| `PATCH` | `/api/sessions/{id}/attendance` | `{"mark": [membership ids], "unmark": [membership ids]}`, at most 500 each and never the same id in both; 200 with the roster. Idempotent: marking someone already present or unmarking someone who is not changes nothing, so an offline phone can resend its queue |
| `POST` | `/api/sessions/{id}/trials` | `{"person_id", "plan_id"}`: start the person on one of the gym's active trial plans from today, marked present; 201 with the roster. 409 `{"code": "already_member", "membership_id"}` when they already have a trial, active or frozen membership, to mark that one instead |
| `GET` | `/api/people/{id}/attendance` | `{"last_30_days", "total", "since_promotion"}`: the person's classes over every membership they hold here, today and the 29 days before it, in all, and since the day of their current rank (that day's classes not counted), `null` with no rank |

A roster row carries `membership_id`, `person_id`, `name`, `rut` (for the screen's search), `plan_name`, `plan_kind`, `status`, `credits_remaining`, `overdue`, `days_absent` (days since their last class before this one, `null` for a first), `regular` (they came to a class of this one's type in the 30 days before it; the screen lists them first), `rank` (as `GET /api/people/{id}/grades` gives `current`) and `present`. A person with two memberships appears once: by the one marked present, else their active one, else trial, else lapsed, else frozen, latest first. A frozen member who turns up is marked for nothing and stays frozen.

Marking spends what the membership pays the class with (`app.domain.attendance`): a credits pack the class type's `credit_cost`, a trial one of its free classes whatever the class costs, and nothing on any other plan. It takes what is left and never refuses: a spent pack, or a lapsed or frozen membership, trains for nothing, since overdue and lapsed members can still train. The nightly `lapse` job lapses a pack at zero, not the mark, so unmarking a mistake the same day gives the credits back and leaves the membership as it was. A mark and a trial guest are held to the roster's rule: a cancelled membership is a 422 `cancelled_membership` on `mark`, any other status the roster does not list `not_on_roster`, one this gym does not have `unknown_membership`, and a membership or trial plan for another program `not_in_program`; a trial guest's other 422s are `unknown_person`, `not_a_trial_plan` and `inactive_plan`. "The last 30 days" is one definition, today and the 29 days before it in the gym's timezone (`app.api.attendance.recent_from`), for `last_30_days` and the proof queue's `attendance_30d`.

`overdue` is whether the membership has a period in `v_overdue`. A coach reads no ledger entries (`0006`), so the roster asks `overdue_memberships()`, a `SECURITY DEFINER` function that returns the current gym's overdue membership ids and nothing else.

Any staff role may use it, coaches included; a coach may start a trial where only an owner or admin may start any other membership, since a trial charges nothing. A trial added at the mat sends no welcome. Members may not use it; the student page carries their own counts (`attendance` on `/api/me/page`).

## Class timer API

A coach runs a class from a timer as a sequence of blocks (#136): warm-up, technique, games, sparring rounds. Migration `0028` stores the gym's block kinds, whether a class type is an open mat, and each session's blocks: the plan and what ran. A student's time is the blocks of every session they attended.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/block-kinds` | the gym's block kinds in its order, archived ones last; `?archived=false` for the ones to plan |
| `POST` | `/api/block-kinds` | `{"name", "is_sparring"}` (default `false`): a new kind, last in the order; 201. 409 when the name is taken, case ignored |
| `PATCH` | `/api/block-kinds/{id}` | change `name`, `is_sparring` or `archived`; only what is sent changes |
| `PUT` | `/api/block-kinds/order` | `{"ids": […]}`: every kind of the gym, once each, in its new order; anything else is a 422 |
| `DELETE` | `/api/block-kinds/{id}` | 204; 409 `{"code": "block_kind_in_use", "blocks"}` when sessions' blocks are of it, as for an `is_sparring` change |
| `GET` | `/api/sessions/{id}/blocks` | `{"session_id", "class_kind", "blocks": […]}`: the plan in order |
| `PUT` | `/api/sessions/{id}/blocks` | `{"blocks": […]}`, at most 30: the whole plan, replaced. A block kept by `id` keeps what it recorded; one left out is dropped with it |
| `PUT` | `/api/sessions/{id}/blocks/{block_id}/actual` | `{"actual_seconds", "rounds_completed"}`: what the block ran; 200 with the block |
| `GET` | `/api/sessions/{id}/blocks/suggested` | `{"session_id", "from_session_id", "blocks": […]}`: the plan of the latest other session of the same class type that has one, without ids, actuals or archived kinds; none when there is no such session |
| `GET` | `/api/people/{id}/time` | `{"timezone", "month_start", "this_month", "all_time"}`, each `{"by_kind", "sparring_seconds", "open_mat_seconds", "classes", "open_mats"}` |
| `GET` | `/api/me/time` | the signed-in person's own time, as above: the student page's "Tu tiempo de entrenamiento" |

Every gym starts with six kinds, Calentamiento, Técnica, Drilling, Juegos, Sparring (`is_sparring`) and Otro: a trigger on `gym` gives a new gym them, and the migration gave the gyms already there theirs. Their ids are derived from the gym's (`block_kind_default_id`, and `app.seed.build.default_block_kind_id` in Python), so the seed points at them. A kind in use is archived rather than deleted, and planned no more; a block already of it may stay in a replanned session.

A class type is a class or an open mat (`kind`, `class` or `open_mat`), and `counts_as_class` says whether attending one counts as a class: by default true for a class and false for an open mat, also when a `PATCH` changes `kind` without it. Every class count leaves out the sessions of a class type that does not count: `GET /api/people/{id}/attendance`, `attendance` on `/api/me/page` (and so the goal progress tile), and the proof queue's `attendance_30d`.

A plan block names its `block_kind_id` and, optionally, its own `id`, so a phone resending its plan offline keeps what each block recorded. A block of a sparring kind sends `rounds_planned` (1 to 100), `round_seconds` (1 to 3,600) and `rest_seconds` (0 to 3,600); its `planned_seconds` is `rounds_planned × round_seconds`, rest not included, at most four hours (422 `planned_seconds_mismatch` if sent otherwise). Any other block sends `planned_seconds` (1 to 14,400) and no rounds (422 `missing`, `not_sparring`). An unknown kind is a 422 `unknown_block_kind`, a newly planned archived one `archived_block_kind`, and an open mat's plan that is not one sparring block `open_mat_plan`. An `id` that is another session's block is a 409. A block kept by `id` with the same kind keeps what it recorded, its `rounds_completed` cut to the rounds now planned and its seconds to what those allow; one given another kind starts unrecorded, since what ran was of the kind it ran as. Changing a class type to an open mat later leaves the plans its sessions already have as they were run; only a new `PUT` is held to the one-block rule.

An actual replaces what the block had, so the timer's queue may retry: `actual_seconds` (0 to 14,400; a block stopped early records less), and for a sparring block `rounds_completed`, at most the rounds planned (422 `missing`, `less_than_equal`, or `not_sparring` on another block). A sparring block's seconds are the rounds', rest not included: at most the completed rounds and part of the next one, if one was planned (`sparred_at_most`), so 3 of 5 rounds of 300 s record at most 1,200, and more is a 422 `less_than_equal` on `actual_seconds`. The timer (#139) sends the time spent in rounds, never the clock time with the rests.

A block carries `id`, `position`, `block_kind_id`, `block_kind_name`, `is_sparring`, `planned_seconds`, `actual_seconds` (`null` until run), `rounds_planned`, `rounds_completed`, `round_seconds` and `rest_seconds`.

A person's time is every block of each session they were marked present at, counted once even with two memberships marked, and whole: someone who arrived late gets it all. `by_kind` is the seconds each kind ran, kinds with any, in the gym's order; `sparring_seconds` sums the sparring kinds, open mats included; `open_mat_seconds` is the open mats' time alone; `classes` counts sessions of a class type that counts as a class and `open_mats` those of an open mat. `this_month` is from the 1st in the gym's timezone (`month_start`).

Any staff role may read all of it, coaches included, since none of it is money. A member reads only their own time, on `/api/me/time`. Only an owner or admin changes block kinds; the plan and its actuals are the session's coach's, or an owner's or admin's (403 for another coach).

## Member import

Onboarding a gym is mostly bringing its spreadsheet over. The admin uploads the file, says what each column is, checks it, then imports; the SPA's screen is `/admin/alumnos/importar`. Only an owner or admin may, since it starts memberships.

| Method | Path | Does |
| --- | --- | --- |
| `POST` | `/api/import/sheet` | the file itself as the body, CSV or XLSX, up to 5 MB. Answers `{headers, rows: [{number, cells}], mapping}`, the mapping a suggestion from the headers. Nothing is stored. 413 `{"detail": {"code": "too_large"}}`; 422 with `unreadable`, `empty`, `too_many_rows` (over 2,000) or `too_many_empty_rows` (more than 20,000 rows scanned, empty ones included, as an XLSX formatted to its last row would be) |
| `POST` | `/api/import/members` | `{rows, mapping, plans?, dry_run}`: the rows sent back, `mapping` field to column (`name` required, one column per field), and `plans` a plan cell's value to the plan it means, for values that are not a plan's name, or to `null` for no plan. `dry_run` defaults to true. Answers each row's `errors`, what it did (`created` or `existing`) to the `person`, `guardian`, `link` and `membership`, and the fields it leaves unapplied (`ignored`), with a `summary` |

The fields are `name`, `last_name` (joined to the name), `phone`, `email`, `rut`, `dob`, `plan`, `due_on`, `started_on`, `guardian_name`, `guardian_rut`, `guardian_email` and `guardian_phone`. `app.member_import.sheet` reads an XLSX's first worksheet, or a CSV in UTF-8 or Windows-1252 (Excel in Spanish) with a comma, semicolon or tab; every cell comes back as text, dates as `YYYY-MM-DD`. Dates in cells may be ISO or day first (`05/12/2026`, `5-12-26`). `app.member_import.rows` makes every check that needs only the row, and reports each with its `field` and a `code`: `required`, `repeated`, `invalid_phone`, `invalid_email`, `invalid_rut`, `invalid_date`, `own_guardian`, `unknown_plan`, `inactive_plan`, `dropin_plan` or `due_before_start`.

A row with a RUT, or an email and no RUT, is someone found again by it, as `join_gym` finds anyone; the phone is a contact and finds nobody. A row with neither and a guardian is a dependent, found by their guardian and their own name among that guardian's dependents. A row with neither and no guardian, as old sheets have, still imports, flagged `missing_identity` (the person shows "Falta RUT"): it is found again by its name among this gym's people who are nobody's dependent. When two of the gym's people share the name, the birth date and then the phone tell them apart, only inside the gym: a value both give that differs means someone else, one that matches picks them out, and when neither settles it the row is refused `ambiguous_name` ("Nombre repetido: agrega RUT o correo"). An earlier row of the same name that nothing tells apart makes it `repeated`. A guardian is found by `guardian_rut` or `guardian_email`, or, named alone, as the person their own row in the sheet is, else by name (and phone) in this gym the same way; one not yet in the gym is added with `guardian_name`, and a `guardian_phone` with no guardian named is refused. Every way in (people, Nuevo alumno, invites, the import, the join link) finds someone with one lookup, `app.api.people.find_in_gym`: by RUT in the gym, else by email, and with a RUT only someone with no RUT of their own; one found by email takes the RUT (`claim_rut`). A row with a RUT or email that finds nobody, but names someone this gym has with neither, is them: their record takes both, refused `rut_in_gym` or `email_in_gym` should another person here have either. Names are folded in Python, accents and case ignored (`rows.fold`), the same fold for the gym's names and the sheet's. A row with both is someone with their own RUT or email and a guardian, such as a teenager. A row with no phone for whom the gym messages (the guardian, for a dependent) is not refused: it imports with `missing_phone`, counted in the summary, and the member shows "Falta teléfono". The links follow the family rules, so `has_guardian` and `one_level` come back as row errors too. A row with a plan gets a membership (`domain.membership.imported`): a monthly or prepaid one is paid through the day before `due_on`, and a monthly one bills on `due_on`'s day, or the 1st on a `first` anchor. It starts on `started_on`, or else today, or `due_on` if that is earlier. A pack or trial starts as it would today, lasting through `due_on` when that is given. A monthly or prepaid plan needs `due_on`. A plan value mapped to `null` imports the person with no membership, whatever plan it names, and its row's dates are not read.

Each row is written in a savepoint of its own: a refused row writes nothing, and the others still import. A dry run writes every row the same way and then rolls the lot back, so it reports what the database itself refuses, and its report is the import's. Guardians' own rows go first, then the other rows with a RUT or email, then dependents, so a row naming a guardian by RUT or email finds the guardian the sheet describes further down, with the name their own row gives. Running it again creates nothing twice. An import never overwrites what the gym has: whoever is found keeps the record this gym has of them, and a membership that is not cancelled keeps its plan and dates. Each row's `ignored` names the sheet's fields that differ from what is kept, so the dry run shows it first. A row refused the first time imports once it is fixed. RUTs already known to another gym join this one as `POST /api/people` does, with what the sheet says.

`tests/fixtures/pilot_sheet.csv` stands in for the pilot gym's sheet, with invented people: Excel's semicolon CSV, phones written every which way, kids under their parent, and one row for each way a row goes wrong. `tests/test_member_import.py` runs it end to end. The pilot's real sheet is never committed here, not even anonymised; it is tried outside the repo.

## Gym settings API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/gym/settings` | the current gym's `name`, `slug`, `timezone`, `grace_days`, `reminder_every_days`, `channels`, `bank_account` and `privacy`; a setting never stored reads as its default (5 grace days, a reminder every 3 days, WhatsApp on, no bank details, no privacy details) |
| `PATCH` | `/api/gym/settings` | change any of those but `slug`; `channels`, `bank_account` and `privacy` are replaced whole, `bank_account: null` clears the bank details, and `privacy` cannot be cleared |
| `PUT` | `/api/gym/logo?x=&y=&size=` | the gym's logo (#223): the picture as picked is the body, with its `Content-Type`, and the square to keep in its upright pixels (all three, or none for the middle square); answers the settings |
| `DELETE` | `/api/gym/logo` | "Quitar logo"; answers the settings |
| `GET` | `/api/logos/<gym_id>/<version>/<variant>` | a logo's file, to anyone, with no session |

Owner and admin only (`AdminSession`); a coach or member gets a 403, since the bank details decide where students send their money. `name` and `timezone` are columns on `gym`; the rest are keys of `gym.settings`, and the grading scheme and custom fields stored beside them are left untouched. `timezone` must be an IANA name, `grace_days` 0 to 60, `reminder_every_days` 1 to 30. `bank_account` takes `bank`, `account_type` (`Cuenta Corriente`, `Cuenta Vista`, `Cuenta RUT` or `Cuenta de Ahorro`), `holder`, `rut` (normalised to `76123456-0`), `number` and an optional `email` for the transfer notice. Email is always on, so `channels` holds only `whatsapp`. `privacy` is what the gym's privacy notice names it by, as the controller of its members' data (#168): `legal_name`, `rut` (normalised), `email` for requests about personal data and an optional `address`; each save stamps it with the gym's `updated_on`, in the timezone the same change leaves it in.

The logo (#223, `app.logos`) takes a PNG, JPEG or WebP of up to 5 MB and never an SVG, which can carry script; anything else is a 415 `logo_type`, a 413 `logo_too_large` (so is a small file that unpacks past 50 megapixels) or a 422 `logo_unreadable`, read from the bytes, not the header. The server turns it upright, cuts the square and draws `512.webp`, `128.webp`, `64.webp` and, for email, `128.png` afresh, so no EXIF or other metadata survives. They go to the blob store under `logos/<gym_id>/<version>/`, and `gym.logo_version` (0040) names the current set: a new upload is a new version, the old files are deleted once the change is saved, and the settings answer `logo`, the path the files are under (`null` with none). Since a version's files never change, `GET /api/logos/…` serves them with a year's `immutable` cache; the API reads them itself (`BlobStore.get`), so the URL is the app's own on R2 as on local disk and never expires. The pages before sign-in show it like the theme: `rakin_auth` may read the one column, `auth_gym_by_slug` returns it, `/api/host`, the join form and the privacy notice carry it, the sign-in link's pages show it (`img-src 'self'`), and `GymLookup.forget` makes a change show there at once. `/api/me/role` carries it as `gym_logo`, and every email of a gym with one shows it round over the message, `128.png` on the gym's host, with the gym's name as its `alt`.

## Privacy notice

Each gym has a public privacy notice at `/privacidad` on its host (#168), linked from the join form's consent checkbox and the student page's footer. The text is a Spanish template in the SPA (`t.privacy` in `frontend/src/i18n/es.ts`, its subprocessors listed once there), filled in with the gym's `privacy` settings; its "last updated" is the later of the template's date (`TEMPLATE_UPDATED_ON` in `frontend/src/api/privacy.ts`, moved with any change to the text) and the gym's `updated_on`.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/privacy` | no session: `{gym, legal_name, rut, email, address, updated_on, human_check}` (`human_check`: whether `HUMAN_CHECK` is on, so the notice names that provider only then) for the gym the host names, else the session's gym, else the one whose join link `?link=` is (the join form on the shared host). 404 `no_privacy_notice` for a gym that has not filled in its details, or no gym at all |

Until the details are set, the join link cannot be generated (`POST /api/join-link`, 409 `privacy_incomplete`), and a link made before them answers 404 `invalid_link`, since its form would ask for consent to a notice that does not exist.

## Staff API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/staff` | the gym's staff, the owner first, then admins, then coaches, each by name: `person_id`, `name`, `phone`, `email`, `role` and `since` |
| `POST` | `/api/staff` | invite: `{phone, name, email, role}` with `role` `admin` or `coach`; 201 with the new staff member, whose record here takes the invite's email and who is emailed a link to it (it signs in to this gym only, `0029`), 409 `{"code": "already_staff", "person_id"}` for someone already on the staff |
| `PATCH` | `/api/staff/{person_id}` | `{role}`: move them between `admin` and `coach`; the role they already have changes nothing |
| `DELETE` | `/api/staff/{person_id}` | revoke their role; 204 |

A role is a `staff` row for the person and the gym (`app.roles`), read on every request, so an invite, a change or a revoke takes effect on the next one. An invite adds the person the way `POST /api/people` does (`join_gym`): by their `rut` when given, so a RUT another gym knows attaches that person with what this gym entered, else by the email in this gym; someone this gym already has, a member say, keeps their record and gains the role. The `phone` is optional: staff need none. The email is required, since staff sign in by a link to it, and becomes the gym's record of their email. After the staff row commits it emails them a `staff_invite` with a 7-day sign-in link that lands on the admin screens rather than the student page. Revoking deletes the staff row and nothing else: the gym keeps its record of them, and the classes they taught keep them as coach. Without a membership either, their session in the gym ends at once (`auth_live_session`, migration 0005); they can be invited again.

Owner and admin only (`AdminSession`), and an admin manages coaches only: inviting an admin, moving anyone to or from admin and revoking an admin are the owner's, so an admin cannot step down either. The owner's row is never changed or revoked here (403), so a gym always keeps its owner. Someone not on this gym's staff is a 404.

## Join link

A gym shares one link (WhatsApp, a poster, anywhere), and people fill in their own details on their phone (#154). What they send is a request, not a member, until staff approve it. The SPA serves the form at `/unirse/<token>`, and the link is on the gym's own host (`<slug>.BASE_DOMAIN`, `app.hosts`), or on `PUBLIC_BASE_URL` when `BASE_DOMAIN` is empty.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/join-link` | the gym's link: `url`, `token`, the `program_id` and `program_name` it pre-selects, `expires_on` (its last day, in the gym's timezone) and `expired`; 404 when it has none |
| `POST` | `/api/join-link` | `{program_id?, expires_on?}`: a new link, with a new token, so the old one stops working; 201. 422 `unknown_program` for a program this gym does not have; 409 `privacy_incomplete` until the gym's privacy details are set ([Privacy notice](#privacy-notice)) |
| `PATCH` | `/api/join-link` | change `program_id` or `expires_on`, keeping the token; `null` clears either |
| `DELETE` | `/api/join-link` | revoke it; 204. Requests already sent stay in the queue |
| `GET` | `/api/join/{token}` | no session: what the form shows, `{gym, program, today, human_check_site_key}`. 404 `invalid_link` for a token that is unknown, malformed (a truncated link), revoked, regenerated or past its last day, or a gym with no privacy details |
| `POST` | `/api/join/{token}` | no session: `{first_name, last_name, rut, phone, email, dob, guardian_name, guardian_phone, guardian_email, no_whatsapp, consent: true, website, human_check_token}`; 202 with no body |
| `GET` | `/api/join-requests` | `?limit=` (1 to 200, 50 by default) and `?offset=`: `{items, total}`, the queue oldest first, each with `rut_in_gym` (whoever in this gym already has its RUT), `email_in_gym` (for a request with no RUT, whoever here has its email) and `ignored_email` (the request's email when approving leaves it unused, since whoever here has that RUT keeps the email this gym has for them) |
| `POST` | `/api/join-requests/{id}/approve` | `{plan_id?}`: adds the person, or links whoever here has the RUT (or, with none, the email), and deletes the request; `{person_id, membership_id}`. A `plan_id` is owner and admin only (403 for a coach); 409 `{"code": "has_membership", "field": "plan_id"}` with a plan for someone who already holds a live membership here, and `has_guardian` or `one_level` for a family link the gym cannot make |
| `DELETE` | `/api/join-requests/{id}` | reject: the request is deleted; 204 |

Owner and admin manage the link (`AdminSession`). Every staff role sees the queue and approves (`StaffSession`), but only an owner or admin may give a plan, since a plan is money: approved with none, the member is in the list "sin plan" until one is started.

The form takes the RUT with its check digit, optional for someone who has none, and a Chilean mobile, normalised as everywhere else (`app.domain.rut`, `app.domain.phone`). Whoever is under 18 on the gym's today (`ADULT_AGE`) must give a guardian's name, phone and email, and may leave their own phone and email out; a minor's phone or email that is the guardian's is dropped, since it is not their own. An adult needs an email and a phone, and any guardian fields they send are ignored. `no_whatsapp` ("No tiene WhatsApp") lets the adult, or a minor's guardian, leave the phone out; approving keeps it on the new record. `consent` must be `true`, and is recorded as `consented_at`. The answers never say whether a RUT or email is already someone's, here or in another gym: a submission is a 202 whatever it holds.

A submission is checked cheapest first: the link (404), then the fields (422), then the honeypot, then the rate limits, and last the human check, so a made-up token or a form that would be refused spends neither a limit nor a call to Cloudflare. The limits are in memory (`app.magiclink.ratelimit`), 20 an hour per client IP (a class signing up on the gym's WiFi is one IP) and then 100 an hour per link, with a 429 and `Retry-After`; the IP is the browser's, which uvicorn takes from Caddy's `X-Forwarded-For` (`FORWARDED_ALLOW_IPS` in both compose files). `website` is a honeypot, a field the form keeps out of sight: filled in, the answer is the same 202 and nothing is stored. With `HUMAN_CHECK=turnstile` the form shows Cloudflare's widget and its token must pass `siteverify` (400 `human_check_failed`). That call runs with no database connection held, since it is an HTTP round trip and the pool is small (#162); the request is written in a second transaction that finds the link again, so a link revoked during the check stores nothing (404 `invalid_link`). The form starts the widget over after any failed submission, since a token is good once. `HUMAN_CHECK=turnstile` without both `TURNSTILE_*` keys is refused at startup.

Approving writes the person through the importer's writer (`app.api.member_import.Writer`), so they are added exactly as a row of the gym's spreadsheet is: found by RUT in this gym, or by email with no RUT, and left as this gym has them, email included, else joined (`join_gym`, so a RUT another gym knows attaches that identity without this gym learning so); a minor is found or added under their guardian, who is found by their email or added with the request's name, email and phone, and linked. A new person's record takes the request's email, which signs in to this gym only (`0029`); the queue shows which emails a kept record leaves unused. Someone who already holds a live membership here is linked with no plan and no email, and refused with a plan (409 `has_membership`), so nobody is billed twice. With a plan, a membership starts on it today (`app.api.memberships.start_membership`, as `POST /api/memberships` does) and the `welcome` goes out with its sign-in link. Without one, `join_approved` tells them, or their guardian, that they are in, with no sign-in link; they can ask for one at `/ingresar` (#246), and the welcome brings it once a plan is started. The request is deleted either way, in the same transaction, so approving one twice at once adds the person once.

The public form knows a token, not a gym, so `join_link_gym(token)` (`0031`), a `SECURITY DEFINER` function owned by `rakin_auth`, answers which gym the token is for and nothing else; the form then acts with `app.gym_id` set to that gym, held to RLS like any request. A request is never kept long: approving or rejecting deletes it at once, and the nightly `join_requests` job deletes any left for 30 days.

## Custom fields API

Each gym defines its own fields on people (weight class, emergency contact, medical notes): `text`, `number`, `date` or `enum` ([spec](../docs/technical.md#sport-agnostic-design)). The definitions are a list in `gym.settings.custom_fields`, in the order the member detail shows them; values are rows of `person_field_value` (migration 0019), one per person and field.

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/custom-fields` | the fields the caller may see, in order, archived ones included: `key`, `label`, `type`, `options` (an enum's), `sensitive`, `visible_to`, `archived` |
| `POST` | `/api/custom-fields` | a new field from `label`, `type`, `options` (an enum's, and only there), and the owner's `sensitive` and `visible_to`; its `key` is made from the label and a random suffix (`Notas médicas` → `notas_medicas_3f9a`) |
| `PATCH` | `/api/custom-fields/{key}` | change `label`, an enum's `options`, `archived`, and the owner's `sensitive` and `visible_to`; the key and type are fixed. Removing an option people still hold is a 409, `{"code": "option_in_use", "options": {"Pluma": 2}}`, so no stored value is left naming no option |
| `PUT` | `/api/custom-fields/order` | `keys`: every field the caller sees, in their new order; fields the caller does not see keep their places |
| `GET` | `/api/people/{id}/fields` | the person's values for the fields the caller sees and that are not archived, in order; `value` is `null` when unset |
| `PATCH` | `/api/people/{id}/fields` | `values` by key; `null` (or blank text) clears one, keys not sent are kept |

Every staff role reads definitions and reads and writes values; defining, reordering and archiving is owner and admin (`AdminSession`). `visible_to` is who sees a field: `owner` (Solo dueño), `admin` (Dueño y administradores) or `staff` (Todo el staff, incluye coaches); the owner sees every field. It defaults to `owner` for a sensitive field and `staff` otherwise, and when the owner marks an existing field sensitive without naming a `visible_to`, it narrows to `owner`. Only the owner may set `sensitive` or `visible_to`: an admin who sends either gets a 403, so an admin can add fields but never widen who sees one. A field the caller may not see is answered as one that does not exist: it is left out of every list, a `PATCH` on its definition is a 404, and a value for it is an `unknown field`, the same as a key no field has. Every new key carries a random suffix, so a key made while a hidden field holds the plain one looks like any other.

A value must fit its type: text up to 1,000 characters (trimmed), a JSON number, a `YYYY-MM-DD` date, or one of the enum's options. A refused `PATCH` writes nothing and is a 422 whose `detail.fields` gives each refused key's reason. Archived fields keep their values but are neither shown nor written until unarchived.

A sensitive field's value is stored in `secret`, encrypted with AES-GCM under a key derived from `FIELD_ENCRYPTION_KEY` and bound to its gym, person and field, never in `value`; changing a field's `sensitive` flag re-encrypts or decrypts what it holds. A definition change reads `gym.settings` `FOR UPDATE` and a value write `FOR SHARE`, so a value written while the owner marks its field sensitive waits for that and is sealed. `FIELD_ENCRYPTION_KEY` is its own setting, not `SECRET_KEY`, so rotating `SECRET_KEY` after a leak touches no stored value; the API refuses to start in production with its local default. **Changing `FIELD_ENCRYPTION_KEY` makes stored sensitive values unreadable**: never change it without re-encrypting them, and keep it with the backups.

## Grading scheme API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/gym/grading-scheme` | the current gym's `ranks`, `kids_ladder` and `goal_metric`; a gym that never set one has none (`{"ranks": [], "kids_ladder": [], "goal_metric": null}`) |
| `PUT` | `/api/gym/grading-scheme` | replace it whole; answers the scheme as stored |
| `GET` | `/api/gym/grading-scheme/presets` | the starting points, `[{key, label, scheme}]`: `bjj`, `judo-karate`, `muay-thai` and `none` ([spec](../docs/technical.md#sport-agnostic-design)) |

A scheme is ranks in order, lowest first, each `{key, label, target, sub_ranks: [{key, label, target}]}`, plus an optional separate `kids_ladder` of the same shape and a `goal_metric` (`classes_since_promotion`, `time_in_rank` or `null`) for the v2 "ready for promotion" flag. A `target` is optional (`null` by default): how much of the goal metric a member needs in that rank or sub-rank before the next promotion, classes or months in rank, 1 to 10.000; a sub-rank's own target wins over its rank's, and a scheme with targets needs a goal metric. It is stored as `gym.settings["grading"]`, beside the other settings, which a change leaves alone. A preset is applied by sending its scheme, edited or not, to `PUT`; nothing records which preset a scheme came from, and no code branches on it (`app.domain.grading` holds the presets as data). Promotions name a rank and a sub-rank by key, so a rank's key is unique across the ranks and the kids ladder together, and a sub-rank's within its rank. Keys are lower-case letters, digits and single dashes, up to 40 characters; labels 1 to 60. At most 60 ranks per ladder and 20 sub-ranks per rank, and a goal metric needs ranks. Any staff role may read the scheme and the presets, since coaches award promotions against it; only an owner or admin may change it. A stored scheme that no longer fits the model, as one written before a change to it would, is logged and read as a 409 `{"detail": {"code": "grading_scheme_invalid"}}`: re-apply a preset with `PUT`, which replaces it.

## Promotions API

| Method | Path | Does |
| --- | --- | --- |
| `GET` | `/api/people/{id}/grades` | `{current, events}`: `current` is the person's latest promotion (`rank_key`, `rank_label`, `sub_rank`, `sub_rank_label`, `awarded_on`) or `null`; `events` is every promotion, newest first by `awarded_on` then by when it was recorded, each also with `id`, `awarded_by_name`, `note` and `created_at`. 404 for anyone not in the gym |
| `POST` | `/api/people/{id}/grades` | award a rank: `{rank_key, sub_rank, awarded_on?, note?}`; 201 with the same document as `GET` |

A promotion is a `grade_event` row (migration `0018`): the keys of a rank and sub-rank of the gym's scheme, the gym-local day it was given (`awarded_on`, today by default, never later; earlier is how a gym enters a member's history), who recorded it and an optional note of up to 500 characters. The labels are the scheme's when read, so renaming a rank renames it in every member's history, and a key the scheme no longer has reads with the key as its label. An award is checked against the stored scheme and refused with a 422 `{"detail": {"code": …}}`: `unknown_rank` (in neither the ranks nor the kids ladder; a gym with no scheme has none), `unknown_sub_rank` (not one of that rank's), `sub_rank_required` (the rank has sub-ranks and none was sent) or `awarded_in_future`; a stored scheme that no longer fits is the 409 `grading_scheme_invalid` above. A promotion attaches to the person's latest membership that is not cancelled, and someone with none is a 409 `no_membership`. Their current rank is their latest promotion over every membership they hold here, so it survives a plan change or a return after cancelling. Any staff role may read and award, coaches included. Promotions are history: `rakin_app` may add and read them, never change or delete them, and a mistake is corrected by awarding the right rank.

An award that becomes the person's current rank writes a `promoted` row to `plan_event` (`0013`) for its membership and `awarded_on`, in the same transaction, for the plan-event emails (#54); a second award that day writes no second row, and recording an older promotion writes none. The student page reads the current rank as `rank` (`/api/me/page`). Classes since the last promotion are `since_promotion` on `GET /api/people/{id}/attendance`; the "ready for promotion" flag the scheme's `goal_metric` is for needs a target per rank, which the scheme does not hold yet.

## Sign-in

Students and staff sign in with a magic link ([spec](../docs/technical.md#communications)). `app/magiclink` is the mechanism, self-contained so it can become a package: it imports nothing else from `app`. `app/auth.py` plugs Rakin into it: people by email, Postgres, and the mailer.

| Route | What it does |
| --- | --- |
| `POST /api/auth/link` `{"email": …}` | emails a link to every person a gym has on record at that address (`gym_person.email`) who is on its roster (not dado de baja), or has a membership, a staff row or a dependent there. Always a 202, known address or not; a 429 with `Retry-After` past 5 requests per address or 30 per IP in 15 minutes |
| `GET /api/auth/callback?token=…` | the page the link opens: an "Entrar" button. It does not spend the link, so a mail scanner that fetches it does no harm |
| `POST /api/auth/callback` | the button. Spends the link and sets the session cookie, then redirects to `/`, or to the link's `next` when it is the student page (`/me`) |
| `POST /api/auth/logout` | ends the session and clears the cookie |

A link is a signed token (HMAC with `SECRET_KEY`) that expires after 15 minutes and works once; `auth_link` stores only its SHA-256. The session is a 30-day cookie, `__Host-session`, `HttpOnly`, `Secure`, `SameSite=Lax`, and `auth_session` likewise stores only its hash. Both pages are plain HTML forms with no script, so a link works in any browser tab. Every notice about a membership (welcome, statement, proof received, receipt, proof rejected) carries a link of its own to the student page, and a staff invite one to the admin screens (`Template.landing`), issued as it is sent: single use as well, but good for 7 days (`app.notices.PAGE_LINK_TTL`), since a statement is read days before its due date. It is never written to `message_log`. The landing is a fixed list (`app.auth.LANDINGS`), so a link cannot send anyone off the app. When `PUBLIC_BASE_URL` is `http://`, as on the Compose stack, the cookie is a plain `session` without `Secure` instead (`app.magiclink.session_cookie_name`): Chrome and Firefox keep a `Secure` cookie on `http://localhost`, but Safari drops it. Every `https://` base URL keeps `__Host-session` with `Secure`, whatever else is configured. Open the link on the same host name the app is served on. The SPA asks for links at `/ingresar`, where any page sends a signed-out visitor.

On each request with the cookie, the session middleware sets `request.state.person_id` and, when the session has a gym, `request.state.tenant`. It never answers 401 itself: `TenantSession` stays the one place a gym-scoped route refuses. A session ends as soon as its person is no longer in its gym: off its roster (`left_on`, `0032`, or forgotten) and with no membership, staff row or dependent there. A parent who only pays for their kids signs in like a member (migration `0010`), and so does a student added with no plan (migration `0042`, #246); a member dado de baja keeps their memberships and still signs in, to pay what they owe. A sign-in reaches only the gyms whose own record of the person holds the address the link went to (migration `0029`), not every gym the person is in: identity is per `(gym, email)`, so an email one gym writes on someone another gym also has signs nobody in to the other gym, whichever path wrote it (adding or editing a person, a staff invite, the import). `auth_link` and `auth_session` record that address. When it reaches exactly one gym the session starts there; when several gyms hold it the session starts in none yet, and gym routes answer 401 until they pick one (#16), from `auth_gyms_of(person, address)` and no wider. A session in a gym stays live only while that gym's record still holds its address, so changing someone's email ends the sessions signed in with the old one.

Sign-in looks across gyms before any gym is set, which RLS forbids even the owner. Migration `0005` does it in `SECURITY DEFINER` functions owned by `rakin_auth`: `auth_people_by_email`, `auth_gyms_of` (by person and address since `0029`), `auth_live_session` and `auth_end_session`. `auth_session` is gym-scoped like any table with a `gym_id`, with inserts open, as on `person`.

The rate limits live in the API process's memory, which is right for the single process Rakin runs. They count by client address, so behind a proxy uvicorn must trust its `X-Forwarded-For`: Compose sets `FORWARDED_ALLOW_IPS` on `api`, whose port is not published.

## Migrations

```sh
uv run alembic revision -m "describe the change"
uv run alembic upgrade head
```

Every table with a `gym_id` (and `gym` itself) is isolated by an RLS policy on `current_setting('app.gym_id')`. With `app.gym_id` unset, those tables return no rows. `person` is global but not globally readable: a read sees only people with a `gym_person`, `membership` or `staff` row in the current gym (migrations `0003`, `0004`), and the API sees only their `id` and `phone`. `job_run` is global.

RLS is **forced**, so it applies to `rakin_owner` as well, not only to the API. A table owner is normally exempt from its own policies; forcing them means a backfill, seed or one-off script run with the owner's credentials sees and writes only the gym in `app.gym_id`, so a missed `SET` returns nothing there too. Work that spans gyms (the nightly jobs, a gym switcher) sets `app.gym_id` per gym or goes through a `SECURITY DEFINER` function written for it. Only a superuser skips RLS.

`ledger_entry` is append-only for every role, the owner and superusers included: triggers reject `DELETE` and `TRUNCATE`, and an `UPDATE` may change only `status`, `validated_by`, `validated_at` and `note`, and only while the entry is `pending`. Violations raise `restrict_violation` (SQLSTATE 23001). A correction is a new entry. The API reads and writes it only for an owner or admin of the gym in `app.person_id` (`0006`); the owner role, which the seed and jobs use, is scoped by the gym alone.

`session` rows are read, added and changed by `rakin_app` (`0020`), and deleted only for an owner or admin (`0033`). Each references its class type and its coach with `gym_id` in the key, so a row cannot name another gym's even past RLS.

`attendance` rows are added and deleted, never changed: `rakin_app` has no `UPDATE` on them (`0023`). Each references its session and membership with `gym_id` in the key.

`join_request` rows are added and deleted, never changed (`0031`): a request is someone's details before the gym has agreed to keep them, so approving, rejecting and the nightly `join_requests` job each delete it. `join_link` is one row per gym, its token replaced to regenerate the link and the row deleted to revoke it.

A `ledger_entry` names a membership or a cobro extra line, never both (`ledger_entry_owner`, `0037`), and one on a line has no billing period and is never a `charge`: the line's `amount_due_clp` is what it owes. A refund's `refund_of` is held to an entry on its own line as on its own membership. `extra_charge` and `extra_line` read as the ledger does: for `rakin_app`, an owner's or admin's, plus anyone's own lines and their dependents', and the cobros those are of. A line's amount and `cancelled_at` change, since neither moves money; nothing deletes either.

`plan` rows are never deleted either: triggers reject `DELETE` and `TRUNCATE` for every role (`0007`), since memberships and the ledger point at them; deactivate one with `active = false`. A check holds each row to its kind's parameters, the rest null. A trial keeps its free classes and free days in `credits` and `credit_expiry_days`, with `price_clp` 0.

A cancelled `membership` is final: a trigger rejects any `UPDATE` of it for every role (`0009`), raising `restrict_violation`. Checks hold `cancel_reason` and `cancelled_at` to exactly the cancelled rows, and `next_plan_id` and `next_plan_from` (a plan change waiting for its period) to being set together, never on a cancelled row.

Grants name each table; `rakin_app` has no privilege on `alembic_version`. A new table gets its `GRANT` (and, if it carries `gym_id`, its RLS policy) in the migration that creates it.

The Postgres tests create, bootstrap and drop a throwaway database on the `TEST_DATABASE_URL` server, so that URL must be a superuser.

## Reporting views

Derived views over the ledger (`0014`, [spec](../docs/technical.md#domain-model)), each `WITH (security_invoker = true)`, so they read as whoever queries them and every table underneath keeps its RLS. Each is built from `ledger_entry` rows, so a coach, who reads no entries (`0006`), gets no row from any of them, and a member reads only their own and their dependents' (`0010`). Only validated entries count.

- `v_overdue`: a billing period with a validated charge, a due date before today in the gym's timezone, and validated payments and adjustments, less refunds (`0021`), short of its amount due. Columns: `gym_id`, `billing_period_id`, `membership_id`, `person_id`, `membership_status`, `period_start`, `period_end`, `due_date`, `amount_due_clp`, `paid_clp`, `outstanding_clp`, `days_overdue`. Lapsed and cancelled memberships keep their unpaid periods there, and the owner's "Vencido" counts them all (#207).
- `v_balance`: per membership with ledger entries (a cobro extra line's are left out, `0037`), `balance_clp`: charges and refunds less payments and the adjustments on a period, which are signed (`0021`). Positive is owed, negative is credit. An adjustment with no period is an overpayment's carried credit, which its payment already counts, so it is left out.
- `v_monthly_income`: per gym and calendar month (`month`, its first day) in the gym's timezone, `income_clp`: the validated payments less the validated refunds (`0022`), of which `extra_income_clp` is the cobro extra lines' (`0037`), each by the month it was validated, so a refund counts in the month it was made, not the month of the payment it gives back; `payments`, how many payments; and `refunds_clp` and `refunds`, the month's refunds. A month with only refunds has a negative `income_clp`. It is the gym's income only for an owner or admin; a member reads the sum of their own and their dependents' payments under the same name, so the dashboard reads it as staff.

- `v_inactive` (`0023`): per person with a trial or active membership, `last_attended_on` (a day in the gym's timezone) and `days_absent`, both `null` for someone who never attended. "More than N days" is the reader's `WHERE`. It reads `attendance`, which a coach may read, so a coach sees it too.

## Seed data

```sh
uv run python -m app.seed                      # as of today in the gym's timezone
uv run python -m app.seed --today 2026-11-08   # the day the UI design depicts
make seed                                      # from the repo root, inside Compose
```

`app.seed` loads Academia Sur, the demo gym that dev, the 90-day simulation and the self-host demo start from. `app/seed/data.py` is the roster: the members the [UI design](../docs/design/ui-design.html) names, in the standing it shows them in (Felipe Díaz 9 days overdue, Diego Morales's proof waiting, Camila Ortiz paying for Mateo and Sofía), plus filler drawn from a fixed random sequence. `app/seed/build.py` turns it into rows for a seed date with no I/O, so tests check it without a database. It also holds the adults' weekly schedule, five `schedule_slot`s taught by Sebastián: Fundamentos at 07:00 on weekdays and 09:00 at the weekend, Fundamentos at 19:00 on Monday, Wednesday and Friday, Avanzado at 20:00 on Tuesday and Thursday, and an open mat at 11:00 on Saturday and Sunday. The schedule's classes of the three weeks before the seed date each ran in blocks of the default kinds, with some sparring cut a round or two short, and up to about half the adults on a monthly or prepaid plan were marked at each, so the class timer's totals have data. The classes from the seed date through the schedule's 14-day horizon are made too, as the nightly `schedule` job would have, with `generated_until` at the horizon's end, so the job carries on from there. None of them is marked, so today's morning class, started by the time anyone opens Hoy, is under Sin asistencia (#216). The design's numbers hold on any seed date: 64 active memberships and 2 frozen, 6 active members overdue for $270.000 (two lapsed members owe on top of that, and Hoy and Pagos list them too, #207), 3 proofs for $126.000 (the design's $162.000 counts Sofía Ortiz's too, but her period would fall in her freeze). Each frozen membership has a `membership_freeze` that started a week before the seed date and ends three weeks after it, and is billed as the app bills one (#216): no period starts once the freeze has, and the freeze moved the paid-through date and the anchor day past the frozen days. `gym.settings` carries the BJJ grading scheme (white to black with 4 stripes, and the grey-to-green kids ladder), the custom-field definitions, the bank account and `grace_days` (10).

Loading again inserts nothing: every row's id is a UUIDv5 of its natural key, and rows already there are skipped, never updated, which the append-only ledger requires anyway. The first load stores its date in `gym.settings["seed"]["as_of"]`, and later loads build for that date again, ignoring `--today`. To reseed for another date, start from an empty database (`docker compose down -v`).

Each transfer's proof key gets a file in the configured `BLOB_STORE`: `app/seed/proof.jpg`, a made-up receipt marked as demo data, so Validar comprobante opens the seeded proofs. A key that already has a file keeps it.

The loader connects as the owner (`MIGRATION_DATABASE_URL`) with `app.gym_id` set to the demo gym. Each member holds the rank `data.py` gives them by one `grade_event`, recorded by Sebastián, the coach, and so writes no plan event: on their first day for a white belt with no stripes, else a day drawn from their time in the gym. Diego Morales's purple belt with 1 stripe dates from 14 June 2025, which his student page shows on the design's day. Each kid has a `guardian_link` to the member who pays for them, who is also the payer (`claimed_by`) of the kid's payments; kids have no phone or email. Every person gets a `gym_person` row with the same name, email, RUT and date of birth. Every guardian in the demo also trains, though a guardian need not. Drop-ins have a plan but no memberships, since a drop-in is a single attendance.

### Try the import

`app/seed/demo_import.csv` is a made-up gym export to try Alumnos → Importar on the seeded gym: 38 rows, semicolon-separated with a BOM, Spanish headers, phones and dates written several ways, plan names in any case, and an `Observaciones` column the import ignores. `demo_import.xlsx` is the same sheet as Excel saves it, with real date cells and some phones stored as numbers. Every name, phone, RUT and `example.cl` address in it is invented.

1. `make seed`, then open http://localhost:8080 and sign in as the owner, `martin.fuentes@example.com`. The link is in the API's log (`docker compose logs api`).
2. Alumnos → Importar alumnos, upload either file and keep the suggested columns. Every plan matches by name, so there is nothing to choose.
3. Check without saving. The dry run reports 33 rows to import and 5 refused: 34 people (2 of them guardians named only on their children's rows), 8 guardian links and 28 memberships. The refused rows show one of each refusal: a missing name, a landline, an unknown plan ("Plan familiar"), a due date before the start, and a phone already used higher up. Felipe Díaz is already in the seed, so the row is listed under "Ya existen": the sheet's email is not applied. Julián Ortiz joins Camila Ortiz, a seeded guardian, and Valentín Godoy is a teenager with their own phone and a guardian.

Importing it for real and then again creates nothing the second time. The dates are fixed in the file, so some memberships come in already overdue, more of them as time goes on. The import refuses a start or due date more than 5 years from today, and the sheet's run from 4 November 2024 to 1 March 2027, so it imports as described until 4 November 2029; after that, bring its oldest dates forward. `tests/test_member_import.py` holds the dry run to these numbers, with the import's clock pinned to the day the sheet was written.

## Nightly jobs

```sh
uv run python -m app.jobs.daily                      # run what is due, once (for cron)
uv run python -m app.jobs.daily --every 3600         # stay up and check hourly (Compose's `jobs`)
uv run python -m app.jobs.daily --today 2026-11-08   # as if it were that date
```

`app/jobs` runs each job once per day ([spec](../docs/technical.md#core-state-machines)). A job is a `Job(name, run)`, where `run(conn, day)` does the day's work on an `asyncpg` connection; `jobs()` in `app/jobs/daily.py` lists them in the order they run on a day, so a later job can rely on an earlier one's work: `JOBS`, which need only the database, then the jobs that send mail.

`job_run` is the record: a day is done for a job once it holds a `succeeded` row for `(job_name, run_date)`, and a job owes every day from its first row to today that has none. A run that finds nothing owed does nothing; one after downtime catches the missed days up, oldest first, and a job that has never run starts today. Each `(job, day)` is one transaction that also marks its row `succeeded`, so the work and its record commit together. A failure rolls the work back, marks the row `failed`, logs `job failed` with the job and date, and stops the run, since later days and later jobs may depend on it; the next run retries that day first. A job that works in pieces may roll back just the piece that broke, to a savepoint, and return `False`: its other work commits, and the day is failed (`job incomplete`) and retried the same way, so such a job must be safe to re-run. Run once (no `--every`), it exits 1 on a failure.

Days are dates in `JOBS_TIMEZONE` (`America/Santiago`). One runner works at a time, under a Postgres advisory lock: a second one logs that and does nothing, and a `running` row found under the lock, left by a runner that died, is run again. The runner connects as the owner (`MIGRATION_DATABASE_URL`), as the seed does, so RLS still holds it to one gym: a job that works per gym sets `app.gym_id` for each.

The owner cannot see which gyms exist with no `app.gym_id` set, so a per-gym job asks `jobs_gym_ids()` (`0011`), a `SECURITY DEFINER` lookup that returns only gym ids and that only the owner may call.

The jobs, in order:

- `freezes` (`app/jobs/freezes.py`): first starts each freeze booked to start by the run date (`started` false, `0027`), as `POST /api/memberships/{id}/freeze` starts one from today: the due date, the billing periods from its first day on, `anchor_day` and a pending plan change move past the frozen days, and a `frozen` row goes to `plan_event`; a membership no longer Active by then has its booked freeze called off instead. Then it returns each Frozen membership whose latest `membership_freeze` of a day or more ends by the run date to Active, and writes an `unfrozen` row to `plan_event` with the change. The due date is left alone: the freeze moved it as it started. It runs first, so a membership unfrozen today is billed today, and a freeze booked over days the job missed starts and ends on the same run. Re-running a date starts and unfreezes nothing more.
- `billing_periods` (`app/jobs/billing.py`): for every Active membership, writes each billing period that falls due within 7 days, with a validated `charge` ledger entry for its amount (the plan's price less `discount_pct`, rounded down to a whole peso; a period discounted to nothing has no charge). A monthly plan owes a period per cycle from its anchor day, a prepaid one a block of `period_months`, a credits pack or a drop-in a single charge, a trial nothing. A period falls due on its first day. A pending plan change prices the first period starting on or after `next_plan_from` and becomes the plan then, with `anchor_day` recomputed. It picks up after the latest period (or the paid-through date, if later), so re-running a date writes nothing. A membership starting, and a member paying ahead, are billed by a request with the same code (`write_billing`), and the job finds those periods there.
- `lapse` (`app/jobs/lapse.py`): flips Active (or Trial) memberships to Lapsed and writes a `lapsed` row to `plan_event` (`0013`) with the change, for the plan-event emails (#54) to send. A monthly or prepaid membership lapses once its oldest billing period that validated payments and credit adjustments leave short is past its due date plus the gym's `grace_days` (5 by default): due Nov 1, Nov 2 to 6 are the grace and Nov 7 lapses (`app.domain.dates.is_past_grace`). A credits pack or a trial lapses the day after its last day or at zero credits, with no grace. A drop-in never lapses, and a Frozen membership waits for its freeze to end (`freezes`). Re-running a date lapses nothing more. It locks every membership it may lapse before it reads what is unpaid, and recording a payment locks its membership first (`app/api/ledger.py`), so a payment and a lapse of one membership run one after the other: a payment that commits first is counted, and one that comes later waits for the run. Any handler that validates a payment must take the same lock before it reads the period.
- `join_requests` (`app/jobs/join_requests.py`): deletes the join link requests nobody approved or rejected that were sent before the start of the day 30 days back, in each gym's timezone (#154). Re-running a date deletes nothing more.
- `schedule` (`app/jobs/schedule.py`): makes each gym's classes of the weekly schedule from the run date through 13 days ahead (`schedule_sessions()`, `0035`; see [Weekly schedule API](#weekly-schedule-api)). Re-running a date makes nothing more.
- `statements` (`app/jobs/statements.py`): emails each billing period's statement to the member, or their guardian, when it falls due within 7 days: what is still owed on it, the due date, the gym's bank details and a link to the student page to upload the proof. Billing writes each period 7 days ahead on the same run, so a period is usually stated the day it appears. A period with a `statement` sent in `message_log` is skipped, so it is stated once; a failed send is tried again on each later run until the due date. A period paid in full, discounted to nothing or of a cancelled membership is not stated, and neither is a frozen membership's while the freeze lasts: it moved the periods it reaches past its end. Every gym's statements are read first, each in its savepoint, and sent after, so no savepoint is open while the relay answers; the day's transaction still is, holding only those reads. Each send, its link and its `message_log` row go through `DATABASE_URL`'s user on a connection of their own, like the API's (`app.jobs.daily.mailing`), so they commit whatever the day's outcome and a day run again sends only what it had not. An address that cannot take mail is not issued a link.

Set `SENTRY_DSN` to report failures to Sentry (`app/sentry.py`): every `ERROR` log line becomes an event, so a failed job, or a run that could not reach the database, arrives there with its traceback. The API starts the same client in `create_app`, so an unhandled error in a request is reported too. Empty, the default, sends nothing.

`tests/test_simulation.py` runs the jobs across 90 simulated days of the demo gym, in two windows that cross Santiago's spring-forward (6 Sep 2026) and fall-back (4 Apr 2027). Each day it freezes the clock (freezegun) at the day's first instant in `JOBS_TIMEZONE`, has members pay on a fixed random schedule (some late, some past the grace, some never), runs `app.jobs.daily` on the date its own `today` reads, and checks: no duplicate, overlapping or missing periods, one charge each, none more than 7 days ahead; `v_balance` equals the ledger summed by kind; each membership lapses on exactly the day the grace rules say, with one `lapsed` event; each frozen one is Active again on the day its freeze ends, with one `unfrozen` event; and a second run at the day's last instant reads the same date and finds nothing owed, so `job_run` ends with one succeeded row per job per day. It is a `postgres` test, so CI runs it with the rest.
