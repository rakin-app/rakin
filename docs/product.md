# Rakin — Product

> Source of truth for scope. Technical design lives in [technical.md](technical.md); screens in [design/ui-design.html](design/ui-design.html).

## Overview and positioning

Rakin (rakin.app; Mapudungun rakin, to count) is an open-source, sport-agnostic membership and fee-tracking platform for small martial-arts gyms (under \~150 active students), launched first at the author's own BJJ academy. It replaces the spreadsheet plus WhatsApp group that most gyms run on today.

The core loop is: member → plan → due date → reminder → bank transfer arrives → validated in the ledger → silence. The product never processes money in v1; it tracks, reminds and reconciles transfers the owner already receives.

**It is:** a bookkeeping ledger for monthly fees, an attendance and class log for coaches, a thin student page (what do I owe, when, how to prove I paid), and a configurable grading / plan / custom-field layer so any martial art fits.

**It is not:** a CRM with sales pipelines, a scheduling or booking product, a payment processor, a cross-gym pass marketplace, or a native mobile app. It is a web app (PWA) with email as the system of record and WhatsApp as the reminder channel.


## Personas

Four personas, three of which may be the same human in a small gym. Each has one job the product must make faster than the spreadsheet, and one constraint that shapes the UI.

| Persona | Who | Primary job | Hard constraint | Frequency of use |
| --- | --- | --- | --- | --- |
| Owner / admin | runs the gym, often also head coach | know who owes what today, validate transfers, send reminders | will not share finances with part-time coaches; does bookkeeping on a phone between classes | daily, 5 min; monthly, 30 min at closing |
| Coach | teaches classes, may be a volunteer or paid per class | take attendance in under 5 s, log the session topic, see who is drifting | no budget, no obligation to enter data; anything slower than a WhatsApp list will not be used | per class |
| Student (adult) | trains 2–4×/week, pays by transfer | know due date and amount, upload proof, see belt and attendance | will not install an app or remember a password; reads WhatsApp, rarely email | 1–2× per month |
| Guardian | parent paying for one or more kids, may also train | pay for N dependents at once, see each child's grade and attendance | one payer, several students, kids have no phones | 1–2× per month |

Roles are per gym: the same person can be owner at gym A and student at gym B. Permissions follow the role, not the person.

## Product principles and non-goals

Six principles decide every scope argument; the non-goals are explicit so they can be cited when a gym asks.

1. **The ledger is the product.** Every other feature exists to feed it or read from it. Ledger entries are append-only; corrections are new entries.
2. **Never touch money in v1.** Track, remind, reconcile. Processing payments (card, Mercado Pago, Khipu checkout) is a v2 plugin, not a core dependency.
3. **Five-second attendance.** If a coach can't mark a 20-person class in the time it takes to bow in, it won't be used and the second ledger is empty.
4. **Students never need an account they manage.** Magic links from email or WhatsApp; the PWA install is optional.
5. **Sport lives in configuration.** Grading schemes, plan types and custom fields are per-gym data. No sport-specific code paths in the core.
6. **Identity is global, membership is per gym.** One person, N memberships. Decided now so the network features are rows, not migrations.

**Non-goals (through v2):** class booking and capacity, native iOS/Android apps, sales pipeline / lead CRM, expense tracking and accounting, SII boleta issuance (export only), cross-gym prepaid pass packs that move money between gyms, a round timer, a content library for techniques.

## Feature scope by release

v1 is one gym (the pilot), v2 unlocks when five gyms are running it, v3 only when one city has enough density for cross-gym features to mean something. Each row is a feature; the release column is the earliest it ships.

| Area | Feature | v1 | v2 | v3 |
| --- | --- | --- | --- | --- |
| People | person (global), guardian ↔ dependent links | ✓ |  |  |
| People | per-gym custom fields (text, number, date, enum) | ✓ |  |  |
| People | waivers / consent signed on phone, stored as PDF |  | ✓ |  |
| Plans | monthly recurring (anchor on signup day or 1st), prepaid N months, credit pack (N classes, expiry), drop-in, trial | ✓ |  |  |
| Plans | family / sibling discount, scholarships (fixed % off) | ✓ |  |  |
| Plans | proration on mid-period changes |  | ✓ |  |
| Ledger | charges generated nightly from memberships; append-only entries; pending → validated → rejected | ✓ |  |  |
| Ledger | student uploads transfer proof via magic link; admin notified; one-tap validate | ✓ |  |  |
| Ledger | cash / other method recorded by admin | ✓ |  |  |
| Ledger | partial payments, adjustments, refunds as entries | ✓ |  |  |
| Ledger | bank reconciliation: Fintoc read-only or Khipu self-confirming transfers, fuzzy match on amount + name/RUT, one-tap confirm |  | ✓ |  |
| Ledger | card / Mercado Pago checkout as plugin |  | ✓ |  |
| Ledger | monthly CSV/XLSX export for the accountant | ✓ |  |  |
| Membership | freeze / pause with automatic due-date shift and reason | ✓ |  |  |
| Membership | trial → conversion tracking | ✓ |  |  |
| Membership | signed membership badge (QR, public verify page) | ✓ |  |  |
| Classes | class types with program (adults, kids) and credit cost | ✓ |  |  |
| Classes | session with coach, topic, notes; roster tap attendance | ✓ |  |  |
| Classes | QR self check-in |  | ✓ |  |
| Classes | curriculum cycles (4–8 week themes) |  | ✓ |  |
| Classes | capacity and booking |  |  | ✓ |
| Grading | per-gym grading scheme (ranks, sub-ranks, kids ladder); promotion log | ✓ |  |  |
| Grading | class-count / time-in-rank goals with "ready for promotion" flag |  | ✓ |  |
| Retention | inactive 14 / 30 days list with one-tap WhatsApp | ✓ |  |  |
| Retention | automatic absence / anniversary messages |  | ✓ |  |
| Comms | email: receipts, statements, magic links, plan events | ✓ |  |  |
| Comms | WhatsApp via wa.me deep links from admin lists | ✓ |  |  |
| Comms | WhatsApp Business API templates, per-gym opt-in |  | ✓ |  |
| Comms | gym announcements to a program or everyone | ✓ |  |  |
| Network | reciprocal agreements between gyms (free open mat, drop-in price) validated by badge scan |  | ✓ |  |
| Network | visit log on the visiting person's global identity |  | ✓ |  |
| Network | multi-gym prepaid pass packs with settlement |  |  | ✓ |
| Admin | roles: owner, admin, coach; coach cannot see ledger | ✓ |  |  |
| Admin | full data export / import (hosted ↔ self-host) | ✓ |  |  |
| Admin | multi-location under one brand |  |  | ✓ |


**Definition of v1 done:** the pilot gym has completed two billing cycles with every payment in the ledger, the owner has not opened the old spreadsheet in 30 days, and average days-past-due is measurably lower than the pre-pilot baseline.
