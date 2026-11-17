# Expenses and club officers: where the money goes, and who sees it (#307)

Spike, November 2026. No product code: this doc decides what a gym's expense is, where
it is kept so billing never reads it, how money in and money out sit side by side, and,
because who may see expenses depends on it, how a gym defines its own roles (titles
and the permissions each carries), how a board hands over to the next one, and how the
account itself changes hands. The build tickets at the end carry it out, in order:
permissions first, then the handover, then expenses.

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
- **Your gym defines its roles.** A role (cargo) is a name you choose (Presidente,
  Tesorera, Coach, Encargada de cobranza) and a set of permissions you tick from
  Rakin's list: see money in, record payments, see expenses, record expenses, manage
  students, take attendance, set up the gym, manage the team. A person can hold several
  roles and can do what any of them allows.
- **Presets are a starting point, not the rules.** When you set up, pick "Academia"
  (Administrador, Coach) or "Club federado" (Presidente, Tesorero, Secretario, Director,
  Delegado, Coach), then rename, change or delete any of them, or start from nothing.
- **You can never lock yourself out.** Whoever holds the account (the person who set
  Rakin up for the gym and pays for it, the *titular*) always has every permission.
  Nothing in Equipo can take it away, and there is always exactly one titular.
- **Nothing changes for a gym that exists today.** Its admins and coaches become the
  roles "Administrador" and "Coach" with exactly what they can do now. Expenses start
  visible to the titular alone (they include what you pay your coaches); tick "Ver
  gastos" on a role to share them.
- **Cambio de mando is one step, not twenty edits.** When a board's term ends, start a
  cambio de mando: who takes each seat, from which day. The incoming people accept; on
  that day the new board gets its access and the old one loses it, with no day where
  nobody can manage the gym and, unless you choose otherwise, no day where both boards
  handle the money. If the outgoing side has vanished, the titular can push it through,
  with a reason, and it is recorded.
- **The new board starts informed.** On day one it gets an *acta de traspaso*: money
  in and out during the last term, what is owed, proofs waiting, open cobros extra,
  recent corrections and the gastos fijos. The outgoing board keeps a record of its
  term, in figures, with nothing personal about any member.
- **Handing the account over** (the titular leaves, the club changes treasurer for
  good) is its own, stricter flow: the incoming titular must accept and sign in again,
  and the change waits a few days so the outgoing one can stop a mistake.
- **Everything is on the record**: every role created or changed, every appointment,
  every cambio de mando and every override, in the gym's audit log.
- **Students can see the board.** Roles you mark as public show on the student page,
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
  staff, an admin only coaches; the owner's row is not changed here, so a gym always
  keeps its owner. There is no way to hand the owner's row to someone else.
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
- **Sign-in**: an emailed link or a sign-in code (0047), per gym; a fresh code is the
  only proof Rakin has that the person at the keyboard holds the address.
- **Jobs**: `app.jobs.daily` runs per gym each night (billing, lapse, overdue).

## Lessons from an earlier design

The owner has solved board positions, permissions per position and terms of office
before, in another product. What carried over, in this doc's terms:

- **Never gate on a title's name.** A check that says "the presidente may" breaks the
  day a gym renames the role or gives two people the seat. Every check here reads a
  permission; the name is only shown.
- **Each permission is its own thing.** Two permissions that hold the same people today
  are still two codes, never one defined as the other, so narrowing one later does not
  silently narrow the other. A test pins them apart.
- **A term is a row, never a column.** A "term ends on" field on the person is
  overwritten by the next term and takes the history with it. Each appointment is its
  own row; a re-election is a new row; a typo is corrected on the row, with before and
  after in the audit log, and never changes who held it or which seat.
- **The row remembers the seat as it was.** A role renamed or deleted later must not
  rewrite who was "Tesorera" in 2025, so an appointment keeps the role's name at the
  time beside the link to it.
- **Terms are half-open.** An appointment's end day is the first day without it, so the
  successor's term starts on that same day: no gap and no overlap, re-elections
  included.
- **Overlap is checked under a lock per person.** "Does this person already hold this
  seat then?" is a read followed by a write; two requests at once both pass the read.
  A transaction-scoped advisory lock on the person serialises them, which is cheaper
  than an exclusion constraint for a handful of writes a year.
- **Changing a seat's permissions is a permission change**, and is audited as one,
  with the permissions before and after.
- **Whoever proposes a change does not confirm it.** The person who starts a handover
  cannot accept a seat for someone else; acceptance is the incoming person's own act,
  signed in as themselves.
- **What members see is its own, minimal answer.** The board shown to students is a
  separate response with a fixed list of fields, tested for leaking anyone's email,
  RUT or id, not the staff list with fields removed.
- **A seat with no term on record is shown, not hidden**, marked "sin fecha", and a
  term about to end warns the people who must renew it, well before it does.

## Part one: roles, permissions and the cambio de mando

### 1. The model (question 6)

Four ideas, kept apart:

| Idea | What it is | Where |
|---|---|---|
| **Titular** | The person who holds the account: set Rakin up for the gym, pays for it, always holds everything. Exactly one per gym | `staff.account_holder` |
| **On the team** | The person is staff here: sees the roster and the schedule, signs in to the admin screens | `staff` row (as today) |
| **Role** (cargo) | What they are called and what they may do: a name and a set of permissions. **Defined by the gym** | `gym_title` |
| **Appointment** (mandato) | A person holding a role from one day to another | `staff_title` |

A person holds **zero or more appointments**; their permissions are the **union** of
the roles they hold today. Roles belong to the gym: the titular (and whoever they let)
creates them, names them, ticks their permissions, marks them public, archives them.
Rakin defines only the **list of permissions** and the presets (section 2).

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
| `members_manage` | Gestionar alumnos | Add and edit people and their data, join requests, groups, Dar de baja. Implies `members_add` | admin |
| `members_add` | Agregar alumnos | Add a student without a plan and keep their record (contact, fields, family, requirements, join requests), as a coach can today | coach |
| `attendance` | Tomar asistencia | Run a class: attendance, notes, the timer, on a session they coach | coach (own sessions) |
| `gym_setup` | Configurar gimnasio | Plans and prices, programs, schedule, custom fields, grading, theme, bank details; run any session | `ADMIN_ROLES` |
| `team_manage` | Gestionar equipo | Invite, appoint and end appointments, create and edit roles, start a cambio de mando (under section 4's rule) | owner; admin for coaches |

Rules that keep the list honest:

- **Implication is stored, not inferred at read time.** A role with `money_write`
  always has `money_read` too: the API adds it on save and a CHECK refuses one without
  it. So every check is one membership test, at the API and in SQL.
- **Each code is its own literal** (the lesson above). `money_read` and `expenses_read`
  hold the same people in a new gym and are never written as one another.
- **Titular-only stays titular-only.** Deleting a student for good (`OwnerSession`
  today), transferring the account (section 6) and overriding a stalled cambio de mando
  (section 5) are not permissions any role can hold.

**Being on the team without permissions** is allowed: a club's Director may be listed
only to be shown to students. They still read the roster and the schedule, as a coach
does today.

### 2. Presets, and today's three roles (question 7)

A preset is a list of roles a gym can add in one step, then change at will. Nothing
in the code reads a preset's name or knows which preset a role came from except to
show "de la plantilla Club federado" in Cargos. Applying a preset twice adds nothing
twice (by name); applying a second preset adds its roles beside the first's.

**Academia** (what every existing gym gets in the migration):

| Role | Permissions | Public on the student page |
|---|---|---|
| **Administrador** | `money_read`, `money_write`, `members_manage`, `members_add`, `attendance`, `gym_setup`, `team_manage` | no |
| **Coach** | `attendance`, `members_add` ¹ | yes |

**Club federado**:

| Role | Permissions | Why |
|---|---|---|
| **Presidente** | `money_read`, `expenses_read`, `team_manage` | Sees everything and answers for it; changes nothing in money unless also Tesorero |
| **Tesorero** | `money_read`, `money_write`, `expenses_read`, `expenses_write` | Runs the money in and out |
| **Secretario** | `members_manage`, `members_add` | The roster and the members; no money |
| **Director** | none | A board seat, shown to members |
| **Delegado** | `attendance` | Takes a team to a competition, marks who came |
| **Coach** | `attendance`, `members_add` | As in Academia |

The matrix, with the titular:

| | Ver ingresos | Registrar pagos | Ver gastos | Registrar gastos | Gestionar alumnos | Agregar alumnos | Tomar asistencia | Configurar gimnasio | Gestionar equipo |
|---|---|---|---|---|---|---|---|---|---|
| Titular | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Administrador | ✓ | ✓ | – | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| Coach | – | – | – | – | – | ✓ | ✓ | – | – |
| Presidente | ✓ | – | ✓ | – | – | – | – | – | ✓ |
| Tesorero | ✓ | ✓ | ✓ | ✓ | – | – | – | – | – |
| Secretario | – | – | – | – | ✓ | ✓ | – | – | – |
| Director | – | – | – | – | – | – | – | – | – |
| Delegado | – | – | – | – | – | – | ✓ | – | – |

¹ Today a coach can add a student without a plan and nothing else of what
`members_manage` covers, so the Coach role gets `members_add` and not the whole of
it. #310 confirmed the set by walking the `StaffSession` endpoints. A coach does a
little more than add: they edit a student's record (contact, custom fields, family,
requirements) and see and approve join requests, with no plan. `members_add` covers
all of that, as keeping the record of a student one may add, so the Coach role keeps
`attendance` and `members_add` exactly; a promotion is `attendance`, given on the mat.
Groups, the join link, enrolling, Dar de baja and the welcome are `members_manage`,
and RLS writes groups and a `history_set` row with it (migration 0069).

A new gym picks a preset (or none) in its first-run setup; an existing one finds
"Agregar plantilla" in Cargos.

**How today's three roles map without a gym noticing:**

- `owner` → `staff.account_holder = true`. No appointment: the titular holds
  everything by the flag.
- `admin` → an open appointment to Administrador, from the `staff` row's `created_at`.
- `coach` → the same, to Coach.

Every endpoint answers as before for each of the three (#308's equivalence test).
Expenses are new, so no one loses anything by them starting titular-only; an academy
whose admin runs the money ticks "Ver gastos" on Administrador. The reason not to
grant it by default: Sueldos y honorarios is what the gym pays its staff, and an admin
reading every coach's pay the day the feature ships is the surprise to avoid.

A coach "runs their own session" today and an admin any session. With `attendance`
the rule stays: a holder of `attendance` runs a session they coach; one with
`gym_setup` too runs any.

### 3. Where it is stored

```sql
staff                       -- as today, one row per person and gym: "on the team"
  + account_holder boolean NOT NULL DEFAULT false
    -- a partial unique index on (gym_id) WHERE account_holder: never two titulars.
    -- A swap clears the old flag before setting the new one, in one transaction
    -- (section 6), and a DEFERRABLE INITIALLY DEFERRED constraint trigger refuses a
    -- gym with none at commit
  role                      -- kept, then dropped in #313

gym_title                   -- a role, defined by the gym
  id uuid PK, gym_id
  name text                 -- "Tesorera", unique per gym (lower) among unarchived
  permissions text[]        -- CHECK ⊆ the known list, implications included
  public boolean            -- shown on the student page
  preset text NULL          -- which preset added it; shown only
  system text NULL          -- 'read_only_handover' for the one role Rakin keeps
                            -- itself (section 5); NULL for every role the gym made
  sort int, archived_at timestamptz NULL

staff_title                 -- an appointment (mandato)
  id uuid PK, gym_id, person_id, title_id
  title_name text           -- the role's name when appointed: history reads this
  starts_on date NOT NULL
  ends_on date NULL         -- the first day without it; NULL is open
  public_contact text NULL  -- 'email' | 'phone' | NULL (section 9)
  handover_id uuid NULL     -- the cambio de mando that started or ended it
  created_by, created_at, ended_by NULL, ended_at NULL
  CHECK (ends_on IS NULL OR ends_on > starts_on)
```

An appointment is **current** when `starts_on <= today < coalesce(ends_on, infinity)`,
"today" in the gym's timezone (`gym.timezone`, as `v_monthly_income` uses). Writes to
one person's appointments take `pg_advisory_xact_lock` on the gym and person, then
refuse a second appointment to the same role that overlaps (409). Nothing deletes an
appointment while the person is in the gym: ending one sets `ends_on`, and a
correction (dates, contact) is an update with an audit row; the holder and the role
are never changed on a row. Forgetting a person (`forget_gym_person`) deletes theirs,
as it does every other record of them.

A role with appointments, current or past, is **archived**, never deleted: it leaves
Cargos and every picker, and its history still reads. Editing a role's permissions
applies to its current holders at once, and writes `title_changed` with the before and
after.

**Access comes from the dates, never from a job.** A person is **on the team** when
they have a `staff` row *and* are the titular or hold a current appointment;
`permissions_in_gym` and `app_can` (section 7) both test the dates at query time, in
the gym's timezone. So an appointment written today with `starts_on` next month grants
nothing until that day's first second, and one whose `ends_on` is today has already
stopped, whatever has or has not run.

**The staff row follows the appointments**, as housekeeping. Writing a person's first
appointment, current or future, creates their `staff` row in the same transaction, so
there is nothing left to do when the appointment starts. Today revoking deletes the
`staff` row and 0005 ends the session. Now: ending a person's last appointment by hand
deletes the row at once unless they are the titular, and for terms that end on their
date the nightly job (`app.jobs.daily`) deletes it afterwards, so 0005's session end
still fires. Their requests are refused from the start of the day either way, because
the check reads the dates; the job only tidies up and ends the session. A future
appointment's row makes the incoming person visible to the gym (0003) before their
term, which it already is for anyone the gym invited.

### 4. Who manages it, and what can never break (question 9)

The titular, and anyone holding `team_manage`, under one rule that reproduces today's
"an admin manages coaches only" and extends to any role:

> You may appoint, end or correct an appointment only for a person whose permissions
> are **strictly fewer** than yours, and only to a role whose permissions are
> **strictly fewer** than yours. Creating or editing a role needs the same of the role,
> before and after.

"Strictly fewer" means a **proper subset**: every permission they (or the role) hold,
you hold too, and you hold at least one more. It is never a count. A role with two
permissions you lack is not "fewer" because yours has three.

- The titular holds everything plus the flag, so no one but the titular touches the
  titular, and the titular touches everyone.
- An Administrador (no expenses) cannot touch another Administrador (equal) or a
  Tesorero (who holds expenses), and can appoint and end Coaches, as today.
- A Presidente of the Club federado preset (`money_read`, `expenses_read`,
  `team_manage`) can appoint directly **only a Director** (no permissions, a subset of
  anything). A Secretario (`members_manage`), a Delegado (`attendance`) and a Tesorero
  (`money_write`, `expenses_write`) each hold something the Presidente lacks. That is
  deliberate: the Presidente oversees and does not run the roster or the money. The
  board is changed through a cambio de mando, which the Presidente may start and the
  titular confirms (section 5). A gym that wants its Presidente to appoint Secretarios
  and Delegados directly ticks `members_manage` and `attendance` on Presidente.
- Nobody grants a permission they lack: it follows from the subset rule, and is tested
  on its own.

**Invariants**, each a test:

1. **There is always exactly one titular**, and the titular always holds every
   permission. The flag is not an appointment: no end date, no role edit, no cambio de
   mando touches it. Only section 6 moves it, in one transaction.
2. **So someone can always manage roles**: the titular. No role edit, archive or
   appointment end can leave a gym where nobody holds `team_manage`, because the titular
   always does.
3. **The titular cannot lock themselves out**: their own row refuses an end date,
   their flag refuses a clear, and leaving the team or being forgotten is refused while
   they hold it ("Traspasa la cuenta primero").
4. **No silent widening**: a role edit that adds a permission to people already holding
   it is shown before saving ("3 personas podrán ver gastos") and audited.

**Terms that run out.** Sixty days before an appointment's `ends_on`, and again on the
day, the nightly job tells the titular and the `team_manage` holders, once each, with
"Iniciar cambio de mando". An appointment already followed by another of the same
person to the same role is a renewal and is silent.

### 5. The cambio de mando (question 9)

A board's term ends, by election, resignation or a handover between owners. Doing it as
twenty edits leaves days where the old tesorero has gone and the new one has not
arrived, or where both are recording payments. So it is one object, staged, accepted
and then effective at one moment.

**What it holds.** A `handover` (gym, effective day *D*, started by, reason, status) and
its **seats**: for each role it changes, who leaves (the current appointment it ends)
and who arrives (a person, already in the gym or invited by email, and an optional end
of their term). A seat may only end (a role left vacant) or only start (a new role).
Seats not in it are untouched: the coaches carry on.

**Its life:**

```
borrador ──propose──▶ propuesto ──(titular confirms, if needed)──▶ confirmado ──D──▶ vigente
   │                     │                                            │
   └──cancel─────────────┴──cancel──▶ cancelado ◀──cancel (before D)──┘

each seat:  pendiente ──accepted (and handover confirmed)──▶ escrito
                      └─declined / titular leaves it vacant──▶ cerrado
```

The dates do the switching; nothing waits for a job. A seat is **escrito** (written)
the moment it is ready: its incoming person has accepted and the handover needs no
further confirmation. In that one transaction, under the per-person locks, the
outgoing appointment gets `ends_on = E` and the incoming appointment is inserted with
`starts_on = E` (and the incoming `staff` row with it), where **E = max(D, today)** in
the gym's timezone. Because access is computed from the dates (section 3), a seat
written before *D* flips at the first second of *D* with no job involved, and a seat
written on or after *D* flips at once. There is no instant with both holders and no
instant with neither, which is section 7's concurrency test.

1. **Borrador.** Started by the titular or a `team_manage` holder (often the outgoing
   presidente). They fill the seats and *D*. Nothing changes yet.
2. **Propuesto.** Each incoming person gets an email and, signed in as themselves, sees
   their seat, its permissions and *D*, and accepts or declines. Acceptance is theirs
   alone: the starter cannot accept for them. Someone invited new accepts by signing in
   from the invite.
3. **The titular's confirmation** is needed when the starter is not the titular and
   any seat's role is not a proper subset of the starter's permissions, or any seat
   ends someone whose permissions are not a proper subset of the starter's (section
   4's rule, seat by seat). With the Club federado preset, a Presidente's handover
   naming a Secretario, Tesorero or Delegado therefore waits for the titular. The
   titular sees the whole handover, seat by seat.
4. **Confirmado** once the titular has confirmed (or no confirmation was needed). At
   that moment every seat already accepted is written; each seat accepted later is
   written when it is accepted. Either way with E = max(D, today), so a handover
   confirmed after *D* takes effect at once, seat by seat. In the same transaction,
   every seat not yet written whose outgoing appointment ends on or before *D* has that
   end cleared (open), written as `appointment_extended`, so the outgoing holder
   carries on ("prorrogado") with no job and no lapse; when the seat is written later,
   the open end becomes E as for any seat.
5. **Vigente** from *D*, once every seat is written or closed. The acta de traspaso is
   snapshotted then (when the last seat is written, or at *D* if all were written
   earlier). The nightly job only does the housekeeping of section 3: it removes the
   `staff` rows of people whose last appointment has ended and ends their sessions
   (0005).
6. **Cancelling** a confirmed handover is possible only before *D*, in one
   transaction: it deletes the written seats' future incoming appointments (they never
   started, so there is nothing for the history to show); it **ends today** (never
   deletes) the early-access read-only appointments, which have already granted access,
   each written as `appointment_ended` with the `handover_id`; and it gives every
   outgoing appointment back the end it had before the handover, the confirmation's
   extensions included, each written as `appointment_corrected` with before and after.
   Then `handover_cancelled`. From *D* on, a mistake is corrected by another cambio de
   mando.

**No gap, no overlap, unless the gym chooses.**

- **Nobody can manage the gym** never happens: the titular holds everything throughout.
- **Both boards with money** never happens by default: outgoing access ends at the
  moment incoming access starts.
- **The gym may choose an acompañamiento**: the outgoing seats keep *read-only* access
  (`money_read`, `expenses_read`, nothing else) for up to 30 days after *D*, to answer
  the new board's questions. Never a write permission, and stated in the handover as
  agreed. It is stored as a second appointment, written with the seat, from *D* to its
  end, to the gym's **system role** "Acompañamiento (solo lectura)" (`gym_title.system
  = 'read_only_handover'`, permissions `money_read` and `expenses_read`, not public).
  Rakin creates that role on first use and keeps it: it is hidden from Cargos and every
  picker, no one can edit, archive or appoint to it by hand, and only a cambio de mando
  writes appointments to it. Its appointments keep the seat in `title_name`
  ("Tesorero (acompañamiento)"), so the history says what it was.
- **The incoming board may see before *D***: the same role, the other way round, from
  the moment the seat is written to *D*, if the gym ticks it. Off by default.

**When a side does not answer.**

- **An incoming person never accepts.** A seat that is not written changes nothing
  at *D*: its outgoing appointment already has an open end, either because it had one
  or because the confirmation extended it (step 4), so the seat is never left empty by
  a missing acceptance and nothing has to run at *D*. Equipo shows the seat as
  "prorrogado", in orange, until the person accepts (and the seat is written, flipping
  at once) or the starter names someone else. Written seats go ahead on *D*
  regardless.
- **The outgoing side has gone** (resigned and unreachable, refuses to start it). The
  titular starts the cambio de mando directly; nobody outgoing has to do anything,
  since the outgoing side never confirms. If it is the outgoing presidente who should
  have started it, the titular states why in the reason.
- **Someone must stop now** (a tesorero removed for cause). The titular may end any
  appointment today with a reason, outside a handover. That is the override: always the
  titular, always with a reason, always audited, and the person is told by email.
- **A stalled handover**: the titular may force a seat through without its incoming
  acceptance only to leave it *vacant*, never to put a person in a seat they did not
  accept.

**What the outgoing board keeps.** From *D* (or the acompañamiento's end) no staff
access, unless they hold another role. They keep, in their own Mi cuenta, **Mi gestión**:
their appointments, and the acta de traspaso's figures only (below), as of *D*. No
member's name, RUT, contact or balance. A member who trains keeps their own student
page as any member does.

**What the incoming board gets on day one: the acta de traspaso.** Generated when the
handover takes effect, stored as a snapshot (`handover.packet`, JSON) so both sides
read the same thing later, and shown in Equipo › Cambios de mando. Each part shows only
to whoever holds the permission it needs:

| Part | What | Needs |
|---|---|---|
| Equipo | Who holds each role from *D*, who left, vacant seats | on the team |
| Alumnos | Active, frozen, left during the term (counts) | on the team |
| Ingresos | Cobrado per month of the outgoing term; Esperado this month | `money_read` |
| Lo que se debe | Total owed, students overdue (count and list), proofs waiting | `money_read` |
| Cobros extra | Open ones: billed, collected, pending | `money_read` |
| Correcciones | The last 90 days of corrections (#277) | `money_read` |
| Gastos | Per month and category during the term; the gastos fijos | `expenses_read` |

The outgoing board's Mi gestión holds the same counts and totals and none of the lists.
A part whose feature is not built yet (Gastos before ticket #316) is simply absent.

**Audit.** Every step writes an `audit_event`: `handover_started`, `handover_proposed`,
`handover_seat_accepted`, `handover_seat_declined`, `handover_confirmed`,
`handover_effective`, `handover_cancelled`, `handover_overridden` (with the reason),
and the appointments' own `appointment_started`, `appointment_ended`,
`appointment_extended` and `appointment_corrected`, each with the `handover_id`. With `title_created` and
`title_changed`, the log answers "who could see the money on 3 March, and who decided
it".

### 6. Transferring the account (the titular)

The most sensitive change: the titular holds everything, cannot be overridden, and is
who Rakin deals with about the gym's subscription. So it has its own flow, never part
of a cambio de mando:

1. **The titular starts it** in Equipo › Cuenta: the incoming person (on the team,
   with an email that signs in to this gym), and what the outgoing titular keeps
   afterwards: nothing, or chosen roles. A reason.
2. **The incoming person accepts**, signed in, and confirms with a fresh sign-in code
   sent to their email, so a session left open on a shared computer is not enough.
3. **Seven days' wait.** Both are emailed at once and each day the change is pending;
   either may cancel. The outgoing titular's email carries a link to cancel without
   signing in, valid until the change takes effect.
4. **It takes effect in one transaction**: the old flag is cleared, then the new one
   set (the partial unique index never sees two, and the deferred trigger never sees
   none at commit), the outgoing titular's chosen roles become
   appointments from that day, and `account_holder_transferred` is written with both
   people and the reason. The subscription's billing contact moves with it.

**If the titular is unreachable** (has died, left the club and does not answer, refuses
a decision the club took), nobody in the gym can move the flag, by design: an in-app
override would be a way to take a gym. It goes to Rakin's support, with the club's own
record of the decision (its acta naming the new titular) and the requester signed in to
the gym; support emails the titular's address with seven days to object, then moves the
flag with a reason naming the request, audited as `account_holder_transferred` with
`by_support`. This doc designs the record and the step; the support procedure itself is
the ops runbook's.

### 7. Enforcement (question 8)

**API.** `app.roles` becomes `app.permissions`:

```python
class Permission(StrEnum):
    MONEY_READ = "money_read"; MONEY_WRITE = "money_write"
    EXPENSES_READ = "expenses_read"; EXPENSES_WRITE = "expenses_write"
    MEMBERS_MANAGE = "members_manage"; MEMBERS_ADD = "members_add"
    ATTENDANCE = "attendance"; GYM_SETUP = "gym_setup"; TEAM_MANAGE = "team_manage"

async def permissions_in_gym(session, tenant) -> frozenset[Permission] | None
    # None: not on the team. The titular: every permission.

def requires(*needed: Permission)   # any staff when empty; else holds all of `needed`
```

One query per request, as `role_in_gym` is today: the `staff` row, the titular flag
and the union of current appointments' permissions. The session aliases keep their
names and move underneath, so #308 changes no endpoint:

| Today | Becomes |
|---|---|
| `StaffSession` | `requires()`: on the team |
| `LedgerSession` | `requires(MONEY_READ)` for GETs, `requires(MONEY_WRITE)` for writes (#310 splits them; #308 maps it to `MONEY_WRITE`, which every admin holds) |
| `AdminSession` | `requires(GYM_SETUP)` |
| `OwnerSession` | the titular flag (`AccountHolderSession`) |
| `SeesMoney` | `MONEY_READ in permissions` |

**The database.** One function, used by every policy instead of a role list:

```sql
CREATE FUNCTION app_can(p text) RETURNS boolean STABLE LANGUAGE sql AS $$
  SELECT EXISTS (
    SELECT FROM staff s
    WHERE s.gym_id = current_gym() AND s.person_id = current_person()
      AND (s.account_holder OR EXISTS (
        SELECT FROM staff_title st JOIN gym_title t ON t.id = st.title_id
        WHERE st.gym_id = s.gym_id AND st.person_id = s.person_id
          AND p = ANY (t.permissions) AND <current in the gym's timezone>)))
$$;
```

It runs as the invoker, under the same RLS as the subselects it replaces (`staff` and
the new tables are themselves gym-isolated). Its argument is a constant, so a policy
calls it as `(SELECT app_can('money_read'))`: Postgres then evaluates it once per
query as an initplan rather than once per row. #309 checks the plan on `ledger_entry`,
the largest table, with `EXPLAIN` in a test. Each role-keyed policy is rewritten, and
split into read and write where today one `ALL` policy serves both:

| Policy (migration) | Read | Write |
|---|---|---|
| `ledger_entry_by_role` (0006) | `app_can('money_read')` | `app_can('money_write')` |
| `extra_charge`, `extra_line` (0037) | `money_read` | `money_write` |
| `charge_group`, `charge_group_member` (0037) | gym (as now) | `money_write` |
| `session_delete_by_role` (0033) | — | `gym_setup` |
| `audit_event_read` (0044) | `money_read`, or `expenses_read` for expense actions, or `team_manage` for team and handover actions | — |
| correction insert (0048) | — | `money_write` |
| `gym_title`, `staff_title`, `handover` (new) | on the team | `team_manage` (the proper-subset rule is the API's); a system role only through a cambio de mando |
| expense tables (new, part two) | `expenses_read` | `expenses_write` |

The students' own policies (their entries, their dependents', their proof claims)
are about the person acting, not a role, and stay as they are. The titular flag is
written only by a definer function, `transfer_account_holder`, which `rakin_app` may
execute and which checks the accepted, waited-out transfer itself.

**The migration path**, so no step changes what anyone can do:

1. Tables, the titular flag, the Academia roles per gym from today's roles; the API
   reads permissions; `staff.role` is still written by the staff API alongside the
   appointments, so the old policies still hold (#308).
2. `app_can` and the policies rewritten (#309). From here the database no longer
   reads `staff.role`.
3. Endpoints by permission, then Equipo, the cambio de mando and the account
   transfer (#310, #311, #320, #321).
4. `staff.role` dropped once nothing reads it, `Role` removed (#313).

**Tests that each permission holds at the database.**

- `test_permissions_rls.py`, parametrised over the table above: for each protected
  table and each of read and write, a person holding only that permission succeeds, a
  person holding every permission but that one gets no rows or a policy error, and a
  person whose appointment ended yesterday gets nothing. Run as `rakin_app` against the
  real database, as the ledger's role tests do today.
- A drift test: no row of `pg_policies` mentions `role` in its `qual` or `with_check`
  (after #309), and every table with a by-permission policy is in the parametrised
  list, so a new money table cannot ship without its case.
- A literal test: each `Permission` is used by name, no permission set is defined as
  another, and no code compares a role's name (`gym_title.name`) in a condition.
- #308's equivalence test: for owner, admin and coach fixtures, every route in the
  app answers the same status before and after (`app.routes`, parametrised).
- The invariants of section 4, and a cambio de mando at *D* with concurrent requests:
  no instant where a query sees both boards with `money_write`, or neither.

### 8. The UI (question 10)

**Ajustes › Equipo**, in the Ajustes layout (#241): a head with "Invitar", then the
cards **Personas**, **Cargos**, **Cambios de mando** and **Historial**, and, for the
titular only, **Cuenta**.

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
│ │ (Titular de la cuenta)   │ │
│ ├──────────────────────────┤ │
│ │ Pablo Soto            ›  │ │
│ │ (Presidente) (Coach)     │ │
│ │ hasta mar 2026           │ │
│ ├──────────────────────────┤ │
│ │ Marta Díaz            ›  │ │
│ │ (Tesorera) prorrogado    │ │
│ └──────────────────────────┘ │
├──────────────────────────────┤
│ Cambios de mando             │
│ Directiva 2026 · 1 mar       │
│ 3 de 4 aceptados          ›  │
│ [Iniciar cambio de mando]    │
├──────────────────────────────┤
│ Cargos                       │
│ Presidente  Ver ingresos,  › │
│             Ver gastos, Eq…  │
│ Tesorero    Ingresos y     › │
│             gastos           │
│ [Nuevo cargo]                │
│ [Agregar plantilla]          │
├──────────────────────────────┤
│ Historial                  ▾ │
└──────────────────────────────┘
```

A person opens in place: their appointments, each a role, a "Desde" and an optional
"Hasta", "Terminar cargo" (after a confirm) and "Agregar cargo"; below, read-only,
"Puede:" and the union of permissions in words. Shown only to whoever may change them
(section 4); others see the row without the chevron.

At 1280, Personas is a table and a role opens beside it:

```
┌ Sidebar ┬──────────────────────────────────────────────────────────────────┐
│         │ Equipo                                          [ Invitar ]      │
│         │ Quién está en el equipo y qué puede hacer.                        │
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Personas                                                          │
│         │ Nombre        Cargos                     Período          Puede   │
│         │ Ana Rojas     Titular de la cuenta       —                Todo    │
│         │ Pablo Soto    Presidente · Coach         mar 25 – mar 26  5 de 9 ›│
│         │ Marta Díaz    Tesorera (prorrogado)      mar 25 – …       4 de 9 ›│
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Cambios de mando                        [Iniciar cambio de mando] │
│         │ Directiva 2026   desde 1 mar 2026   3 de 4 aceptados   Propuesto ›│
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Cargos                                                            │
│         │ Cargo       Ingresos  Pagos  Gastos  Reg.gastos  Alumnos  Asist… │
│         │ Presidente     ✓        –      ✓        –          –        –    │
│         │ Tesorero       ✓        ✓      ✓        ✓          –        –    │
│         │ [Nuevo cargo]   [Agregar plantilla]                               │
│         ├──────────────────────────────────────────────────────────────────┤
│         │ Historial                                                       ▾ │
└─────────┴──────────────────────────────────────────────────────────────────┘
```

A role opens to its name, "Visible para los alumnos", and one checkbox per permission
with its line of help ("Ver gastos: incluye sueldos y honorarios"). A checkbox the
editor may not grant is disabled with the reason. Saving a change that widens what
current holders can do says so first.

**Iniciar cambio de mando**, one form: a name ("Directiva 2026"), *D*, the reason; then
one row per seat, pre-filled with every role that has a current holder: "Sale" (the
current holder, or "nadie"), "Entra" (a person, or "Invitar…"), "Hasta" (optional).
Below, the two choices, "Acompañamiento de la directiva saliente (solo lectura, hasta
30 días)" and "La directiva entrante ve antes del cambio (solo lectura)", both off.
"Proponer" sends the emails. The handover then opens to its seats with each one's
state (aceptado, pendiente, rechazado) and, for the titular, "Confirmar". On *D* it
opens to the acta de traspaso.

**The incoming person's view**: an email and a page, "Te proponen como Tesorera desde
el 1 de marzo", the permissions in words, "Aceptar" or "Rechazar".

**Cuenta** (titular only): "Traspasar la cuenta", the flow of section 6, and its
pending state with the days left and "Cancelar".

**Invitar** asks what it asks today (RUT, name, email, phone) and, instead of the role
radio, one or more roles (checkboxes, at least one), "Desde" (today) and an optional
"Hasta". The invite email names the roles ("te invitó como Tesorera").

**What a member sees.** On the student page, a card "Directiva y equipo" lists the
current holders of public roles: name, roles, and the contact they chose to share
(`staff_title.public_contact`: email, phone or nothing; nothing by default). Only
current appointments; a public role with nobody in it says "sin designar"; never
permissions; never ended ones. A gym with no public roles shows no card.

### 9. Privacy

- A public role shows the officer's name and role only. A phone or email shows only if
  the officer turns it on for that appointment, in their own Mi cuenta or when
  accepting it; nobody can publish someone else's phone.
- The board's answer to members is its own schema with a fixed field set, and a test
  searches its bytes for every officer's email, RUT and id.
- The outgoing board's Mi gestión and the acta's figures carry no member's name, RUT,
  contact or balance; only the incoming board's money parts list who owes.
- The Historial and Cambios de mando cards are for `team_manage` holders.
- The privacy notice gains one sentence: the gym may show its officers' names and roles
  to its members.

## Part two: expenses

### 10. What an expense is (question 1)

| Field | Required | Notes |
|---|---|---|
| Fecha (`spent_on`) | yes | The day it was paid; it decides the month |
| Monto (`amount_clp`) | yes | CLP, integer, > 0 |
| Categoría | yes | The gym's list (below) |
| Pagado a (`payee`) | no | Free text: "Inmobiliaria X", "Enel", the coach's name |
| Método | no | Transferencia, efectivo, tarjeta, otro (the ledger's methods plus tarjeta) |
| Nota | no | |
| Comprobante | no | A photo or PDF, through the blob store, under `receipts/<gym_id>/` |
| Gasto fijo | no | The template it came from (section 11) |
| Cobro extra | no | The cobro that recovers it (section 14) |

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

### 11. Recurring costs (question 2)

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

### 12. Where it lives (question 3)

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
  Expense rows must not reach an Administrador without `expenses_read`, so #309's
  rewrite splits the policy by action, as section 7's table says.
- **Forgetting a person** does not touch expenses: they name a payee in text, not a
  person. An expense's `created_by` is kept (the gym's record of who typed it), as
  `ledger_entry.recorded_by` is.

### 13. The view (question 4)

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

### 14. Money that is not the gym's (question 5)

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

- Budgets, forecasts, bank reconciliation, invoices (facturas) and tax (IVA). Rakin
  records what was paid; the accountant does the rest.
- Per-category privacy (hiding Sueldos y honorarios from a Tesorero). `expenses_read`
  is all or nothing; if a club asks, a category can gain "solo el titular" later.
- A limit on how long a term may last. Some clubs' statutes cap a board's term; Rakin
  does not know which, so an end date is optional and never capped. A gym that wants
  the reminder sets the end.
- A register of every past board since the club's founding, for people who are no
  longer in the gym. History starts with the appointments Rakin records.
- Officers across gyms (one federation, several clubs).
- Rakin's own subscription billing; section 6 only says its contact moves with the
  titular.

## Build tickets

In order. Each is one PR. The permissions come first; the cambio de mando and the
account transfer need Equipo's roles; expenses need `expenses_read` and
`expenses_write` to exist, and the tables of part two are created with `app_can`
policies from the start.

1. **#308 Permisos detrás de los roles.** `gym_title`, `staff_title` (with
   `title_name` and half-open terms), `staff.account_holder`; the migration that turns
   each gym's roles into the Academia preset's appointments; `app.permissions`
   (`Permission`, `permissions_in_gym`, `requires`); the session aliases redefined over
   permissions; `GET /api/me/role` adds `permissions`; the frontend's role tests read
   them; the staff API keeps writing `staff.role` in step. The equivalence and literal
   tests. No visible change.
2. **#309 RLS por permiso.** `app_can`; every role-keyed policy rewritten and split read
   and write (section 7's table), `audit_event_read` split by action; the parametrised
   RLS test and the drift test.
3. **#310 Endpoints por permiso.** Walk the `StaffSession`, `LedgerSession` and
   `role_in_gym` call sites: GETs to `money_read`, writes to `money_write`, members to
   `members_manage` or `members_add`, classes to `attendance`; the staff API's
   proper-subset rule with `team_manage`. Tests per area.
4. **#311 Equipo: roles defined by the gym.** Cargos (create, permissions, public,
   archive, presets), first-run preset choice, Personas with appointments and
   corrections, Historial, Invitar with roles, the `staff` row written with the first
   appointment, the invariants of section 4, and their audit rows.
5. **#320 Cambio de mando.** `handover` and its seats; propose, accept, confirm; each
   seat written with future-dated ends and starts the moment it is ready, so the dates
   flip access at *D* with no job; prorrogado seats; cancel before *D*; the
   acompañamiento's system role; the titular's overrides; term alerts; the audit rows;
   the concurrency test across *D*.
6. **#321 Traspasar la cuenta.** Equipo › Cuenta; acceptance with a fresh sign-in code;
   seven days cancellable; `transfer_account_holder`; the support path.
7. **#312 Directiva en la página del alumno.** Public roles, `public_contact` chosen by
   the officer, the card on the student page with its own schema, the privacy notice's
   sentence.
8. **#313 Retirar `staff.role`.** Drop the column and `Role` once nothing reads them;
   the drift test extended to the code.
9. **#314 Gastos.** `expense`, `expense_category` with the defaults; record, edit with
   audit, void with a reason; the receipt upload; the Gastos list by month; the test
   that billing is untouched.
10. **#315 Gastos fijos.** `expense_recurring`, `expense_skip`; the "por registrar"
    card; one-tap fixed, pre-filled estimated, "Registrar los fijos", "No este mes".
11. **#316 Finanzas: el mes y el año.** The page, Entradas from `v_monthly_income`,
    Salidas by category, Resultado, the year view; Salidas only without `money_read`.
12. **#317 Exportación con gastos.** The Gastos and Resumen sheets, the CSV download,
    gated on `expenses_read`.
13. **#318 Gastos recuperados con cobros extra.** `expense.extra_charge_id`, the picker
    in the form, the cobro's "Gastos asociados" line, Finanzas' recovered line.
14. **#322 Acta de traspaso.** The snapshot written when a cambio de mando takes
    effect, its parts by permission, and the outgoing officers' Mi gestión.

Tickets 9 onward need only #308 and #309, so expenses can go in parallel with #310 to
#313; #322 needs #320 and #316.
