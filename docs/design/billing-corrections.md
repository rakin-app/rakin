# Billing corrections: full control of a student's billing (#272)

Spike, November 2026. No product code: this doc decides what the owner and admins can
correct on a student's billing, how the ledger records it, what stays forbidden, and
how the ficha offers it. The build tickets at the end carry it out, in order.

## For the owner, in short

- **Every mistake on a student's billing can be fixed from the ficha**, without asking
  anyone to touch the database: a charge voided by mistake comes back, a payment
  recorded on the wrong month or plan moves, a debt can be forgiven, a lapsed plan can
  be reactivated and a cancel undone.
- **Nothing is ever erased.** A fix is a new line in the Libro, beside the line it
  fixes, with who made it, when and why. A reason is always required. The Libro shows
  the fix; a "Correcciones" list on the ficha shows every fix with the amount before and
  after.
- **One button.** Tap any line of the Libro and choose "Corregir": the ficha offers only
  the fixes that make sense for that line. Fixes to the whole plan are under "Corregir
  plan".
- **The owner and admins can do all of it; coaches never.** Every fix names who made
  it, so the owner can see what an admin changed.
- **A few things stay impossible, for everyone**: changing or deleting a payment the
  student already got a receipt for (it is undone with a new line, and the student is
  told), and anything that would make the balance disagree with the Libro.
- **The student from the pilot (#271)** can be fixed today with two actions, and will
  be fixed cleanly once "Restaurar cargo" ships: void the old plan, restore the charge
  voided by mistake. The walk-through is below.

## What exists today

What the app has now, so the design builds on it rather than beside it:

- **The ledger is append-only** (`ledger_entry`, migration 0002). A validated entry can
  never change or be deleted; the trigger lets only a pending proof be validated or
  rejected. The one exception is `forget_gym_person` deleting a person (0044).
- **A billing period** (`billing_period`) holds its amount due and dates. It is settled
  by the validated `payment`, `adjustment` and `refund` entries on it
  (`app.domain.billing`, `settled_amount`); the `charge` entry the job writes beside it
  is what `v_balance` counts. So **a period's `amount_due_clp` and its charge entry
  must agree**, or the ficha's "debe" and the balance on the receipt disagree. The
  period rows are not append-only: a freeze moves their dates (`shift_billing_periods`,
  0027).
- **Corrections that exist**: an adjustment on a period, in the member's favour (up to
  what it owes) or against them ("Recargo"), with a required note (#38); a refund of a
  validated payment (#38); a void of what a period owes (`voids`, one per period, #256);
  a plan voided as of its start (#256); a cobro extra line cancelled with a reason
  (#256); since #271, "Anular cargo" reaches every plan of the member, and a voided
  charge is put back with a Recargo of the amount the void took off.
- **Who and when**: every entry the API writes carries `validated_by` and
  `validated_at` (`app.api.entries`); an adjustment's note is its reason.
  `audit_event` (0044) is the gym's log, but only a person's deletion writes it.
- **The student** sees their payments, refunds and adjustments in "Mis pagos" (`/me`),
  without the admin's notes, except a rejection's and a carried credit's.

What is missing, from the real cases:

1. A **restored void is still a void.** After a Recargo puts a voided charge back, the
   charge still reads "Anulado" in the Libro, "Esperado" still leaves it out, and the
   period can never be voided again (`ledger_entry_one_void` is one per period, ever).
2. A **payment on the wrong period or plan** can only be refunded and recorded again,
   which reports money given back that never left, and a second receipt.
3. A **payment recorded by mistake** (wrong amount, wrong member) has the same problem.
4. **No status change can be undone.** A lapsed plan stays lapsed even once paid: the
   module docstring of `app.domain.membership` says a payment returns it to Active, but
   no code does. A cancel is final in the database (0009).
5. **No due date can be moved** except by a freeze.
6. **No debt can be forgiven** as such: a void says the charge was a mistake, which
   leaves "Esperado" wrong for a charge that was real but will not be collected.
7. **No record of before and after**: a correction's entry says what it did, not what
   the period and the balance were before it.

## 1. The corrections

Each real case, what it becomes, and whether it exists:

| # | Correction | What it is | Today |
|---|------------|-----------|-------|
| C1 | Void a charge, any plan (lapsed and cancelled included) | void entry (exists) | ✅ #256, #271 |
| C2 | Restore a charge voided by mistake | `restore` entry against the void | ⚠️ Recargo, half-way |
| C3 | Change a charge's amount ("cobrar $20.000 en vez de $25.000") | adjustment of the difference | ✅ Ajuste, which asks for the difference; #279 asks for the new amount |
| C4 | Undo an adjustment | `revert` entry against it | ❌ |
| C5 | Add a one-off charge | a cobro extra line for one person (#195) | ✅ from Cobros; not from the ficha |
| C6 | Move a payment to another period or plan | `move` pair: out of one period, into another | ❌ |
| C7 | Undo a payment recorded by mistake | `mistake` entry against the payment | ❌ (refund, misreported) |
| C8 | Change a period's due date | row change + audit | ❌ |
| C9 | Change a period's dates | **not offered**: void it, or freeze | — |
| C10 | Reactivate a lapsed plan | row change + audit | ❌ |
| C11 | Undo a cancel | row change + audit | ❌ (the DB refuses) |
| C12 | Undo a lapse | = C10 | ❌ |
| C13 | Merge two plans of one person | **not a primitive**: C6 for each payment, then void the duplicate plan | — |
| C14 | Set the paid-through date by hand | **not offered**: derived from the periods; a shortcut writes payments or discounts per period | — |
| C15 | Write off a debt ("condonar") | `write_off` entry | ❌ (a void, misreported) |

Why C9, C13 and C14 are not corrections of their own:

- **C9, a period's dates.** A period's dates decide what the next one bills from
  (`billed_through`), the anchor day and the `(membership_id, period_start)` key. A date
  typed by hand there can leave a gap or an overlap billing would then honour forever.
  The real cases are "the month was billed but they were away", which is a freeze (or a
  void, after the fact), and "the plan should bill on the 15th", which is a plan change
  from a day (#249). The due date alone (C8) is safe to move, and is the case owners
  ask for: "le doy hasta el 10".
- **C13, merging.** Two plans of one person are two histories with their own periods.
  "Merging" them always means: keep one, move what was paid on the other onto it (C6),
  and void the other (C1, "Anular plan"). Built from those, every step is visible in the
  Libro and each can be undone; a merge primitive would be one opaque step that cannot.
- **C14, paid-through.** "Pagado hasta" is computed from the periods
  (`billing.paid_through`). A date set by hand would say "paid" while the ledger says
  "owes", the one thing the guards below exist to prevent. The cases behind it are a
  member who paid before the gym used Rakin (record those payments, or pay ahead,
  #196) and a gift ("le regalamos diciembre", a discount adjustment, or C15). A
  "Pagado hasta…" shortcut may write those entries period by period; that is a
  convenience on top, listed last in the tickets.

## 2. The model: append-only with correcting entries

**Recommendation: keep the ledger append-only, and record every correction of money as
a new entry linked to what it corrects.** Change rows only for what is not money: a
due date and a membership's status, each with an audit row.

Why not editable rows with a change log:

- **The guarantee is already in the database.** The append-only trigger means no bug,
  and no admin, can quietly change what was paid. A change log beside editable rows is a
  second copy of the truth that the app must remember to write; a correcting entry
  cannot be forgotten, because it *is* the change.
- **Every total already adds entries up.** `v_balance`, `v_overdue`, `v_monthly_income`,
  the lapse job, the receipts and "Mis pagos" all sum entries. A new entry flows through
  all of them with no change to most; an edited row would need each to agree on which
  version it reads.
- **Receipts were emailed.** A payment's receipt is in the student's inbox. Editing the
  row would make the app disagree with a document the student holds; a correcting entry
  keeps both, and says what changed.
- **Reports stay as they were reported.** A correction lands in the month it is made,
  so November's "Cobrado", once given to the accountant, stays what it was.

The cost is that the Libro grows a line per fix, and that "the amount of a charge" is
its amount due plus its adjustments rather than one number. Both are already true
today (Ajuste, Anular cargo); the UI below shows a corrected line with its fix under it.

### What changes in the ledger

**No new entry kind.** The four kinds stay `charge`, `payment`, `adjustment` and
`refund`, so settlement (`settled_amount`, `SETTLING_KINDS`) and the views keep their
arithmetic. Two columns say what a correction is:

- `ledger_entry.purpose` (text, nullable): why an adjustment or refund was written, when
  it is a correction. `void` replaces the `voids` boolean (migrated: `voids` becomes
  `purpose = 'void'`, and stays readable as a generated column for one release, or is
  dropped with its readers in the same PR).
- `ledger_entry.corrects` (uuid, nullable, references `ledger_entry`): the entry this
  one undoes or moves. A check keeps it to the purposes that need it.

| Purpose | Kind | Amount | `corrects` | Settles the period as | Counts in |
|---------|------|--------|-----------|------------------------|-----------|
| *(none)* | adjustment | ± | — | today: + favour, − owed | today |
| `void` | adjustment | + all owed | — | today | not in "Esperado" (today) |
| `restore` | adjustment | − the void's amount | the void | owed again | "Esperado" again: the void no longer counts once restored |
| `revert` | adjustment | − the adjustment's | the adjustment | as if it never was | — |
| `write_off` | adjustment | + all owed | — | nothing owed | "Esperado" keeps it; a "Condonado" figure beside "Vencido" |
| `move` (out) | refund | the amount moved | the payment | the old period owes again | not a refund: left out of `refunds_clp` and `income_clp` |
| `move` (in) | payment | the amount moved | the payment | the new period paid | not income: the money was counted when first paid |
| `mistake` | refund | what is left of the payment | the payment | the period owes again | income of the month it is made, as "Pagos anulados", not as a refund |

What each needs beyond the row:

- **`restore`**: a void can be restored once; a restored void no longer marks its charge
  voided (`VOIDED_JOIN` reads a void with no restore against it), and "Esperado" counts
  the period again. The unique index becomes "one void without a restore per period",
  enforced under the period's lock (`locked_period`) and backed by a constraint trigger,
  since a partial index cannot look at another row. #271's Recargo hint on the Ajuste
  form becomes "Restaurar cargo".
- **`move`**: two entries in one transaction, the pair sharing `corrects` (the original
  payment). Out: a refund-shaped entry on the old period, `refund_of` the payment, so
  what is left to refund or move of it goes down as a refund would take it (`REFUNDED`).
  In: a validated payment on the new period, with the original's method, settled by
  `billing.apply`, so an overpayment carries credit as any payment does. Both periods
  are locked, membership first, in id order. `v_monthly_income` leaves both out.
  `v_balance` moves the amount from one membership to the other; the person's total is
  unchanged. Allowed between periods of the same person, and between people who share a
  guardian (a parent paying for two children, recorded on the wrong one), never between
  unrelated people.
- **`mistake`**: a refund-shaped entry of what is left of the payment (after earlier
  refunds and moves). `v_monthly_income` reports it in a column of its own,
  `corrected_clp`, so "Cobrado" nets it in the month it is made and "Reembolsos" does
  not show money that never left. It emails the student a short correction ("El pago de
  $30.000 del 3 nov se anuló: fue un error de registro. Tu saldo es $X.") so the receipt
  in their inbox is not silently wrong. To record the right amount, the admin then
  records a payment as usual.
- **`write_off`**: as a void, refused on a period with money or a proof waiting on it.
  It differs from a void only in the reports: the charge was real, so "Esperado" keeps
  it, and the book's KPIs add "Condonado" for the month.

`forget_refusal` and `forget_gym_person` (0044) need only the new purposes in their
sums: a moved-out and a mistaken payment count as given back, so a person whose only
payment was recorded by mistake can still be deleted.

### What changes in rows

Each writes an `audit_event` row in the same transaction (below).

- **Due date (C8)**: `billing_period.due_date` of a period not paid in full, to any day
  from its start to its end plus 60 days. It moves the lapse and the overdue emails with
  it, since both read `due_date`. A trigger refuses any `UPDATE` of `amount_due_clp`,
  so the period and its charge entry can never disagree; dates change only through
  `shift_billing_periods` (freezes) and this.
- **Reactivate a lapsed plan (C10, C12)**: `lapsed → active`, which the domain already
  allows. Refused while a period past due plus grace is unpaid, since the job would lapse
  it again that night (the reason #271 did not reactivate); the form says what to do
  first: record the payment, move the due date (C8), write off or void the period. It
  asks **from when to bill**: by default, after the last period billed, catching up the
  months since the lapse one per cycle, as the job catches up after downtime, with each
  listed and priced before saving; or from today, setting `current_period_end` to
  yesterday so the gap is not billed (`_first_unbilled` already takes the later of it
  and `billed_through`). Separately, a payment that settles the last unpaid period of a
  lapsed plan offers "Reactivar plan" in its success message; it does not reactivate
  on its own, because a member who paid an old debt may have left.
- **Undo a cancel (C11)**: `cancelled → active`, or `lapsed` if a period past due plus grace is unpaid (it would lapse again that night),
  clearing `cancel_reason` and `cancelled_at`. The 0009 trigger lets it through only for
  a membership not voided, and only when an `audit_event` row for it is written in the
  same transaction (the API writes it first, the trigger checks for it). Refused when the
  person has started another plan since, which would leave them with two live ones; the
  form says so and offers to move the payments instead. It bills from when as C10 does.
  A freeze booked ahead that the cancel called off stays called off.

### Why no hand edit of an amount

An amount due is changed with an adjustment of the difference (C3), never by editing
`amount_due_clp`. The form asks the question the owner asks ("¿Cuánto debe cobrarse este
mes?", the new amount) and writes the difference, positive or negative, with the reason.
The Libro shows the charge with its adjustment under it: "Cuota noviembre $25.000 ·
Ajuste −$5.000 · cobrar $20.000: hermano".

## 3. The audit trail

Every correction records **who, when, the reason, and the period and balance before and
after**.

- **Who and when** are already on every entry (`validated_by`, `validated_at`) and the
  reason is the entry's note, required for every purpose. For a row change there is no
  entry, so the audit row is its only record.
- **`audit_event` becomes the record of every correction**, entries and row changes
  alike, so one query answers "what was changed on this student". New actions:
  `ledger_corrected` (C2–C4, C6, C7, C15, and the existing void and adjustment from now
  on), `due_date_changed`, `membership_reactivated`, `cancel_undone`. A `person_id` column
  (nullable) says whose; `detail` holds what the action touched and the figures:

  ```json
  {
    "purpose": "restore",
    "membership_id": "…", "billing_period_id": "…", "entry_ids": ["…"],
    "before": {"outstanding_clp": 0, "balance_clp": 0},
    "after":  {"outstanding_clp": 25000, "balance_clp": 25000}
  }
  ```

  Row changes put the field instead: `{"due_date": {"before": "2026-11-01", "after":
  "2026-11-10"}}`, `{"status": {"before": "lapsed", "after": "active"}, "bill_from":
  "2026-11-13"}`.
- **Writing it**: the app role gets `INSERT` on `audit_event`, with a policy that the
  actor is the person acting (`app.person_id`), the gym the current one, and the action
  a correction; nothing updates or deletes a row. The figures are read under the same
  locks as the correction, so before and after are exact.
- **Deleting a person** (`forget_gym_person`) deletes their correction rows with the
  rest of their history and counts them in the `person_deleted` row, which keeps nothing
  about them, as 0044 decided for the ledger.

Where it shows:

- **In the Libro**, a corrected line shows its fix under it, in the line's own place:
  "Cuota noviembre · Anulado: duplicado, por Ana, 2 nov · Restaurado: se anuló el cargo
  equivocado, por Martín, 13 nov". The Libro stays the money; nothing is hidden.
- **"Correcciones"**, a section of the ficha under the Libro, owner and admin only:
  every audit row of the person, newest first, one line each: what, the period, before →
  after, the reason, who, when. Collapsed to the latest three, with "Ver todas (N)".
- **The student sees the money, not the audit.** "Mis pagos" shows the entries as now
  (a restored charge is owed again; a moved payment reads "Pago movido de noviembre a
  diciembre"; a mistaken one "Pago anulado: error de registro"), without the admin's
  reason, who made it, or the before and after. The one thing emailed is C7's
  correction, since it undoes a receipt they hold.

## 4. Guards

**Forbidden for everyone, the owner included** (the database refuses where it can):

1. Changing or deleting a validated ledger entry: a payment, once its receipt is
   emailed, is undone (C7) or moved (C6), never edited. *(trigger, 0002)*
2. Changing a period's amount due by hand: amounts change by adjustments, so the
   balance always equals the ledger. *(new trigger on `amount_due_clp`)*
3. Setting "Pagado hasta" by hand (C14). *(no endpoint)*
4. Moving money between people who are not the same person or share a guardian.
5. Voiding, writing off or reactivating over money in flight: a period with a proof
   waiting is reviewed first; one with money on it is refunded or moved first (as #256).
6. An adjustment in the member's favour beyond what the period owes: credit is a
   payment's to carry (as #38).
7. Restoring a void twice, reverting a revert, or correcting a correction's own
   entry other than by its inverse.
8. Undoing the void of a plan, or the deletion of a person: both are for mistakes, and
   final. A plan voided by mistake is assigned again.
9. Changing or deleting an audit row.

**Needs a confirmation step**: every correction form shows the period and the balance
before → after as the admin types, and its button names the fix ("Restaurar cargo").
These five ask once more, in a second step that says what else happens:

- **Anular pago (C7)**: "Se enviará a <nombre> un aviso de que el pago se anuló."
- **Mover pago between plans (C6)**: names both plans.
- **Reactivar plan (C10) and Deshacer baja (C11)**: lists the periods it will bill, and
  their total, or says it bills from today.
- **Condonar deuda (C15)**: "Esta deuda no se cobrará; seguirá contando en Esperado."

## 5. UI: one "Corregir"

**Recommendation: one "Corregir" per line of the Libro, and one "Corregir plan" on the
plan.** Not a button per fix: the ficha already has Ajuste, Reembolso, Anular cargo and
Anular plan beside Registrar pago, Congelar and Cambiar plan, and every fix above would
add another. Each line knows what can be done to it, so the ficha offers only that, and
a fix starts from the line it fixes, which is how the owner describes the mistake
("el cargo de noviembre", "el pago del 3").

- **A charge line** (one per period): Cambiar monto (C3), Mover vencimiento (C8),
  Anular cargo (C1) or Restaurar cargo (C2), Condonar deuda (C15).
- **A payment line**: Mover a otro mes o plan (C6), Anular pago (C7), Reembolsar (the
  existing refund, also here).
- **An adjustment line**: Revertir (C4).
- **"Corregir plan"**, on the plan's card: Reactivar plan (C10), Deshacer baja (C11),
  Anular plan (#256, moved here), Cobro extra (C5: opens Cobros' wizard with the person
  filled in).

"Ajuste" and "Anular cargo" leave the action row: both are now under a line. Registrar
pago, Congelar and Cambiar plan stay where they are: they are what the gym does, not
fixes. Each line in the Libro becomes a button that opens its fixes in place under it,
as the ficha's forms open today, so nothing navigates away. Lines past the first four
are under "Ver todo", as now.

At 390 (a phone). `~$25.000~` is a struck-through amount:

```
┌──────────────────────────────────────┐
│ Libro                                │
│ ● Cuota diciembre          $25.000 › │
│   generado 24 nov · por pagar        │
│ ● Pago noviembre           $25.000 › │
│   transferencia · validó Ana · 3 nov │
│ ○ Cuota noviembre        ~$25.000~ › │
│   Anulado: duplicado · Ana · 2 nov   │
│ ┌──────────────────────────────────┐ │
│ │ Corregir cuota noviembre         │ │
│ │ ( Restaurar cargo )              │ │
│ │ ( Mover vencimiento )            │ │
│ │                                  │ │
│ │ Motivo                           │ │
│ │ [ Se anuló el cargo equivocado ] │ │
│ │ Debe en noviembre  $0 → $25.000  │ │
│ │ Saldo              $0 → $25.000  │ │
│ │ [ Cancelar ] [ Restaurar cargo ] │ │
│ └──────────────────────────────────┘ │
│ Ver todo (12)                        │
│                                      │
│ Correcciones                         │
│ Anuló cuota nov · $25.000 → $0       │
│   duplicado · Ana · 2 nov            │
└──────────────────────────────────────┘
```

At 1280 (a desktop): the Libro and its fixes in the ficha's main column, the plan card
with "Corregir plan" in the side column.

```
┌───────────────────────────────────────────────────────────┬──────────────────────────┐
│ Libro                                                     │ Mensual · Activo         │
│ ● Cuota diciembre  generado 24 nov · por pagar  $25.000 › │ Pagado hasta 30 nov      │
│ ● Pago noviembre   transferencia · Ana · 3 nov  $25.000 › │                          │
│ ○ Cuota noviembre  Anulado: duplicado · 2 nov ~$25.000~ › │ [ Registrar pago ]       │
│   ┌─────────────────────────────────────────────────────┐ │ [Congelar] [Cambiar plan]│
│   │ Corregir cuota noviembre                            │ │ [ Corregir plan ▾ ]      │
│   │ ( Restaurar cargo ) ( Mover vencimiento )           │ │   Reactivar plan         │
│   │ Motivo [ Se anuló el cargo equivocado             ] │ │   Deshacer baja          │
│   │ Debe en noviembre $0 → $25.000 · Saldo $0 → $25.000 │ │   Anular plan            │
│   │                       [ Cancelar ] [ Restaurar ]    │ │   Cobro extra            │
│   └─────────────────────────────────────────────────────┘ │                          │
│ Correcciones                                              │                          │
│ Anuló cuota nov · $25.000 → $0 · duplicado · Ana · 2 nov  │                          │
└───────────────────────────────────────────────────────────┴──────────────────────────┘
```

Only what applies is offered (the ficha's rule since #256): a line with nothing to fix
has no "›", and "Corregir plan" lists only what the plan's status allows. Coaches see no
Libro, so none of this.

## 6. Roles

**Owner and admin, all of it. Coaches never.** The owner's position is that an admin
must have complete control, and the ledger already runs on that (`LedgerSession`; RLS
in 0006 refuses a coach at the database). What makes it safe is not a narrower role but
the record: every fix names who made it, the owner reads every admin's in
"Correcciones", and nothing can be erased. Deleting a person stays the owner's alone
(#157), as now. If an owner later wants to keep some fixes to themselves, a gym setting
("solo el dueño anula pagos") is a small change on top; nothing here needs it now.

## 7. The member from #271, end to end

The state on staging, from #271: plan **A** lapsed, with November's $25.000 unpaid;
plan **B** active, started the same day, whose November $25.000 was voided ("duplicado"),
though A's was the one meant. The member owes $25.000 on A and nothing on B. #275 has
since fixed the flow, so it cannot happen again; this repairs the one member. The PM
should first check on the ficha that no payment has landed on either November since.

What the result should be: one plan, B; November owed once, on B; A gone from Hoy and
from the balance.

**With what the app has today (no SQL):**

1. Ficha → plan A (Caducado) → **Anular plan**, motivo "Plan duplicado (#271)". A has
   no money on it, so the void goes through: A ends as of its start, its November charge
   is voided, and it leaves Hoy.
2. Ficha → plan B → **Ajuste** → November (marked "anulado $25.000") → **Recargo
   $25.000**, motivo "Se anuló el cargo equivocado". B's November owes $25.000 again,
   on Hoy once it is past due.

That leaves the money right and three blemishes: B's November charge still reads
"Anulado: duplicado", the book's "Esperado" leaves it out, and it can never be voided
again.

**Once "Restaurar cargo" ships (#278):**

1. As above: **Anular plan** on A.
2. Libro of B → the November charge line → **Corregir → Restaurar cargo**, motivo "Se
   anuló el cargo equivocado". B's November owes $25.000; the line reads "Anulado:
   duplicado · Restaurado: se anuló el cargo equivocado"; "Esperado" counts it; it could
   be voided again; "Correcciones" lists both fixes with $0 → $25.000.

If the PM repairs it today with the Recargo, #278's migration does not convert it:
a Recargo is an adjustment, not a restore. The charge would keep reading "Anulado".
That is cosmetic, but if it matters, wait for #278 to do step 2.

If a payment had landed on A's November in the meantime, step 1 is refused ("tiene un
pago"); **Mover pago** (#280) moves it to B's November first, and then A voids.

## 8. Overlap with #271

#271 is merged (#275). What it built stays, and these tickets build on it:

- **"Anular cargo" across every plan** (#271 point 4) is kept as it is. #279 moves
  it from the action row to a charge line's "Corregir", with the same plan labels.
- **Restoring a voided charge with a Recargo** (#271 point 6, the `voided_clp` hint on
  the Ajuste form) is **replaced** by "Restaurar cargo" (#278). The hint goes, and
  `voided_clp` stays for the line to know it can be restored. The caveat #275 left
  ("Esperado" leaves out a restored charge) is fixed there.
- **The start after a lapsed plan's last period** and **one Hoy row per member**
  (#271 points 1, 3) are not corrections, and nothing here touches them.

## Build tickets

In order. Each is one PR. The first three lay down the record, the model and the frame; the rest can go in
any order after #279, except #285, which follows #284.

1. **#277 Corrections record who, why, and before and after.** `audit_event` gains the
   correction actions and `person_id`; the app role inserts them under a policy; the
   existing void, plan void and adjustment write one with before and after. The ficha's
   "Correcciones" section. Backend + ficha.
2. **#278 Restaurar cargo.** `purpose` and `corrects` on `ledger_entry` (`voids` migrated
   to `purpose = 'void'`); a restore entry against a void; a restored charge no longer
   reads voided, counts in "Esperado" and can be voided again. Replaces #271's Recargo
   hint.
3. **#279 One "Corregir" per Libro line.** Lines become buttons that open their fixes in
   place; Ajuste becomes "Cambiar monto" (the new amount, not the difference); Anular
   cargo moves under a charge line, Anular plan under "Corregir plan". No new fix; the
   frame for the rest.
4. **#280 Mover pago.** The `move` pair, between periods and plans of one person or of
   people sharing a guardian; reports leave it out.
5. **#281 Anular pago registrado por error.** The `mistake` entry; "Pagos anulados" in
   the book; the correction email.
6. **#282 Revertir ajuste and Condonar deuda.** The `revert` and `write_off` entries;
   "Condonado" in the book's KPIs.
7. **#283 Mover vencimiento.** A period's due date, with its audit row; the trigger on
   `amount_due_clp`.
8. **#284 Reactivar plan caducado.** `lapsed → active`, billing from the last period or
   from today; "Reactivar plan" offered after a payment settles a lapsed plan.
9. **#285 Deshacer baja.** `cancelled → ` its status before, through the 0009 trigger
   with an audit row; refused beside another live plan.
10. **#286 "Pagado hasta…" shortcut.** Payments or discount adjustments per period up to
    a date, for a member who paid before the gym used Rakin. Lowest priority: payments
    ahead (#196) cover most of it.
