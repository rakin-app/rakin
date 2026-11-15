# Expenses and club officers: where the money goes, and who sees it (#307)

Spike, November 2026. No product code: this doc decides what a gym's expense is, where
it is kept so billing never reads it, how money in and money out sit side by side, and,
because who may see expenses depends on it, how today's three roles become titles
(presidente, tesorero, secretario) and permissions. The build tickets at the end carry
it out, in order: permissions first, then expenses.

## For the owner, in short

- **Record what the gym spends.** Rent, power, water, gas, internet, the federation,
  insurance, gear, coaches' pay: a date, an amount, a category, who was paid, how, a
  note and, if you want, a photo or PDF of the receipt. The categories come filled in
  for a Chilean gym or club and you can rename, add or hide them.
- **Fixed costs are one tap a month.** Save rent or internet as a "gasto fijo" once.
  Each month Rakin lists the ones not yet recorded; you confirm rent as it is and type
  the power bill's amount. Rakin never records an expense on its own, because a bill
  it invents is a bill you did not pay.
- **Expenses never touch your students.** They live apart from the Libro: nothing in a
  student's balance, Esperado, Cobrado or the overdue emails can see them.
- **One page for the month: Finanzas.** Money in (what you collected, cobros extra
  included), money out by category, and the result; and the year, month by month. The
  accountant's export gains a Gastos sheet and a Resumen.
- **A trip paid for the group** is an expense linked to the cobro extra that recovers
  it, so you see what it cost, what came back and the difference.
- **Titles and permissions are separate.** A title is what someone is called
  (Presidente, Tesorera, Coach). Each title carries a set of permissions: see money
  in, record payments, see expenses, record expenses, manage students, manage the team,
  take attendance, set up the gym. A person can hold several titles and can do what
  any of them allows. You, the owner, can always do everything.
- **Nothing changes for an academy.** Your admins and coaches become the titles
  "Administrador" and "Coach" with exactly what they can do today. Expenses start
  visible to you alone (they include what you pay your coaches); tick "Ver gastos" on
  a title to share them.
- **A club adds its board in one step**: "Agregar cargos de club" adds Presidente,
  Tesorero, Secretario, Director and Delegado with sensible permissions you can change.
  Each appointment has a term (from, to). When the board changes, end the old terms and
  start the new ones; who held what and when stays in the history.
- **Students can see the board.** Titles you mark as public show on the student page,
  with a contact only if that officer chooses to share one.

## What exists today

- **Roles** (`app.roles`): `Role` is `owner`, `admin` or `coach`, one `staff` row per
  person and gym (`PRIMARY KEY (gym_id, person_id)`, migration 0001). Sessions:
  `StaffSession` (any role, 63 uses), `AdminSession` (owner and admin, the gym's setup,
  89), `LedgerSession` (owner and admin, money, 47), `OwnerSession` (owner, 3: deleting a
  member among them), and `SeesMoney` (8), which hides amounts from a coach. A further
  16 call sites call `role_in_gym` directly (`sessions.py`, `join.py`,
  `session_blocks.py`, `staff.py`, `me.py`, `member_roll.py`, `custom_fields.py`,
  `ledger_export.py`).
- **Staff API** (`app.api.staff`): invite (through `join_gym`), change role, revoke
  (deletes the `staff` row; 0005 ends the person's session here). Owner and admin manage
  staff, an admin only coaches; the owner's row is not changed here.
- **RLS by role name.** Every policy that keys off a role repeats
  `s.role IN ('owner', 'admin')` as a subselect on `staff`: `ledger_entry_by_role`
  (0006), `session_delete_by_role` (0033), `charge_group`, `charge_group_member`,
  `extra_line` and `extra_charge` (0037), `audit_event_read` (0044), and the correction
  insert (0048). Each policy is one `USING` and `WITH CHECK` for reads and writes alike.
  Person visibility (0003), forgetting (0032, 0044) and the roster ask only whether a
  `staff` row exists.
- **Frontend**: `GET /api/me/role` answers the role; `readsLedger` and `managesGym`
  (`frontend/src/api/me.ts`) test `'owner' | 'admin'`, and a few routes test the role
  string inline (`PersonWelcome`, `PersonPlan`, `PersonActions`, `StaffSettings`).
  Ajustes › Equipo (`StaffSettings.tsx`) lists people with one role each.
- **Money in**: the ledger (`ledger_entry`, append-only), `v_monthly_income` (Cobrado,
  dated by `validated_at`, in the gym's timezone; `extra_income_clp` since 0037), Cobros
  extra (#195: `extra_charge` with category `rifa`, `seminario`, `equipamiento`,
  `gasto_compartido`, `otro`), and the accountant export (#40, `app.ledger_export`: one
  CSV, or an XLSX with Movimientos, Por validar and Totales).
- **Uploads**: the blob store (`app.integrations.blobstore`) takes JPEG, PNG, WebP,
  HEIC and PDF up to 10 MB through presigned URLs; proofs live under
  `proofs/<gym_id>/<person_id>/`.
- **Audit**: `audit_event` (0044, 0048), readable by owner and admin, insert-only for
  `rakin_app` under a policy per action (`docs/design/billing-corrections.md`).
- **Jobs**: `app.jobs.daily` runs per gym each night (billing, lapse, overdue).

## Part one: titles and permissions

### 1. The model (question 6)

Three ideas, kept apart:

| Idea | What it is | Where |
|---|---|---|
| **On the team** | The person is staff here: sees the roster and the schedule, signs in to the admin screens | `staff` row (as today) |
| **Title** (cargo) | What they are called and shown as: Presidente, Tesorera, Coach. Editable per gym | `gym_title` |
| **Permission** | What a title lets them do. A fixed list Rakin defines | `gym_title.permissions` |

A person holds **zero or more titles**, each for a **term**; their permissions are the
**union** of the titles they hold today. The **owner** is a flag on their `staff` row,
not a title: they hold every permission, always, and nothing in Equipo can take it away.

The permissions. The issue lists seven; an eighth, "set up the gym", is what
`ADMIN_ROLES` covers today (plans, prices, schedule, settings, bank details), and
without it today's admin could not be mapped exactly. A ninth, narrow one, `members_add`,
keeps what a coach does today (footnote ¹ below).

| Permission (code) | In Ajustes | What it opens | Today |
|---|---|---|---|
| `money_read` | Ver ingresos | Pagos, the Libro, amounts anywhere (`SeesMoney`), Cobrado and Esperado, the export, corrections' history | `LEDGER_ROLES` reads |
| `money_write` | Registrar pagos | Record and validate payments, corrections, cobros extra, start, change, freeze or cancel a student's plan. Implies `money_read` | `LEDGER_ROLES` writes |
| `expenses_read` | Ver gastos | Gastos, Finanzas, the export's Gastos sheet | new |
| `expenses_write` | Registrar gastos | Record, correct and void expenses; gastos fijos; categories. Implies `expenses_read` | new |
| `members_manage` | Gestionar alumnos | Add and edit people and their data, join requests, groups, Dar de baja | coach adds, admin the rest |
| `attendance` | Tomar asistencia | Run a class: attendance, notes, the timer, on any session | coach (own sessions) |
| `gym_setup` | Configurar gimnasio | Plans and prices, programs, schedule, custom fields, grading, theme, bank details | `ADMIN_ROLES` |
| `team_manage` | Gestionar equipo | Invite, give and end titles, edit titles (under the rule in section 4) | owner; admin for coaches |

Two rules keep the list honest:

- **Implication is stored, not inferred at read time.** A title with `money_write`
  always has `money_read` too: the API adds it on save and a CHECK refuses one without
  it. So every check is one membership test, at the API and in SQL.
- **Owner-only stays owner-only.** Deleting a student for good (`OwnerSession`), and the
  owner's own row, are not a permission any title can hold.

**Being on the team without permissions** is allowed: a club's Director may be listed
only to be shown to students. They still read the roster and the schedule, as a coach
does today. A title meant only for display, held by someone who is not otherwise staff,
is the same: holding any title makes them staff.

### 2. Defaults (question 7)

Every gym gets two titles in the migration, built from its roles:

| Title | Permissions | Public on the student page |
|---|---|---|
| Dueño (the flag, not a title) | everything | yes |
| **Administrador** | `money_read`, `money_write`, `members_manage`, `attendance`, `gym_setup`, `team_manage` | no |
| **Coach** | `attendance`, `members_add` (footnote ¹) | yes |

"Agregar cargos de club" in Equipo adds five more, each editable or removable:

| Title | Permissions | Why |
|---|---|---|
| **Presidente** | `money_read`, `expenses_read`, `team_manage` | Sees everything and answers for it; changes nothing in money unless also Tesorero |
| **Tesorero** | `money_read`, `money_write`, `expenses_read`, `expenses_write` | Runs the money in and out |
| **Secretario** | `members_manage` | The roster, the minutes, the members; no money |
| **Director** | none | A board seat, shown to members |
| **Delegado** | `attendance` | Takes a team to a competition, marks who came |

The permission matrix, with the owner:

| | Ver ingresos | Registrar pagos | Ver gastos | Registrar gastos | Gestionar alumnos | Tomar asistencia | Configurar gimnasio | Gestionar equipo |
|---|---|---|---|---|---|---|---|---|
| Dueño | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Administrador | ✓ | ✓ | – | – | ✓ | ✓ | ✓ | ✓ |
| Coach | – | – | – | – | ✓¹ | ✓ | – | – |
| Presidente | ✓ | – | ✓ | – | – | – | – | ✓ |
| Tesorero | ✓ | ✓ | ✓ | ✓ | – | – | – | – |
| Secretario | – | – | – | – | ✓ | – | – | – |
| Director | – | – | – | – | – | – | – | – |
| Delegado | – | – | – | – | – | ✓ | – | – |

¹ Today a coach can add a student without a plan and nothing else of what
`members_manage` covers. Giving the Coach title the whole of `members_manage` would
widen what coaches can do, so the migration does not: the Coach title gets `attendance`
only, plus `members_add`, a ninth code that is the narrow "add a student" a coach has
today and is shown in Ajustes as "Agregar alumnos". `members_manage` implies it. Ticket
3 confirms the exact set by walking the 63 `StaffSession` endpoints; if a coach does
less than this, the title gets less.

**How today's three roles map without a gym noticing:**

- `owner` → `staff.owner = true`. No title.
- `admin` → the Administrador title, term from the `staff` row's `created_at`, open.
- `coach` → the Coach title, the same.

Every endpoint answers as before for each of the three (ticket 1's equivalence test).
Expenses are new, so no one loses anything by them starting owner-only; an academy
whose admin runs the money ticks "Ver gastos" on Administrador. The reason not to
grant it by default: Sueldos y honorarios is what the gym pays its staff, and an admin
reading every coach's pay the day the feature ships is the surprise to avoid.

A coach "runs their own session" today and an admin any session. With `attendance`
the rule stays: a holder of `attendance` runs a session they coach; one with
`gym_setup` too runs any, as admins do now. A Delegado with `attendance` alone marks
the sessions they are put on as coach.

### 3. Where it is stored

```sql
staff                       -- as today, one row per person and gym: "on the team"
  + owner boolean NOT NULL DEFAULT false
    -- UNIQUE (gym_id) WHERE owner: one owner per gym
  role                      -- kept, then dropped in ticket 6

gym_title
  id uuid PK, gym_id
  name text                 -- "Tesorera", unique per gym (lower)
  permissions text[]        -- CHECK ⊆ the known list; money_write ⇒ money_read, etc.
  public boolean            -- shown on the student page
  preset text NULL          -- 'admin' | 'coach' | 'presidente' | … : where it came from
  sort int, archived_at timestamptz NULL

staff_title                 -- an appointment: who held which title, from when to when
  id uuid PK, gym_id, person_id, title_id
  starts_on date NOT NULL
  ends_on date NULL         -- the last day; NULL is open
  public_contact text NULL  -- 'email' | 'phone' | NULL: what members may see (section 7)
  created_by, created_at, ended_by NULL, ended_at NULL
  CHECK (ends_on IS NULL OR ends_on >= starts_on)
```

An appointment is **current** when `starts_on <= today <= coalesce(ends_on, today)`,
"today" in the gym's timezone (`gym.timezone`, as `v_monthly_income` uses). A
`staff_title` row is never deleted while the person is in the gym: ending one sets
`ends_on`. Forgetting a person (`forget_gym_person`) deletes theirs, as it does every
other record of them.

**The staff row follows the appointments.** Today revoking deletes the `staff` row and
0005 ends the session. Now: ending a person's last current appointment (by hand, or
`ends_on` passing) deletes the `staff` row unless they are the owner, and the nightly
job (`app.jobs.daily`) does it for terms that ran out, so 0005's session end still
fires. A future appointment (a new board from 1 March) creates the row on its
`starts_on`, by the same job, so the incoming tesorero is not staff early.

### 4. Who manages it (question 9)

The owner, and anyone holding `team_manage`, under one rule that reproduces today's
"an admin manages coaches only" and extends to any title:

> You may give, end or change an appointment only for a person whose permissions are
> **strictly fewer** than yours, and only with a title whose permissions are
> **strictly fewer** than yours. Editing a title's permissions needs the same of the
> title, before and after.

- The owner holds everything plus the flag, so no one but the owner touches the owner,
  and the owner touches everyone.
- An Administrador (no expenses) cannot touch another Administrador (equal) or a
  Tesorero (who holds expenses), and can appoint and end Coaches, as today.
- A Presidente (`money_read`, `expenses_read`, `team_manage`) can appoint a Secretario
  or a Delegado, not a Tesorero (who records money the Presidente does not). For a
  Presidente to appoint the next Tesorero, the owner gives Presidente the money
  permissions too, or does it.
- Nobody grants a permission they lack.

**A board that changes each year.** The new board is entered as appointments with
their `starts_on`; the outgoing ones get `ends_on` the day before. Equipo's "Cambio de
directiva" does both in one form: pick each board title, the incoming person and the
date. Nothing is lost: the history card lists every appointment, newest first, as
"Tesorera · M. Pérez · mar 2025 – feb 2026".

**Who owns a club.** The owner is whoever opened the gym in Rakin, often the head
coach or the first presidente. Handing the ownership over (a presidente leaving) is
not in this design: it is rare, it is the one change that must not be undone by
mistake, and today it is a support request. It is noted as out of scope, not filed.

### 5. Enforcement (question 8)

**API.** `app.roles` becomes `app.permissions`:

```python
class Permission(StrEnum):
    MONEY_READ = "money_read"; MONEY_WRITE = "money_write"
    EXPENSES_READ = "expenses_read"; EXPENSES_WRITE = "expenses_write"
    MEMBERS_MANAGE = "members_manage"; MEMBERS_ADD = "members_add"
    ATTENDANCE = "attendance"; GYM_SETUP = "gym_setup"; TEAM_MANAGE = "team_manage"

async def permissions_in_gym(session, tenant) -> frozenset[Permission] | None
    # None: not on the team. The owner: every permission.

def requires(*needed: Permission)   # any staff when empty; else holds all of `needed`
```

One query per request, as `role_in_gym` is today: the `staff` row, the owner flag and
the union of current appointments' permissions. The session aliases keep their names
and move underneath, so ticket 1 changes no endpoint:

| Today | Becomes |
|---|---|
| `StaffSession` | `requires()`: on the team |
| `LedgerSession` | `requires(MONEY_READ)` for GETs, `requires(MONEY_WRITE)` for writes (ticket 3 splits them; ticket 1 maps it to `MONEY_WRITE`, which every admin holds) |
| `AdminSession` | `requires(GYM_SETUP)` |
| `OwnerSession` | the owner flag |
| `SeesMoney` | `MONEY_READ in permissions` |

**The database.** One function, used by every policy instead of a role list:

```sql
CREATE FUNCTION app_can(p text) RETURNS boolean STABLE LANGUAGE sql AS $$
  SELECT EXISTS (
    SELECT FROM staff s
    WHERE s.gym_id = current_gym() AND s.person_id = current_person()
      AND (s.owner OR EXISTS (
        SELECT FROM staff_title st JOIN gym_title t ON t.id = st.title_id
        WHERE st.gym_id = s.gym_id AND st.person_id = s.person_id
          AND p = ANY (t.permissions) AND <current in the gym's timezone>)))
$$;
```

It runs as the invoker, under the same RLS as the subselects it replaces (`staff` and
the two new tables are themselves gym-isolated). Each role-keyed policy is rewritten,
and split into read and write where today one `ALL` policy serves both:

| Policy (migration) | Read | Write |
|---|---|---|
| `ledger_entry_by_role` (0006) | `app_can('money_read')` | `app_can('money_write')` |
| `extra_charge`, `extra_line` (0037) | `money_read` | `money_write` |
| `charge_group`, `charge_group_member` (0037) | gym (as now) | `money_write` |
| `session_delete_by_role` (0033) | — | `gym_setup` |
| `audit_event_read` (0044) | `money_read`, or `expenses_read` for expense actions | — |
| correction insert (0048) | — | `money_write` |
| expense tables (new, part two) | `expenses_read` | `expenses_write` |

The students' own policies (their entries, their dependents', their proof claims)
are about the person acting, not a role, and stay as they are.

**The migration path**, so no step changes what anyone can do:

1. Tables, the owner flag, the two titles per gym from today's roles; the API reads
   permissions; `staff.role` is still written by the staff API alongside the
   appointments, so the old policies still hold (ticket 1).
2. `app_can` and the policies rewritten (ticket 2). From here the database no longer
   reads `staff.role`.
3. Endpoints by permission, and Equipo (tickets 3 and 4).
4. `staff.role` dropped once nothing reads it, `Role` removed (ticket 6).

**Tests that each permission holds at the database.**

- `test_permissions_rls.py`, parametrised over the table above: for each protected
  table and each of read and write, a person holding only that permission succeeds, a
  person holding every permission but that one gets no rows or a policy error, and a
  person whose appointment ended yesterday gets nothing. Run as `rakin_app` against the
  real database, as `test_ledger_by_role` does today.
- A drift test: no row of `pg_policies` mentions `role` in its `qual` or `with_check`
  (after ticket 2), and every table with a `_by_role` or `_by_permission` policy is in
  the parametrised list, so a new money table cannot ship without its case.
- Ticket 1's equivalence test: for owner, admin and coach fixtures, every route in the
  app answers the same status before and after (`app.routes`, parametrised).

### 6. The UI (question 10)

**Ajustes › Equipo**, in the Ajustes layout (#241): a head with "Invitar", then three
cards: **Personas**, **Cargos** and **Historial**.

At 390:

```
┌──────────────────────────────┐
│ Equipo                       │
│ Quién está en el equipo y    │
│ qué puede hacer.             │
│ [        Invitar         ]   │
├──────────────────────────────┤
│ Personas                     │
│ ┌──────────────────────────┐ │
│ │ Ana Rojas                │ │
│ │ (Dueña)                  │ │
│ ├──────────────────────────┤ │
│ │ Pablo Soto            ›  │ │
│ │ (Presidente) (Coach)     │ │
│ │ hasta feb 2026           │ │
│ ├──────────────────────────┤ │
│ │ Marta Díaz            ›  │ │
│ │ (Tesorera)               │ │
│ └──────────────────────────┘ │
│ [Cambio de directiva]        │
├──────────────────────────────┤
│ Cargos                       │
│ Presidente  Ver ingresos,  › │
│             Ver gastos, Eq…  │
│ Tesorero    Ingresos y     › │
│             gastos           │
│ [Nuevo cargo]                │
│ [Agregar cargos de club]     │
├──────────────────────────────┤
│ Historial                  ▾ │
└──────────────────────────────┘
```

A person opens in place: their appointments, each a title, a "Desde" and an optional
"Hasta", "Terminar cargo" (sets Hasta to yesterday after a confirm) and "Agregar cargo";
below, read-only, "Puede:" and the union of permissions in words. Shown only to whoever
may change them (section 4); others see the row without the chevron.

At 1280, Personas is a table and a title opens beside it:

```
┌ Sidebar ┬──────────────────────────────────────────────────────────────────┐
│         │ Equipo                                          [ Invitar ]      │
│         │ Quién está en el equipo y qué puede hacer.                        │
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Personas                                                          │
│         │ Nombre        Cargos                     Período          Puede   │
│         │ Ana Rojas     Dueña                      —                Todo    │
│         │ Pablo Soto    Presidente · Coach         mar 25 – feb 26  6 de 9 ›│
│         │ Marta Díaz    Tesorera                   mar 25 – feb 26  4 de 9 ›│
│         │ [Cambio de directiva]                                             │
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Cargos                                                            │
│         │ Cargo       Ingresos  Pagos  Gastos  Reg.gastos  Alumnos  Asist… │
│         │ Presidente     ✓        –      ✓        –          –        –    │
│         │ Tesorero       ✓        ✓      ✓        ✓          –        –    │
│         │ [Nuevo cargo]   [Agregar cargos de club]                          │
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Historial                                                       ▾ │
└─────────┴──────────────────────────────────────────────────────────────────┘
```

A title opens to its name, "Visible para los alumnos", and one checkbox per
permission with its line of help ("Ver gastos: incluye sueldos y honorarios"). A
checkbox the editor may not grant is disabled with the reason.

**Invitar** asks what it asks today (RUT, name, email, phone) and, instead of the role
radio, one or more titles (checkboxes, at least one), "Desde" (today) and an optional
"Hasta". The invite email names the titles ("te invitó como Tesorera").

**What a member sees.** On the student page, a card "Directiva y equipo" lists the
current holders of public titles: name, titles, and the contact they chose to share
(`staff_title.public_contact`: email, phone or nothing; nothing by default). Only
current appointments; never permissions; never ended ones. A gym with no public titles
shows no card.

### 7. Privacy

- A title being public shows the officer's name and title only. A phone or email shows
  only if the officer turns it on for that appointment, in their own Mi cuenta or when
  appointed; the owner cannot publish someone else's phone.
- The Historial card is staff-only and shown to `team_manage` holders.
- The privacy notice gains one sentence: the gym may show its officers' names and
  titles to its members.

## Part two: expenses

### 8. What an expense is (question 1)

| Field | Required | Notes |
|---|---|---|
| Fecha (`spent_on`) | yes | The day it was paid; it decides the month |
| Monto (`amount_clp`) | yes | CLP, integer, > 0 |
| Categoría | yes | The gym's list (below) |
| Pagado a (`payee`) | no | Free text: "Inmobiliaria X", "Enel", the coach's name |
| Método | no | Transferencia, efectivo, tarjeta, otro (the ledger's methods plus tarjeta) |
| Nota | no | |
| Comprobante | no | A photo or PDF, through the blob store, under `receipts/<gym_id>/` |
| Gasto fijo | no | The template it came from (section 9) |
| Cobro extra | no | The cobro that recovers it (section 12) |

**Categories** (`expense_category`, per gym), seeded on the gym's first visit to
Gastos, or in the migration for gyms that exist: Arriendo, Luz, Agua, Gas, Internet y
teléfono, Federación, Seguros, Sueldos y honorarios, Equipamiento, Eventos y
competencias, Mantención y aseo, Otros. Rename, add, reorder, hide. A category with
expenses is archived, never deleted, so last year's report still reads. Otros cannot be
archived; it is where an archived category's future expenses would go if needed.

A receipt reuses the proofs path: `POST /api/expenses/receipt-upload` presigns a key
under the gym's receipts prefix (same types, same 10 MB), and recording the expense
claims the key as the proof claim does (the key must be under that prefix and the
object must exist). Downloads are presigned by an endpoint that requires
`expenses_read`, so the key itself opens nothing.

### 9. Recurring costs (question 2)

**A template that pre-fills the month, confirmed by a person. No automatic entries.**

`expense_recurring`: category, payee, method, `amount_clp` and `amount_kind`
(`fixed`: rent, internet; `estimated`: power, water, gas, where the amount is last
month's and only a hint), the day of the month it is usually paid, `active`.

Gastos opens on the month, and above the list a card **"Gastos fijos por registrar"**
lists the active templates with no expense from them this month:

```
Gastos fijos por registrar · noviembre
  Arriendo     $650.000   día 5     [Registrar]
  Internet      $32.990   día 10    [Registrar]
  Luz          ~$84.000   día 20    [Registrar…]
  [Registrar los 2 fijos]
```

A fixed one records in one tap at its amount, dated its day (or today, if earlier). An
estimated one opens the form pre-filled, with the amount selected for typing the
bill's figure. "Registrar los fijos" records every fixed one at once. A template can be
skipped for a month ("No este mes"), which hides it until next month.

Why not create them automatically: an expense Rakin writes on the 5th that was paid on
the 9th, or not at all because the landlord agreed a month off, makes the month's
result wrong with nobody having said so, and the person reading Finanzas cannot tell an
expense someone confirmed from one a job invented. The card makes the monthly task one
tap and leaves the record true. If owners later ask for it anyway, a template can gain
"registrar solo" for fixed amounts; nothing here prevents it.

### 10. Where it lives (question 3)

Its own tables, never in the ledger:

```sql
expense_category (id, gym_id, name, sort, archived_at)
expense_recurring (id, gym_id, category_id, payee, method, amount_clp, amount_kind,
                   day_of_month, active, created_by, created_at)
expense (id, gym_id, spent_on, amount_clp, category_id, payee, method, note,
         receipt_object_key, recurring_id NULL, extra_charge_id NULL,
         created_by, created_at, voided_at NULL, voided_by NULL, void_reason NULL)
expense_skip (gym_id, recurring_id, month)   -- "No este mes"
```

- **Billing cannot read it.** No foreign key from any billing table points at these,
  and none of `v_balance`, `v_monthly_income`, `app.domain.billing`, the overdue job or
  the student page reads them. A test asserts it, as #295's does for history: recording
  and voiding expenses leaves every billing view and a member's balance byte-identical.
- **RLS**: read with `app_can('expenses_read')`, write with
  `app_can('expenses_write')`, isolated to the gym for the owner role (jobs, seed), as
  the money tables are (0037's `_money`, without the `own` policy: no member has
  expenses).
- **Correcting**: an expense is a record of the gym's, not a member's debt, so it can
  be edited, unlike a ledger entry. Every edit writes an `audit_event`
  (`expense_changed`, with `before` and `after` of the changed fields); **voiding**
  ("Anular", with a reason) sets `voided_at` and writes `expense_voided`. A voided
  expense stays in the list, struck through, and out of every total. Nothing deletes an
  expense; `rakin_app` has no DELETE grant on it.
- **Audit visibility**: `audit_event_read` today lets owner and admin read every row.
  Expense rows must not reach an Administrador without `expenses_read`, so ticket 2's
  rewrite splits the policy by action, as section 5's table says.
- **Forgetting a person** does not touch expenses: they name a payee in text, not a
  person. An expense's `created_by` is kept (the gym's record of who typed it), as
  `ledger_entry.recorded_by` is.

### 11. The view (question 4)

A new page **Finanzas** in the shell, beside Pagos, for anyone with `expenses_read`.
Gastos (the list and the form) is its second tab.

**The month**, from what the person may see:

```
Noviembre 2026                               [‹] [›]
┌───────────────┬───────────────┬───────────────┐
│ Entradas      │ Salidas       │ Resultado     │
│ $2.430.000    │ $1.512.990    │ +$917.010     │
└───────────────┴───────────────┴───────────────┘
Entradas    Cuotas y planes       $2.110.000
            Cobros extra            $320.000
Salidas     Arriendo                $650.000
            Sueldos y honorarios    $600.000
            Luz                      $84.000
            …
```

- **Entradas** is Cobrado as Pagos shows it (`v_monthly_income`, net of refunds,
  dated by `validated_at`), split into plans and cobros extra (`extra_income_clp`). It
  is the same figure as Pagos, so they never disagree.
- **Salidas** is the month's non-voided expenses by `spent_on`, by category.
- A person with `expenses_read` but not `money_read` (a gym could make such a title)
  sees Salidas only, with no Entradas or Resultado.
- **The year**: twelve rows (or bars at 1280), Entradas, Salidas and Resultado per
  month, and the year's totals; a category's row opens to its months.

**The accountant export** (#40) gains, for a person with `expenses_read`:

- XLSX: a **Gastos** sheet (Fecha, Categoría, Pagado a, Método, Monto, Nota,
  Comprobante: yes or no, Estado: Anulado for voids, listed apart as Por validar is
  today) and a **Resumen** sheet (Entradas, Salidas by category, Resultado).
- CSV: a separate "Gastos del mes (CSV)" download beside today's, since a CSV holds one
  table.
- Someone with `money_read` only gets today's file, unchanged.

### 12. Money that is not the gym's (question 5)

A trip, a seminar, a group's gear: the gym pays and the members pay it back through a
Cobro extra (#195, whose category `gasto_compartido` exists for this).

**Link the expense to the cobro, one way, and keep both gross.** An expense may name
the cobro extra that recovers it (`expense.extra_charge_id`; many expenses to one
cobro: the bus and the hotel). Then:

- The cobro's detail shows **"Gastos asociados $X · Recaudado $Y · Diferencia $Y−X"**,
  to whoever holds both `money_read` and `expenses_read`.
- Finanzas keeps Entradas and Salidas gross, since the bank saw both movements, and
  adds one line under Resultado: "De esto, gastos recuperados con cobros extra: $X
  pagado, $Y recaudado".
- Nothing nets automatically, and the cobro's billing does not change: a member's line
  still owes what the cobro says.

Why not net: the accountant needs both movements, and a cobro that collected less than
it cost is exactly what the owner wants to see, not hidden.

## Out of scope

- Transferring a gym's ownership (section 4).
- Budgets, forecasts, bank reconciliation, invoices (facturas) and tax (IVA). Rakin
  records what was paid; the accountant does the rest.
- Per-category privacy (hiding Sueldos y honorarios from a Tesorero). `expenses_read`
  is all or nothing; if a club asks, a category can gain "solo el dueño" later.
- Officers across gyms (one federation, several clubs).

## Build tickets

In order. Each is one PR. The permissions come first; expenses need
`expenses_read` and `expenses_write` to exist, and the tables of part two are created
with `app_can` policies from the start.

1. **#308 Permisos detrás de los roles.** `gym_title`, `staff_title`, `staff.owner`;
   the migration that turns each gym's roles into Administrador and Coach appointments;
   `app.permissions` (`Permission`, `permissions_in_gym`, `requires`); the session
   aliases redefined over permissions; `GET /api/me/role` adds `permissions`;
   `readsLedger` and `managesGym` and the inline role tests read them; the staff API
   keeps writing `staff.role` in step. The equivalence test over every route. No
   visible change.
2. **#309 RLS por permiso.** `app_can`; every role-keyed policy rewritten and split read
   and write (section 5's table), `audit_event_read` split by action; the parametrised
   RLS test and the drift test.
3. **#310 Endpoints por permiso.** Walk the `StaffSession`, `LedgerSession` and
   `role_in_gym` call sites: GETs to `money_read`, writes to `money_write`, members to
   `members_manage` or `members_add`, classes to `attendance`; the staff API's
   strictly-fewer rule with `team_manage`. Tests per area.
4. **#311 Equipo: cargos, períodos e historial.** Personas, Cargos and Historial in
   Ajustes › Equipo (390 and 1280); several titles per person with terms; Invitar with
   titles; "Agregar cargos de club"; "Cambio de directiva"; the nightly job that adds
   and removes `staff` rows as terms start and end.
5. **#312 Directiva en la página del alumno.** Public titles, `public_contact` chosen by
   the officer, the card on the student page, the privacy notice's sentence.
6. **#313 Retirar `staff.role`.** Drop the column and `Role` once nothing reads them;
   the drift test extended to the code.
7. **#314 Gastos.** `expense`, `expense_category` with the defaults; record, edit with
   audit, void with a reason; the receipt upload; the Gastos list by month; the test
   that billing is untouched.
8. **#315 Gastos fijos.** `expense_recurring`, `expense_skip`; the "por registrar" card;
   one-tap fixed, pre-filled estimated, "Registrar los fijos", "No este mes".
9. **#316 Finanzas: el mes y el año.** The page, Entradas from `v_monthly_income`,
   Salidas by category, Resultado, the year view; Salidas only without `money_read`.
10. **#317 Exportación con gastos.** The Gastos and Resumen sheets, the CSV download,
    gated on `expenses_read`.
11. **#318 Gastos recuperados con cobros extra.** `expense.extra_charge_id`, the picker
    in the form, the cobro's "Gastos asociados" line, Finanzas' recovered line.

Tickets 7 onward need only 1 and 2; 3 to 6 can go in parallel with them.
