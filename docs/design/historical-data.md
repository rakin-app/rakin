# Historical data: bringing a gym's past in (#292)

Spike, November 2026. No product code: this doc decides which of a gym's history Rakin
takes in, where it is stored so billing never reads it, how an owner enters it by hand
or from a spreadsheet, and how the pilot gym's real history is loaded. The build tickets
at the end carry it out, in order.

## For the owner, in short

- **Your history goes in beside billing, never into it.** What a student paid before
  Rakin, the day they started and the belts they earned are kept as **historial**:
  shown on the ficha, never charged, never reminded, never counted in Pagos. The Libro
  stays what Rakin billed and collected.
- **What comes in, most useful first:** when each student started ("Alumno desde"), the
  students who already left (when, and why), what each one paid month by month, their
  belts with dates, and how many classes they had before Rakin, as one number.
- **Two ways, the same result.** By hand on the ficha ("Agregar historial": a year of
  payments in one form, an earlier start, a past belt), and "Agregar exalumno" in
  Alumnos. Or from a spreadsheet: download Rakin's template (three tabs: Alumnos, Pagos,
  Grados), fill it, and upload it in Alumnos › Importar, which already brings your
  students in. The dry run shows every row before anything is saved, and running it
  again adds nothing twice.
- **Nothing you have is overwritten.** The import fills what is empty and says what it
  left alone, as it does today.
- **Everything says where it came from**: typed by whom and when, or imported from which
  file. An import can be undone as a whole.
- **Former students stay private.** Only you and your admins see why someone left and
  what they paid; Rakin never writes to a former student, and you can still delete one
  completely.
- **Payments for months already on their Rakin plan are not historial.** Those go
  through "Pagado hasta" (#286), because billing has to know about them.

## What exists today

- **Import** (`app.api.member_import`, `app.member_import`): `POST /api/import/sheet`
  reads the first worksheet of a CSV or XLSX (up to 2,000 rows) and suggests a mapping
  by header; `POST /api/import/members` reads the rows, then writes each in a savepoint,
  as a dry run (rolled back) by default. A person is found by RUT, else email, else by
  name among this gym's people (told apart by birth date, then phone); a dependent by
  guardian and name. It never overwrites (`ignored`) and only fills a RUT or email for
  someone who had neither (`_key`). A row with a plan gets a membership as of its due
  date (`domain.imported`). One import at a time per gym (advisory lock, #203).
- **People** (`gym_person`): name, contacts, RUT, birth date, `created_at`, and
  `left_on` (0032), set by Dar de baja (`POST /api/people/{id}/leave`, within the last
  five years), which ends every membership. There is **no reason** for leaving and **no
  start date** of the person's own: the ficha's "Alumno desde" is the earliest
  membership's `started_on`, else the day the record was created
  (`MemberDetail.tsx`).
- **Billing** reads memberships and their periods only. `_first_unbilled`
  (`app.domain.billing`) bills a recurring membership from its `current_period_end`, or
  from `started_on` when it has none. That is the #271 lesson in one line: **a
  membership started in the past bills every month since**, unless it says it is paid
  through. The import is safe because it always sets `current_period_end` from the due
  date.
- **Ledger** (`ledger_entry`): append-only (0002), every entry on a membership; income
  is dated by `validated_at` (`v_monthly_income`, the accountant export #40). A payment
  written today for 2023 would land in today's "Cobrado".
- **Corrections** (`docs/design/billing-corrections.md`): #277 makes `audit_event` the
  record of every fix, with a `person_id` and an app-role insert policy; #286 "Pagado
  hasta" writes real payments on real periods up to a date. Both still open.
- **Grades** (`grade_event`, 0018): append-only, `awarded_on` may be in the past already,
  but a grade **hangs off a membership**, so someone without one (a former student whose
  plans were never in Rakin) can hold none: `award_grade` answers `no_membership`.
- **Attendance** (`attendance`, 0023): one row per session and membership, so nothing
  before the gym's first class in Rakin. The ficha shows a total, the last 30 days and
  the classes since the current rank (`person_attendance`).
- **Forgetting** (`forget_gym_person`, 0032 and 0044): deletes a person's records here,
  refused while they still hold money (`payment`, `pending`, `owes`), are staff, or
  answer for a dependent.

## 1. What history is worth having

In order of value to an owner, from what owners ask and what the app can use:

| # | History | Why it matters | Stored as |
|---|---------|---------------|-----------|
| H1 | **Alumno desde**, the day they first started | The ficha's first line; loyalty ("8 años con nosotros"); it is in every gym's sheet | `gym_person.member_since` |
| H2 | **Former students**, the day they left and why | The full roster, win-back, and why people leave (price, moved, injury) | `gym_person.left_on` (exists) and `left_reason` |
| H3 | **Past payments** by month: date, amount, method, the month it paid | "¿Me pagó marzo de 2024?", a former student's record, years of income at a glance | `history_payment` (new) |
| H4 | **Belts and grades** with dates | The current rank must be the real one from day one; time at each belt | `grade_event` (exists), by person |
| H5 | **Classes before Rakin**, one number | The total on the ficha, eligibility talk ("lleva 300 clases") | `gym_person.prior_classes` |

**Out of scope, and why:**

- **Attendance session by session.** Nobody has it in a usable form (paper lists, a
  WhatsApp group), and a past session would need a class, a coach and a time that never
  existed in Rakin. One number per person (H5) is what is asked for.
- **Past plans as memberships, with periods.** A past membership would be one more thing
  billing could start reading (the #271 lesson), and the only use of it is "which plan
  were they on": the payment row's free-text plan name answers that (H3).
- **Old debts.** Money a student still owes at go-live is not history: it is owed now,
  so it belongs in the ledger. A one-off charge (Cobros, #195) for that person records
  it today, and the doc on the pilot says so.
- **Past freezes, receipts, refunds, proofs.** No owner has asked; a refund before Rakin
  is a payment row with a note. No receipt is ever emailed for history.
- **Past hours per tag** (#243's "tiempo de entrenamiento"). Needs session-level data.
- **History of guardians, contacts or custom fields.** The current value is the useful
  one.

## 2. How it is stored without touching billing

**Recommendation: history lives in its own rows, which no billing code, view, job or
export reads.** Not ledger entries, and never a membership started in the past.

### Why a past payment is not a ledger entry

- **The ledger dates income by when it was recorded.** `v_monthly_income`, the book's
  "Cobrado" and the accountant export (#40) file a payment under its `validated_at`.
  Five years of payments imported today would all be November 2026's income. Back-dating
  `validated_at` would instead rewrite months the gym's accountant closed on the gym's
  own books, before Rakin.
- **A ledger entry needs a membership and a period.** A 2022 payment would need a 2022
  membership and a 2022 period, the exact rows the nightly job bills from, lapses on
  and emails about. Every guard would have to learn to skip them, and one that forgot
  would charge or warn a student for a month they paid four years ago.
- **"Esperado", "Vencido", the balance and the receipts all sum entries.** A separate
  table cannot leak into any of them; no view mentions it.
- **The accountant already has those years.** The gym's books before Rakin are
  wherever they were. Repeating them in Rakin's export would count them twice.

### Why "Alumno desde" is not a membership's start

A membership's `started_on` is the day billing may start from (`_first_unbilled`). An
earlier date there is exactly #271. The person's own start (`member_since`) is a fact
about them, read by the ficha and nothing else. A plan starts the day it starts billing,
as now; "Alumno desde" shows the earliest of `member_since` and the first membership's
start, so a gym that types no history sees what it sees today.

### The new columns and table

On `gym_person`:

- `member_since date`: the day they first trained here. Not after today, at most 60
  years back (a typo guard, not a rule: a founder's first students).
- `left_reason text` (≤ 200 characters): why they left, written with Dar de baja or for
  a former student. Owner and admin only (below): it is personal, and someone may still write
  health data in it, which the hint asks them not to (#384).
- `prior_classes integer ≥ 0`: classes before Rakin, added to the ficha's total.

`history_payment`, one row per payment the gym received before Rakin:

| Column | |
|---|---|
| `id`, `gym_id`, `person_id` | `(gym_id, person_id)` references `gym_person` |
| `paid_on date` | the day it was paid; not after today |
| `amount_clp bigint > 0` | |
| `method text` | `cash`, `transfer`, `other`, or null: old records often do not say |
| `covers_month date` | the month it paid for, as its first day; null when unknown |
| `plan_name text` | the plan as the gym called it then ("Mensual 3x semana"); free text, no link to `plan` |
| `note text` | ≤ 500 |
| `source text` | `manual` or `import` |
| `import_id uuid` | the import's audit row (§6), for `import` |
| `created_by`, `created_at` | who typed or imported it, and when |

**The boundary with billing**, checked by the API on every write, by hand or imported:
a history payment's `covers_month` (or `paid_on`, when it has none) must be **before the
start of the person's first membership in Rakin**, if they have one. A month on or after
it is part of their Rakin plan: the form says so and points at "Pagado hasta" (#286),
which writes it in the ledger where billing sees it; the import refuses the row
(`covers_plan`). Someone with no membership (a former student) has no boundary but
today.

RLS as every tenant table, and read and written under `LEDGER_ACCESS` (0006): owner and
admin only, like the Libro. The app role may `SELECT`, `INSERT` and `DELETE`: unlike the
ledger, history is not what Rakin collected, so a typo is removed and typed again, with
an audit row that keeps what was removed (§6).

### Grades by person

A belt earned before Rakin is a real grade: it should be the current rank, draw the belt
and start "desde". So it stays a `grade_event`, which already takes a past
`awarded_on`. What changes is that a grade **belongs to the person**, not to a
membership: `grade_event.person_id` (backfilled from the membership, then `NOT NULL`),
`membership_id` becomes nullable, and every read moves to `person_id` (`app.api.grades`,
`_promoted_on`, the people list's current rank, `forget_gym_person`). A `source` column
(`app`, `manual`, `import`) says how it came in. A history grade writes **no**
`promoted` plan event: nobody should be congratulated for a belt from 2021. If it is the
latest by `awarded_on` it becomes the current rank, as any grade does.

### What each reader does with history

| Reader | History |
|---|---|
| Nightly billing, lapse, overdue and statement jobs | never read it |
| `v_balance`, `v_overdue`, `v_monthly_income`, the book's KPIs ("Esperado", "Cobrado", "Vencido") | never read it |
| The accountant export (#40) | leaves it out; its footnote line says "No incluye el historial anterior a Rakin" |
| Hoy, Pagos, the inactive list | never read it |
| The ficha | "Alumno desde", the leaving banner with its reason, a **Historial** card, the belt, the class total |
| The student's own page (`/me`) | "Alumno desde" and their belt; not the history payments (no receipt was ever issued for them, and the gym may have typed them roughly) |
| Deleting a person (#256) | deletes it all, and counts it in the `person_deleted` row |

A test pins the first three rows: a gym with history and without it bills, lapses,
reports and exports the same.

## 3. The spreadsheet path

**Recommendation: one importer, one workbook, three tabs.** The importer gains two row
kinds beside the people it already reads; it is not a second importer.

- **Alumnos** is today's sheet with four more columns. One row per person, as now.
- **Pagos**: one row per payment. A gym that keeps a grid (one row per student, a column
  per month) copies it into this shape; the template's instructions tab says how, and
  most gyms' payment notebooks are already a list.
- **Grados**: one row per belt or stripe earned.

A CSV is one tab, so the upload asks which (Alumnos, by default, as today). An XLSX is
read by tab name: `read_sheet` returns every worksheet it knows (Alumnos, Pagos,
Grados, matched by folded name, else the first as Alumnos), and the screen shows a step
per tab found.

### One dry run, in order

`POST /api/import/members` takes the tabs together, each with its mapping, and writes
them in one transaction in order: **Alumnos, then Pagos, then Grados**, every row in its
own savepoint as now. So a Pagos row finds a student the Alumnos tab adds, in the dry run
too, and the dry run reports every tab's rows before anything is kept. The advisory lock,
the dry-run rollback and the report shape stay; the report gains a section per tab.

A Pagos or Grados row **never creates a person**. It finds them as the Alumnos tab does
(`Writer._in_gym`, `_named`): by RUT, else email, else name (told apart by birth date
when the row gives one). Nobody found is refused (`unknown_person`), and so is a name two
people share (`ambiguous_name`, as now): the fix is a RUT in the row.

### Running it again adds nothing twice

- **Alumnos**: as today. The history columns fill a field that is **empty** and are
  `ignored` when it holds something else. This is the one change to "never overwrites":
  the fields are new, so every person the pilot already imported has them empty, and
  the second run is how they get filled.
- **Pagos**: a row is the payment already here when the person, `paid_on`, `amount_clp`
  and `covers_month` match an existing history payment (`existing`, written nothing).
  Two rows in one sheet with the same person, `paid_on`, `amount_clp` and
  `covers_month`: the second is `repeated`. So two real, equal payments on one day for
  one month collapse into one on import; the sheet tells them apart with a different
  "Mes que paga", else the second is typed by hand. There is no unique index: by hand,
  two equal payments are allowed (the form warns).
- **Grados**: the grade already here when person, rank, sub-rank and `awarded_on` match.

### New checks

| Code | Tab | When |
|---|---|---|
| `unknown_person` | Pagos, Grados | nobody in the gym or on the Alumnos tab is the row |
| `covers_plan` | Pagos | the month is on or after their first Rakin plan's start (§2) |
| `invalid_amount` | Pagos | not a whole number of pesos above zero (`$25.000`, `25000` and `25.000` all read as 25000) |
| `unknown_rank` | Grados | no rank of the gym's scheme by that label, and the admin did not choose one |
| `left_before_start` | Alumnos | "Fecha de baja" before "Alumno desde" |
| `has_left` | Alumnos | (exists, unchanged) a row with a plan names someone this gym already has dado de baja (`Writer._membership`) |

A row with a "Fecha de baja" and a plan is **not** refused: the person is imported as a
former student and the plan is `ignored`, as any field the import does not apply.

Rank labels are matched as plans are (`PlanFinder`): folded label, else the admin's
choice for that value on the mapping step ("Café" → Marrón). A sub-rank is a label of
the rank's, or a number ("2" = the second stripe).

Dates in history columns may go back 60 years (`HISTORY_WINDOW_YEARS`); billing's own
dates keep their five (`STARTED_ON_WINDOW_YEARS`). The row cap rises for Pagos to 20,000
(five years of a 300-student gym, monthly); Alumnos and Grados keep 2,000.

### Header suggestions

Today "ingreso", "fecha de ingreso", "inicio" and "alta" suggest the plan's start
(`STARTED_ON`). In a gym's sheet those words mean when the student joined, so they move
to **Alumno desde**; the plan's start keeps "inicio del plan". A sheet that relied on
the old suggestion gets the new one, and can map it back on the mapping step.

### The template

"Descargar plantilla" on Importar: `GET /api/import/template.xlsx`, built with
`openpyxl` as the export is, Spanish headers, one example row per tab in grey, an
"Instrucciones" tab, and the gym's own plan names and ranks as the dropdowns of the
Plan and Grado columns. Every header is one the mapping suggests by itself, so a filled
template maps with no changes.

**Alumnos** (bold: new)

| Column | Example | |
|---|---|---|
| Nombre | Martina | required |
| Apellido | Soto Pérez | |
| RUT | 12.345.678-5 | finds them; one of RUT or Correo is best |
| Correo | martina@example.cl | |
| Teléfono | +56 9 1234 5678 | |
| Fecha de nacimiento | 14-03-2010 | |
| Apoderado | Paula Pérez | for a minor |
| RUT apoderado, Correo apoderado, Teléfono apoderado | | |
| Plan | Mensual | the plan now; empty for a former student |
| Próximo vencimiento | 01-12-2026 | needed with a monthly plan |
| Inicio del plan | | packs and trials only |
| **Alumno desde** | 05-03-2019 | |
| **Fecha de baja** | | a former student: the day they left |
| **Motivo de baja** | Se cambió de ciudad | |
| **Clases antes de Rakin** | 320 | |

**Pagos**

| Column | Example | |
|---|---|---|
| RUT | 12.345.678-5 | or Correo, or Nombre: who paid for whom |
| Correo | | |
| Nombre | Martina Soto Pérez | |
| Fecha de pago | 03-04-2024 | required |
| Monto | 25000 | required, pesos |
| Mes que paga | 04-2024 | `MM-AAAA` or a date; optional |
| Método | Transferencia | Efectivo, Transferencia, Otro; optional |
| Plan | Mensual 3x semana | as the gym called it; optional |
| Nota | | |

A payment for a child goes on the child's row (the child's name or RUT), as the Libro
puts it on the child's plan.

**Grados**

| Column | Example | |
|---|---|---|
| RUT, Correo, Nombre | | as in Pagos |
| Grado | Azul | required, a rank of the gym's scheme |
| Sub-grado | 2 | optional: a stripe, by label or number |
| Fecha | 12-08-2023 | required |
| Nota | Graduación de invierno | |

## 4. The in-app path

**Recommendation: one "Historial" card on the ficha, and "Agregar exalumno" in
Alumnos.** History is about one person, so it lives on their ficha; the card is where
it is seen and where more is added.

- **Historial card** (owner and admin), under the Libro: "Alumno desde 5 mar 2019 ·
  320 clases antes de Rakin", then the history payments by year, newest first, each
  year collapsed to its total ("2024 · 11 pagos · $275.000"), opening to one line per
  payment. Its button **"Agregar historial"** opens, in place as every ficha form does,
  three choices:
  - **Pagos anteriores**: the bulk form below.
  - **Fecha de inicio y clases**: "Alumno desde" and "Clases antes de Rakin".
  - **Grado anterior**: the grade form with its date, open to someone with no plan.
- **A line of the card** opens "Eliminar" with a reason, for a typo. Editing is deleting
  and typing again; no edit form.
- **Dar de baja** gains "Motivo" (optional, with chips: Precio, Horario, Se cambió,
  Motivo personal, Otro, which fill the text; none about health, #384), and its date may go back 60 years: #294 changes
  the five-year check in `POST /api/people/{id}/leave` (`member_roll.leave`) and its
  message to `HISTORY_WINDOW_YEARS`.
- **Agregar exalumno**: in Alumnos, "Nuevo alumno" gains a choice at the top: *Entrena
  aquí* (today's form) or *Ya no entrena aquí*. The second asks name, RUT or email,
  phone (optional: nobody will write to them), Alumno desde, Fecha de baja and Motivo,
  and offers "Agregar historial" on the new ficha. No plan, no welcome.

### Twelve months in one form

"Pagos anteriores" asks once and fills a list:

- **Desde** and **hasta** (months), **monto por mes**, **método**, **día de pago**
  (default the 5th) and **plan** (free text).
- It lists one row per month, each editable (amount, day, method) or removable ("ese
  mes no pagó"), with the total. Guardar writes them all in one transaction, or none.
- A month on or after their first Rakin plan is left out of the list, with the line
  "Desde diciembre 2026 está en su plan: usa Pagado hasta", and a link to it (#286).

At 390 (a phone):

```
┌──────────────────────────────────────┐
│ Historial                            │
│ Alumno desde 5 mar 2019              │
│ 320 clases antes de Rakin            │
│ ▸ 2026 · 10 pagos      $250.000      │
│ ▸ 2025 · 12 pagos      $300.000      │
│ ▸ 2024 · 11 pagos      $275.000      │
│ Ver años anteriores (3)              │
│ ┌──────────────────────────────────┐ │
│ │ Agregar pagos anteriores         │ │
│ │ Desde [ ene 2024 ▾]              │ │
│ │ Hasta [ dic 2024 ▾]              │ │
│ │ Monto por mes [ $25.000      ]   │ │
│ │ Método [ Transferencia ▾ ]       │ │
│ │ Día de pago [ 5 ]                │ │
│ │ Plan  [ Mensual 3x semana    ]   │ │
│ │ ─────────────────────────────    │ │
│ │ ene 2024  5 ene  $25.000     ✕   │ │
│ │ feb 2024  5 feb  $25.000     ✕   │ │
│ │ …                                │ │
│ │ dic 2024  5 dic  $25.000     ✕   │ │
│ │ 12 pagos · $300.000              │ │
│ │ [ Cancelar ] [ Guardar 12 pagos ]│ │
│ └──────────────────────────────────┘ │
│ ( Agregar historial )                │
└──────────────────────────────────────┘
```

At 1280 (a desktop): the card in the ficha's main column under the Libro; the form's
fields two to a row, the months in a table beside them.

```
┌───────────────────────────────────────────────────────────┬──────────────────────────┐
│ Historial                                                 │ Mensual · Activo         │
│ Alumno desde 5 mar 2019 · 320 clases antes de Rakin       │ Pagado hasta 30 nov      │
│ ▸ 2026 · 10 pagos · $250.000                              │                          │
│ ▸ 2025 · 12 pagos · $300.000                              │ Azul · 2 grados          │
│ ┌───────────────────────────────────────────────────────┐ │ desde 12 ago 2023        │
│ │ Agregar pagos anteriores                              │ │                          │
│ │ Desde [ene 2024▾] Hasta [dic 2024▾] │ ene 2024 · 5 ene│ │                          │
│ │ Monto [$25.000  ] Método [Transf. ▾]│   $25.000     ✕ │ │                          │
│ │ Día   [5]         Plan [Mensual 3x ]│ …               │ │                          │
│ │                                     │ 12 · $300.000   │ │                          │
│ │                     [ Cancelar ] [ Guardar 12 pagos ] │ │                          │
│ └───────────────────────────────────────────────────────┘ │                          │
│ ( Agregar historial )                                     │                          │
└───────────────────────────────────────────────────────────┴──────────────────────────┘
```

"Agregar exalumno" at 390, the same form one column wider at 1280:

```
┌──────────────────────────────────────┐
│ Nuevo alumno                         │
│ ( Entrena aquí ) (● Ya no entrena )  │
│ Nombre [ Diego Rojas             ]   │
│ RUT    [ 9.876.543-2             ]   │
│ Teléfono (opcional) [            ]   │
│ Alumno desde [ 03-2017 ]             │
│ Fecha de baja [ 15-01-2022 ]         │
│ Motivo [ Se cambió de ciudad     ]   │
│ (Precio)(Horario)(Se cambió)(Motivo  │
│ personal)(Otro)                      │
│ No le escribiremos: queda en         │
│ Dados de baja con su historial.      │
│ [ Cancelar ] [ Agregar exalumno ]    │
└──────────────────────────────────────┘
```

A coach sees "Alumno desde", the belt and the class total, as now; not the Historial
card, the reason for leaving or the history payments.

## 5. Overlap with #286 and the corrections tickets

| Case | Owner | Why |
|---|---|---|
| A current student paid months that their Rakin plan covers (from its start on) | **#286 "Pagado hasta"** | billing must know those months are paid; real ledger entries on real periods |
| An imported current student's next due date | **the importer, as today** (`Próximo vencimiento`) | sets `current_period_end`; no payments written |
| Anything paid before their first Rakin plan, or by someone with no plan | **#292, historial** | billing must never know |
| A debt from before Rakin they still owe | **Cobros (#195)**, a one-off charge for that person | owed now: ledger |
| Fixing a history line | **#292**, delete and type again | not ledger, no correction entry |
| Fixing a ledger line | **#277–#285** | unchanged |

So #286 needs no history and history needs no correction primitive. The one link is
the form's pointer: a month the plan covers sends the owner to "Pagado hasta", and #286's
form, for a month before the plan's start, says "Antes de su plan: agrégalo al
historial".

## 6. Audit

History uses #277's record (`audit_event` with `person_id` and the app-role insert
policy), so it **follows #277**. New actions:

- `history_imported`: one row per import that wrote anything (not a dry run): the file's
  name, its SHA-256, the tabs, and the counts written per tab. `person_id` null. Its id
  is the `import_id` every row it wrote carries.
- `history_set`: a person's `member_since`, `left_reason` or `prior_classes` written,
  by hand or by an import (with `import_id`): `{"member_since": {"before": null, "after":
  "2019-03-05"}}`. One row per person, not per field.
- `history_removed`: a history payment deleted, with the whole row in `detail`, and the
  reason.

A history payment and a grade carry `source`, `import_id`, `created_by` and `created_at`
themselves, so writing one by hand needs no audit row (a year of payments would be twelve
rows saying the same as the payments). The Historial card shows the source on each line
("importado de pagos_meta.xlsx · Ana · 14 nov"), and #277's "Correcciones" lists the
three actions with the rest.

**Deshacer importación**: the import's line in Importar's recent list offers it, owner
only, with a reason. It deletes the history payments and grades with that `import_id`,
and puts back `member_since`, `left_reason`, `left_on` (of someone it made a former
student) and `prior_classes` the import set, where they still hold its value (one changed since is kept, and the confirmation says how many).
People and memberships it created stay: they are today's import, which has no undo; a
former student it created can be deleted from their ficha, since they have no ledger.
Grades are append-only to the app role, so the undo runs through a `SECURITY DEFINER`
function, as `forget_gym_person` does, which deletes only rows with that `import_id`.
The undo writes an `import_undone` row with its reason and what it removed, and an
import is undone once.

## 7. Privacy

- **Who sees it.** History payments and the reason for leaving: owner and admin only
  (`LEDGER_ACCESS`), never a coach, never the student. "Alumno desde", the belt and the
  class count are what a coach sees today.
- **Rakin never writes to a former student.** An imported or added former student gets
  no welcome; a person with `left_on` holds no membership, so no billing mail reaches
  them, and the cobros screen already leaves them out. The first ticket adds a test that
  nothing in `app.notices` is sent to someone with `left_on`.
- **Deleting a former student works**, and deletes all their history:
  `forget_gym_person` gains the history payments, the person-level grades and the
  person's `history_set` and `history_removed` rows, and counts them in
  `person_deleted`. `audit_event` stays append-only to `rakin_app`, as #277 has it:
  only that definer function deletes a row, and the `person_deleted` row, which names
  nobody, is the only trace left. An import's `history_imported` and `import_undone`
  rows carry no `person_id` and stay. A former student whose only
  money is history holds nothing in the ledger, so nothing refuses: `forget_refusal`'s
  `payment`, `pending` and `owes` read only the ledger and the periods.
- **Retention.** History is kept while the person is: the gym keeps its own student
  records, and the owner can delete anyone. No automatic purge now. Chile's new data
  protection law (Ley 21.719) applies from December 2026 and expects data kept for a
  purpose and deleted on request; deleting covers the request, and the gym's privacy
  notice (#168) gains one sentence: "Si dejas de entrenar, guardamos tu historial
  (inicio, pagos y grados) hasta que pidas que lo borremos." A later "exalumnos sin
  actividad hace más de N años" clean-up is a small addition if an owner wants it.
- **The reason for leaving** must not be health data: a gym may not keep it, even with
  consent (art. 16 bis, #384). No chip names an injury, and the hint asks for no health
  data: "Motivo personal" is enough.

## 8. The pilot gym (Meta)

ops#4 already holds the rule: **the real sheet is never committed**, not even
anonymised, and the first run is a dry run on a local stack. History extends it:

1. **Before**: #277 and the first history tickets are deployed; Meta's plans and grading
   scheme are set in Ajustes, so the Plan and Grado columns match.
2. **Fill the template** with the owner, outside any repository checkout (a folder
   in the owner's documents, never the worktree). Most of Meta's payment record is a grid by
   month; copy it into the Pagos tab's rows with the instructions tab's recipe.
3. **Dry run locally** (`docker compose up`, plans and ranks typed as in prod): upload,
   read every refusal. Report counts and codes on ops#4, never names.
4. **Fix the sheet**, repeat until the only refusals are understood ones.
5. **Dry run on production**, which writes nothing, and compare its summary with the
   local one.
6. **Import on production.** Check five fichas with the owner: "Alumno desde", the belt,
   a year of payments, a former student. Check Pagos' "Esperado" and Hoy did not change.
7. **If wrong**: Deshacer importación, fix, import again.
8. **After**: delete the local copy and the local database (`docker compose down -v`), as
   ops#4 says.

## Build tickets

In order. Each is one PR. All follow #277 (the audit record). The first two are the
model and make sense alone; the import tickets come after the by-hand ones, so every
field has a screen before a sheet can fill it.

1. **#293 Alumno desde and classes before Rakin.** `gym_person.member_since` and
   `prior_classes`; the ficha's "Alumno desde" reads the earliest of it and the first
   plan; the class total adds `prior_classes`; "Fecha de inicio y clases" on the ficha;
   `history_set` audit rows.
2. **#294 Former students: why they left, and Agregar exalumno.** `left_reason`; Dar de baja
   asks Motivo and takes 60 years (the `member_roll` check); "Ya no entrena aquí" in Nuevo alumno; owner and admin
   only; the notices test; the privacy notice's sentence.
3. **#295 Historial de pagos.** `history_payment`; the Historial card; "Pagos anteriores",
   twelve months in one form; the boundary with the plan and the pointer to #286;
   delete with a reason (`history_removed`); forget deletes them; the test that billing,
   views and the export are unchanged; the export's footnote line.
4. **#296 Grados anteriores: grades belong to the person.** `grade_event.person_id`,
   nullable `membership_id`, `source`; reads move to the person; a history grade writes
   no `promoted` event; "Grado anterior" open to someone with no plan; forget.
5. **#297 Importar: the history columns on Alumnos, and the template.** Alumno desde, Fecha
   de baja, Motivo de baja, Clases antes de Rakin; former-student rows; fill when empty;
   the header suggestions; `HISTORY_WINDOW_YEARS`; `history_imported` rows and
   `import_id`; "Descargar plantilla" (Alumnos tab, and the instructions).
6. **#298 Importar: the Pagos tab.** Tabs read by name (CSV: chosen); one transaction in
   order; finding people without creating them; `unknown_person`, `covers_plan`,
   `invalid_amount`; idempotent matching; 20,000 rows; the template's Pagos tab.
7. **#299 Importar: the Grados tab.** Rank matching and choices; sub-ranks by label or
   number; `unknown_rank`; idempotent matching; the template's Grados tab.
8. **#300 Deshacer importación.** The undo of an import's history, owner only, with a reason,
   through a definer function; Importar's recent imports list.

The pilot's load (§8) is ops#4's, once #297, #298 and #299 ship, and #300 before the
real import, so a wrong load can be undone.
