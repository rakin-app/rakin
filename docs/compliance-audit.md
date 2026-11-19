# Ley 21.719 readiness audit: hosted Rakin

Spike #366, audited 2026-11-16 against `main` at `9667044`. It checks the promises in [technical.md, "Compliance and privacy"](technical.md#compliance-and-privacy) against the code, and lists what hosting Rakin for a second gym still needs. It is read-only: every gap is its own issue. Epic: #69.

Hosting makes the company the **encargado** (processor) of each gym's member data, and each gym the **responsable** (controller). The law takes effect on 1 December 2026, two weeks from this audit (or 15 October 2027 if the postponement bill passes; see [question 4](#open-legal-questions)).

## Blockers for onboarding a second gym

These must be closed before a second gym's data enters the hosted instance:

| # | Gap | Issue |
| --- | --- | --- |
| 1 | No processor terms (DPA) between the company and a gym. `technical.md` promises a template; none exists | #367 |
| 2 | An imported minor with no guardian gets statements and overdue emails at their own address. Only hand enrolment requires a guardian | #368 |
| 3 | No breach response runbook: nobody is named, there is no order or deadline, and no gym contact list | #369 |
| 4 | Backup restore not yet rehearsed, though `technical.md` requires it before the second gym | ops#2 |

Everything else is labelled `before paid launch` or `later` in the [gap list](#gaps-and-issues).

## 1. The compliance table, row by row

Status: **implemented**, **partial** or **missing**.

### Data controller

| Promise | Status | Evidence |
| --- | --- | --- |
| Per-gym privacy notice at `/privacidad`, filled in from Ajustes, linked from the join form and the student page | implemented | `backend/app/api/privacy.py`; `frontend/src/routes/Privacy.tsx`; link in `frontend/src/layouts/MeLayout.tsx`; `backend/tests/test_privacy.py` |
| The join link works only once the notice is filled in | implemented | `backend/app/api/join.py:288-296` (`has_privacy`); 409 `privacy_incomplete` on generating a link |
| A DPA template for hosted gyms | **missing** | nothing in the repo (#367) |

### Consent captured with a timestamp and the text version, by the guardian for a minor

**Partial.**

- The join form requires the consent box (`backend/app/schemas/join.py:89`, `consent: Literal[True]`; `backend/tests/test_join.py:446`) and stores `join_request.consented_at` (`backend/app/api/join.py:341-348`).
- Approving a request **deletes it** (`backend/app/api/join.py:519`), so the consent timestamp is gone once the person exists. Nothing on `gym_person` records it.
- No text version is stored. The SPA has a notice version, `TEMPLATE_UPDATED_ON` (`frontend/src/api/privacy.ts:26`), but it never reaches the database.
- A minor's form requires a guardian's name, email and phone (`backend/app/api/join.py:386-406`), and the guardian ticks the box. The record does not say that the guardian consented.
- Members added by hand (`POST /api/people`) or by import have no consent record at all.
- The notice gives **contract** as the legal basis for adults and **guardian consent** for minors (`frontend/src/i18n/es.ts`, `privacy.basis`). `technical.md` says consent is captured "at membership creation (adult)". The two disagree; see [question 6](#open-legal-questions).

Gap: #370.

### Minors never receive messages

**Partial.**

- Every notice is addressed through `contact_for` (`backend/app/contacts.py`), which sends to the guardian when a `guardian_link` exists. It is used by welcome, statements, overdue, receipts, proofs, freeze requests, reminders, the inactive list and cobros. Tests: `backend/tests/test_overdue_emails.py:283`, `:456`, `backend/tests/test_statements_job.py:240`, `backend/tests/test_reminders.py:259`, `backend/tests/test_guardians.py:349`.
- Routing depends on the **link**, not on age. Hand enrolment refuses a minor with no guardian (`backend/app/api/member_roll.py:218-222`, `backend/tests/test_member_roll.py:273`), and so does the join form. The **import does not check age** (`backend/app/member_import/rows.py`, `backend/app/api/member_import.py`: no age check). A child row with their own email and no guardian becomes a member, and the nightly `statements` and `overdue` jobs then email the child.
- Editing a person's birth date, or removing a guardian later, is not checked either.
- A minor with their own email can ask for a sign-in link at `/ingresar`. That message is one they requested, but it is still a message to a minor.

Gap: #368 (blocker).

### Sensitive custom fields: encrypted at rest, excluded from default exports, role-gated

**Partial.**

| Part | Status | Evidence |
| --- | --- | --- |
| Encrypted at rest, app-level AES-GCM, bound to gym, person and field | implemented | `backend/app/domain/custom_fields.py:158-180`, key `FIELD_ENCRYPTION_KEY` (`backend/app/settings.py:44`, refused at its public default outside local); `backend/tests/test_custom_fields.py:387`, `:409` |
| Excluded from exports | implemented | the only export is the accountant's ledger: `secret IS NULL` (`backend/app/api/ledger_export.py:55-60`); `backend/tests/test_ledger_export.py:382` |
| `visible_to` per field, owner only by default; never answered to a role it is hidden from | implemented | `backend/app/domain/custom_fields.py:41-53`, `backend/app/api/custom_fields.py:86`; `backend/tests/test_custom_fields.py:215`, `:346` |
| A per-gym switch that turns sensitive fields off entirely | **missing** | no such setting in `backend/app/schemas/gym.py` |
| Explicit consent for health data, which is sensitive data under the law | **missing** | nothing records it per field or per person |

Gap: #376.

### The student's data view, JSON export, and deletion by anonymisation

| Part | Status | Evidence |
| --- | --- | --- |
| The student page shows all stored data | **missing** | `GET /api/me/page` (`backend/app/api/me.py:279`, `MyPage` in `backend/app/schemas/me.py:68`) shows name, plan, payments, rank, attendance and cobros. It does not show the RUT, email, phone, birth date, guardian, custom fields or message history |
| One-click JSON export | **missing** | no endpoint. #63 is the gym-wide export, not the member's |
| Deletion that anonymises the person and keeps ledger amounts | **missing** | see below |

What exists is `DELETE /api/people/{id}` (owner only), which calls `forget_gym_person` (migrations 0032, 0044, 0051, 0054, 0055). It **deletes**, it does not anonymise. It **refuses** anyone the gym kept money from (`forget_refusal` returns `payment`; `backend/tests/test_voids.py:358`). So a member who ever paid cannot be deleted at all, which is most real members. It was built for people added by mistake.

When it does run, it leaves these behind:

- `message_log` rows, with `to_address` and the template `payload` (names, amounts);
- proof files in object storage, since nothing deletes them;
- `auth_link` rows with the person's email;
- `idempotency_key` response bodies that mention them;
- the global `person` row (name, RUT, email, birth date), which only #69 was meant to erase.

Gap: #371 (view and export) and #372 (deletion).

### Retention: lapsed memberships anonymised at 24 months, proof images deleted 12 months after validation

**Missing.**

The nightly jobs are `freezes`, `billing`, `lapse`, `join_requests`, `schedule`, `statements` and `overdue` (`backend/app/jobs/daily.py:34-46`). The only deletion job is `join_requests`, which deletes requests left for 30 days (`backend/app/jobs/join_requests.py`, `backend/tests/test_join.py:1095`). Nothing anonymises lapsed members, and nothing ever deletes a proof file (`BlobStore.delete` is called only for gym logos, `backend/app/api/gym.py:134`).

Nothing purges these either: `auth_link`, expired `auth_session`, `message_log`, or `idempotency_key` rows for people who never write again (the TTL sweep runs only on that person's next claim, `backend/app/idempotency.py:171-180`).

The privacy notice also promises something else: "Si dejas de entrenar, guardamos tu historial (inicio, pagos y grados) hasta que pidas que lo borremos" (`frontend/src/i18n/es.ts`, `privacy.retention`). That is not the 24-month rule. Members read the notice, so it wins until the two agree.

Gap: #378.

### Security: TLS only, RLS, magic-link expiry, encrypted backups

| Part | Status | Evidence |
| --- | --- | --- |
| TLS only | implemented | Caddy redirects HTTP to HTTPS and gets certificates per host (`deploy/Caddyfile`). `.app` is HSTS-preloaded. Cookies are `Secure` off a non-`http` base URL. Postgres is reachable only on the Compose network |
| RLS | implemented | see [section 2](#2-tenant-isolation) |
| Magic links expire | implemented | 15 minutes for a requested link and code, 7 days for one in a notice, sessions that end 35 days after their last use and 180 days after sign-in (#491), single use (`backend/app/magiclink/service.py:46-47`); `backend/tests/magiclink/test_web.py:488`, `:786`, `backend/tests/test_auth.py:278`, `:323` |
| Audit via `message_log` and `validated_by` | partial | both exist and are append-only. Not enough to scope an incident: see [section 5](#breach-response) |
| Backups encrypted | implemented | `pg_dump` piped through `age` to a public key, so the host cannot read its own backups (`backend/app/backup.py:198-211`); `backend/tests/test_backup.py:238` |

## 2. Tenant isolation

**Implemented for the database. Proofs are isolated through it.**

I migrated a scratch database to head and read `pg_class` and `pg_policy`. Every table with a `gym_id`, plus `gym`, has RLS **enabled and forced**, with a `gym_id = app.gym_id` policy. `person` is forced too, and the API role has no grant on it at all: it reads it only through policies scoped to the gym's own people, and writes only through `join_gym`.

Three tables have no RLS, each by design:

| Table | Personal data | Why it is global |
| --- | --- | --- |
| `auth_link` | email, person id | a sign-in link belongs to no gym; looked up only by token hash |
| `mail_suppression` | email address | Resend's bounces and complaints are per address |
| `job_run` | none | job bookkeeping |

Tests that prove gym A cannot read gym B:

- `backend/tests/test_migration_0001.py:108`: every gym-scoped table has forced RLS and a policy. A new table without them fails this test.
- `backend/tests/test_tenancy.py:219`: an endpoint sees only its gym's rows, for every table. Also `:225` (people), `:270` (a person in another gym by id), `:287` (only `person.id` is readable).
- `backend/tests/test_tenancy.py:133`: every API route is public or gym-scoped.
- Each later table has its own isolation test, listed in `test_migration_0001.py:126-145`.

**Object storage.** Proofs are stored at `proofs/<gym_id>/<person_id>/<uuid>` (`backend/app/api/proofs.py:51-57`). A claim takes only a key under the claimant's own prefix: the API checks it, and so does a database check from migration 0012 (`backend/tests/test_proofs.py:339`). The bucket is private. A file is reached only through a presigned URL issued for a `ledger_entry` read under RLS (`backend/app/api/proof_review.py:182-185`; `backend/tests/test_proof_review.py:569`, another gym's entry is a 404). One bucket key reads every gym's proofs, so the API's S3 key is as sensitive as the database password.

**Observation, not a gap.** RLS separates gyms, not people within a gym. A member's session can read any `gym_person` row in their gym at the database level; only the API stops them. `ledger_entry` is the exception (`ledger_entry_own`). #309, which moves RLS to permissions, is where member-scope policies would go.

## 3. Personal data inventory

Per person, per gym, unless marked global. "Drop?" asks whether the field can go or become optional.

| Where | Fields | Why | Drop? |
| --- | --- | --- | --- |
| `person` (global) | name, RUT, email, birth date | one identity across gyms by RUT (`join_gym`) | Already optional. Only `id` and `rut` do identity work; name, email and birth date are the first gym's copy and never shown to a gym. Could hold only the RUT (#372) |
| `gym_person` | name, email, RUT, phone, `no_whatsapp`, birth date, `left_on`, `left_reason`, `member_since`, `prior_classes` | the gym's record; phone for WhatsApp; birth date for minors and kids' ladders | RUT optional already (email is the identity without one). Birth date could be optional for adults, but it is how a minor is detected. `left_reason` is free text |
| `guardian_link` | guardian, dependent | who pays and gets notices for a minor | no |
| `membership`, `membership_freeze`, `freeze_request`, `plan_event` | plan, status, dates, cancel, void and freeze reasons, notes | billing | reasons and notes are free text: could hold health details ("lesión") |
| `billing_period`, `ledger_entry`, `extra_line`, `history_payment` | amounts, method, bank transaction reference, notes, proof key | accounting | `note` is free text |
| Proof files (object storage) | transfer screenshots and PDFs: name, bank, account digits, sometimes RUT | the gym checks a payment | could be deleted at validation, not 12 months later (#378) |
| `attendance`, `session_block`, `grade_event`, `audit_event` | classes, time on the mat, belts and dates, who did what | the product's core; corrections | belt history of children: [question 2](#open-legal-questions) |
| `person_field_value` | the gym's custom fields, sensitive ones sealed | gym-defined (emergency contact, weight, injuries) | yes: each is the gym's choice |
| `session.notes` | coach's notes on a class | coaching | free text, may name students |
| `message_log` | channel, to address, template, payload, status | proof of what was sent | could drop `to_address` and `payload` after a period (#378) |
| `join_request` | name, RUT, phone, email, birth date, guardian's name, phone and email, `consented_at` | waiting for staff | already deleted at 30 days |
| `auth_link`, `auth_session` | email, person, expiry | sign-in | purge after expiry (#378) |
| `idempotency_key` | response body of a write | double-submit replay | 24h by design; purge globally (#378) |
| `mail_suppression` (global), `mail_unsubscribe` | address, reason; unsubscribe flag | deliverability; opt-out | no |
| Browser `localStorage` on staff phones | unsent attendance marks and class drafts | offline classes | cleared on sign-out (`frontend/src/api/drafts.ts`) |
| Logs (Docker `json-file`, 5 × 20 MB per service) | method, path (with ids), status, request id | operations | no names, RUTs or emails are logged (`backend/app/middleware.py:46`) |
| Backups (age-encrypted dumps) | everything in the database | recovery | see [section 4](#4-offboarding) |
| The accountant's export (downloaded by owner or admin) | name, RUT, amounts, non-sensitive custom fields | the gym's books | RUT could be optional per gym |

**The RUT.** It is optional at every entry point since #165: email is the identity without one, and an import keeps a row with neither. It is needed for:

- one person across gyms (`join_gym`);
- the v2 badge and visits;
- the accountant's export column.

None of these needs it to be mandatory. Keep it optional, and make the export column follow whether the gym collects it. No issue: the data model already allows it.

## 4. Offboarding

**Missing.** When a gym cancels, nothing happens:

- There is no command to export a gym's data (#63 is open) and none to delete a gym. `app.gyms` only creates (`backend/app/gyms.py`).
- Its rows, its proofs under `proofs/<gym_id>/` and its people's `person` rows stay forever.
- `forget_gym_person` cannot be used in bulk: it refuses every member who paid.

**Backups.** Retention keeps the newest dump of each of the 14 most recent days that have one, and of the 8 most recent Sundays (`backend/app/backup.py:61-62`, `:163-172`; `backend/tests/test_backup.py:76`). Data deleted today survives in backups for **up to about 8 weeks** (the eighth Sunday back, 50 to 56 days). Two things stretch that:

- Retention counts dumps, not days. If backups stop, the last ones are kept until they start again.
- `deploy.md` asks for object versioning on the proofs bucket "where the provider offers it". If it is on, a deleted proof stays as an old version until a lifecycle rule removes it. The same holds for the backups bucket.

Gap: #377.

## 5. Gaps the table does not cover

### Processor terms

There are no terms between the company and a gym that cover:

- the object, duration and nature of the processing;
- security duties;
- subprocessors;
- breach notice to the gym;
- deletion or return of data at the end.

The privacy notice already tells members that Rakin "trata tus datos por encargo de la academia y solo para prestarle ese servicio", with a list of subprocessor kinds (`frontend/src/i18n/es.ts`, `privacy.processors`). The contract that should back that sentence does not exist. Gap: #367 (blocker). Writing the text is the lawyer's job, out of scope here. The subprocessor list below is its technical annex.

### Breach response

When audited there was no runbook. It is now [incident-response.md](incident-response.md) (#369), which says where each source below is and how long it is kept. To scope an incident, these exist:

- **Request logs**: method, path, status and request id. No gym, no person, no client IP. Kept only until 5 × 20 MB rotates out per service (`deploy/docker-compose.yml:17-22`): days, not months.
- **`auth_session`**: who signed in to which gym, and when. No IP, no user agent.
- **`message_log`**: every message sent.
- **`audit_event`**: corrections and deletions only.
- **Sentry**: errors.
- **Provider logs**: VPS, R2 and Resend access logs, if those accounts keep them.

Nothing records reads: who opened a ficha, who downloaded a proof, who exported the ledger. Nothing names who at the company is told first, who tells each gym, by what deadline, or where each gym's contact is.

Gap: #369 (runbook, blocker) and #374 (logs that can scope an incident).

### International transfer

| Data | Where | Location |
| --- | --- | --- |
| Postgres (everything) | the VPS, Hetzner | United States: Ashburn, Virginia (`docs/deploy.md`, section 1) |
| Proofs | Cloudflare R2 (`S3_REGION=auto`) | R2 picks the location; no jurisdiction is set |
| Backups | R2, a separate bucket | as above |
| Email (names, amounts, sign-in links) | Resend, through SMTP | United States |
| Errors | Sentry, US region (`*.ingest.us.sentry.io`) | United States (#373, #430) |
| Join form human check | Cloudflare Turnstile, only when `HUMAN_CHECK` is set | global |
| DNS and TLS | Cloudflare DNS (grey cloud), Let's Encrypt | no personal data |

**What Sentry receives.** When audited, `init_sentry` passed nothing beyond the DSN and environment, so the SDK's defaults applied: request bodies and stack-frame local variables were attached to errors, and a Postgres error carried the row's values, such as a unique violation's `Key (rut)=(…)`. An error while saving a member could send their name, RUT, birth date or custom fields.

Since #373, `backend/app/sentry.py` sends none of that:

- no user data, cookies, IPs or query strings (`data_collection`, the SDK's successor to `send_default_pii=False`);
- no request bodies (`max_request_body_size="never"`) and no local variables (`include_local_variables=False`);
- `before_send` drops what is left anyway: the request's `data`, `query_string`, cookies and `Cookie` header, and the query string of every URL in a breadcrumb (httpx's log line `HTTP Request: GET https://…?…` included);
- an exception from asyncpg or SQLAlchemy keeps its type but not its text: it becomes `sqlstate=23505 constraint=person_rut_key (message withheld)`. A pydantic `ValidationError`, whose text quotes the `input_value`, becomes the fields that failed and why (`Person: rut int_parsing (message withheld)`);
- the same text is withheld where a log record quotes the exception, with `%s` or in an f-string: in the event's message and parameters, and in the breadcrumb the record leaves for later events (`before_breadcrumb`).

`tests/test_sentry_privacy.py` sends an error with a RUT in the body, the query string, a cookie and a local; a unique violation through SQLAlchemy and through asyncpg; and a validation error logged every way above. It fails if the RUT reaches the transport. Every `ERROR` log record still becomes an event, with its message and `extra`: the code logs ids there, never names, RUTs or emails. The organisation is on the US region, in the United States, where the database and the email provider are too; the EU region was considered and not kept (#430). That is a transfer under art. 27 (no country is declared adequate), so Sentry's data processing terms go in the DPA's annex (#367). The SPA has no Sentry.

Gap: #373 (closed).

### A member's request that reaches the company

The company receives mail at `soporte@` and `hola@` (Cloudflare Email Routing, `technical.md`). Nothing says what happens when a member writes there to ask for their data or its deletion. The company is the processor, so it should pass the request to the gym (the controller) and help it answer, without answering itself. That needs:

- a written procedure;
- a way to tell which gym the member belongs to without revealing other gyms;
- the legal deadline, tracked.

Gap: #375.

## Gaps and issues

| Gap | Severity | Issue |
| --- | --- | --- |
| Processor terms (DPA) with each hosted gym, with the subprocessor annex | blocks second gym | #367 |
| Minors reached directly: import and edits allow a minor with no guardian; routing by link, not age | blocks second gym | #368 |
| Breach response runbook | blocks second gym | #369 |
| Restore rehearsed before the second gym | blocks second gym | ops#2 |
| Consent record kept past approval, with the notice version, the guardian, and the basis for staff-added members | before paid launch | #370 |
| The member's own data view and JSON export on `/me` | before paid launch | #371 |
| Deletion for a member who paid: anonymise instead of refusing, and remove what `forget_gym_person` leaves behind | before paid launch | #372 |
| Sentry: no request bodies, locals or row values; choose the region (done: US, #430) | before paid launch | #373 |
| Logs that can scope an incident: gym, person and IP on requests; reads and exports recorded; kept long enough | before paid launch | #374 |
| A member's request that reaches the company by email | before paid launch | #375 |
| Sensitive fields: explicit consent and the per-gym off switch | before paid launch | #376 |
| Gym offboarding: export, deletion of rows and files, backups ageing out | before paid launch | #377 |
| Retention jobs, and a retention promise the notice and `technical.md` agree on | later (the first proof turns 12 months old in late 2027) | #378 |

Existing issues linked rather than duplicated: #69 (the epic), #63 (gym export, part of #377), #182 (merging people across gyms, which #372's anonymisation must respect), ops#2 (restore rehearsal), #309 (RLS by permission, the place for member-scope policies).

## Open legal questions

Researched from the primary sources in [legal-research.md](legal-research.md) (#381), which proposes an answer to each and leaves the lawyer five yes/no confirmations.

1. **Consent age for minors.** Sources disagree between under 14 and under 16. The code treats everyone under 18 as needing a guardian (`ADULT_AGE = 18`, `backend/app/schemas/join.py:25`). Is that right, or may a 14- or 16-year-old consent alone?
2. **Profiling.** Does a child's belt and attendance history count as profiling?
3. **Small companies.** Does the first-year warnings-only regime apply to the company?
4. **Effective date.** 1 December 2026, or 15 October 2027 if the postponement bill passes?
5. **Privacy notice wording.** The art. 14 ter wording is already pending with the owner's lawyer.
6. **Legal basis.** The notice says contract for adults and guardian consent for minors; `technical.md` says consent for everyone. Which is right? Does a member added by staff or by import, who never saw the notice, need consent recorded, or is the contract enough?
7. **Accounting retention.** How long must the gym keep ledger entries with the member's name? Does keeping amounts after a deletion request rest on legitimate interest or on a legal duty?
8. **Retention promise.** Should the notice keep "hasta que pidas que lo borremos" for a former student's history, or should a fixed period (24 months) apply?
9. **Subprocessors abroad.** Is a general authorisation in the DPA enough for US subprocessors (Resend, Sentry, Cloudflare)? Does each need its own transfer clause, and must the notice name them?
10. **Shared identity.** One `person` row is shared by every gym that adds the same RUT, though no gym sees another's data. Is that a communication of data between controllers, and does it need disclosure?
11. **Breach notice.** What deadlines apply from processor to controller, and from controller to the Agencia and to members? Who notifies the members: the gym or the company on its behalf?
12. **Turning 18.** Does a member who joined as a minor with guardian consent need to give their own consent at 18?
13. **WhatsApp from staff phones.** Reminders are sent by staff from their own phones through `wa.me` links. Is the member's number then processed outside the processor's control, and does the gym's notice need to say so?
14. **Registration and a delegate.** Must the company, as processor, register anywhere or appoint a data protection delegate?
