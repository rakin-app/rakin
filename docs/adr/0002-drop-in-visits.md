# ADR 0002: A drop-in visit is a one-day membership, ended as it starts

- **Status:** accepted
- **Date:** 2026-11-16
- **Issue:** #130

## Context

A drop-in visitor ("Clase suelta") pays for one class. The coach adds them on the
Clase roster, marks them present, and the gym charges the drop-in plan's price,
in the payment book until it is paid
([technical design](../technical.md#domain-model)).

Attendance hangs off a membership (`attendance.membership_id`), and so does the
ledger: a charge is a billing period's, and paying, a proof, a receipt, a refund,
a void, overdue and "Cobrado" all read billing periods. The issue proposed an
attendance row with no membership, carrying `person_id` and the plan, with its
charge on the ledger attached to the person, and allowed a one-day `dropin`
membership instead if the ledger cannot carry a charge without one.

It cannot. A ledger entry names a membership's period or a cobro extra line, and
a charge is only ever a period's (migrations 0001, 0037). A person-level charge
would mean a third owner for `ledger_entry`, a period of its own, and teaching
every reader of periods about it: payments, proofs, receipts, refunds, voids,
`v_overdue`, `v_balance`, the book and its export. The billing code already knows
a drop-in membership: one period, its first day to its first day, at the plan's
price, never lapsed (`app.domain.billing`, `app.jobs.lapse`).

## Decision

A visit is a **membership on the drop-in plan for the class's day, Cancelled as it
is written** (`app.domain.membership.drop_in`, reason `clase suelta`), present at
the class, with that day's one period and its charge.

- **Cancelled, not Active.** Nobody is on the plan after the class. Cancelled
  keeps the visitor off every later roster, out of the member counts and
  `v_inactive`, and away from the billing and lapse jobs, with no special case in
  any of them. It also makes a visit one class: a roster refuses to mark a
  cancelled membership at any other session.
- **Charged by a definer function.** A coach adds the visitor, but may not write
  the ledger (0006). `dropin_charge` (0061) bills the one period at the plan's
  price, for staff of the gym only.
- **Paid by the ledger's rules.** "Pagó en efectivo / por transferencia" records a
  validated payment, as Registrar pago does, and only for an owner or admin.
- **Unmarked the same day, voided.** Unmarking the visit on the day it was added
  voids what its period still owes and the membership with it, as Anular plan
  does, recorded among the corrections (`dropin_void`). Nothing is deleted. A
  visit with a payment the gym kept, or a proof waiting, stays marked: refunding
  or reviewing is the payment book's. So does a visit added on an earlier day.

## Consequences

- The visit is everywhere attendance and money already are, with no new reader:
  the Ficha's counts and history, the book, overdue, receipts, the export.
- The visitor's Ficha lists a cancelled "Clase suelta" plan per visit. The member
  list shows them by their latest, as anyone whose plan ended.
- A drop-in's charge is not in the book's "Esperado", which counts Active and
  Lapsed memberships. It is in Cobrado once paid, and in Vencidos while owed.
- A visitor is found again by their phone. Someone new has no RUT or email yet,
  "Falta RUT" until the gym adds one.
