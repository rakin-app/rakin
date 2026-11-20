# Resumen del mes: what Rakin can honestly say it did for a gym (#504)

Spike, 20 November 2026. No product code. It answers #504's five questions from the
code as it stands (each claim cites the file it rests on), the legal research in
[`legal-research.md`](../legal-research.md) and the texts in [`legal/`](../legal/README.md).
The build tickets are #505 to #508 ([section 5](#5-build-plan)).

**The legal parts are research, not legal advice.** They apply answers the lawyer
has already been asked about. None of them adds a new question for the lawyer.

## For the owner, in short

- **Rakin can say what happened after it acted. It cannot say what would have
  happened without it.** "$X llegó después de un recordatorio" is a fact the data
  proves. "Rakin recuperó $X" is a guess. The summary says the first and never the
  second.
- **The honest headline is the work nobody on the team had to do.** For example:
  "Rakin envió 64 recordatorios; 31 pagos atrasados ($1.240.000) llegaron después,
  23 de ellos sin que nadie del equipo escribiera." Every figure in that sentence is
  a count.
- **Almost everything is already in the database.** Payments, the reminders sent
  (email and WhatsApp), the nudges from the inactive list, attendance, proofs and
  their review times, reactivations and trial conversions are all there. The first
  ticket needs no migration.
- **Email open tracking: off.** Apple Mail and Gmail make opens close to
  meaningless. Turning it on would change the subprocessor annex, so every gym would
  have to accept the terms again. Click tracking would send every sign-in link
  through Resend. A better signal exists and needs no pixel: the email's own
  sign-in link, when the person taps its button. That is a later, optional ticket.
- **No new person-level history.** The summary is counts and sums per gym and
  month. Closed months are kept as a snapshot of those numbers, so they survive the
  log purges #378 plans.
- **The titular and anyone who can see money** (`money_read`) see it. Coaches do not.

## 1. What can be attributed, and how strictly

### What the data holds today

| Fact | Where it is | Notes |
| --- | --- | --- |
| Overdue email sent | `message_log`: `channel = 'email'`, `template = 'payment_overdue'`, `status = 'sent'`, `payload.billing_period_id`, `payload.on`, `sent_at` | The nightly job sends one on the due date, the next day, then every 3 days while the grace lasts (`app.domain.membership.is_overdue_email_day`). "Enviar recordatorio" sends the same email by hand (`app.api.reminders.email_reminder`). The log does not say which of the two sent it |
| Statement sent | `message_log`, `template = 'statement'`, `payload.billing_period_id` | 7 days before the due date (`app.jobs.statements`) |
| WhatsApp payment reminder opened | `message_log`: `channel = 'whatsapp'`, `template IN ('payment_due_today', 'payment_overdue', 'proof_rejected_followup')`, `payload.billing_period_id`, `payload.ordinal`, `payload.days_overdue` | Written when an admin **opens** the `wa.me` link (`app.api.reminders.remind`). Rakin never learns whether the message was sent or read (migration 0024). The WhatsApp template `payment_overdue` has the same name as the email template, so `channel` tells them apart |
| Inactive nudge opened | `message_log`: `channel = 'whatsapp'`, `template = 'inactive_nudge'`, `payload.about` (the member), `payload.days_absent` | The same "opened" meaning (`app.api.inactive.nudge`). The list holds only people away 14 days or more |
| Payment | `ledger_entry`: `kind = 'payment'`, `status = 'validated'`, `billing_period_id`, `method`, `claimed_by` / `claimed_at` (a proof the member uploaded), `created_at`, `validated_at` | A proof the member uploaded has `claimed_by` set, by `transfer` (migration 0012). A payment staff record has no claim |
| Period due | `billing_period.due_date`, `amount_due_clp` | What is still owed is settled by `app.domain.billing.SETTLING_KINDS` |
| Attendance | `attendance` joined to `session.starts_at` | One row per membership per class (migration 0023) |
| Proof review time | `ledger_entry.claimed_at` → `validated_at`, for both validated and rejected proofs | |
| Lapsed plan brought back | `membership.reactivated_at`, and `audit_event` `membership_reactivated` (migrations 0048, 0050) | |
| Trial converted | `membership.converted_from` (migration 0074) | |
| Month's income | `v_monthly_income` (migration 0014), shown in the ledger KPIs (`app.api.ledger.BOOK_KPIS`) | Grouped by the month a payment was validated in, in the gym's timezone |

### Payments after a reminder

**The trap in a time window.** #504 asks within how many days a payment should
count. With the nightly cadence (days 0, 1, 4, 7, 10, 13 for a grace of 15), no
overdue period with an email address goes more than 3 days without one. Any window
of 3 days or more therefore counts **every** late payment made during the grace.
Whether the window is 7 days or 14 makes no difference. The window is not what
needs deciding. What needs deciding is what to call the result.

**The rule.** A payment counts as *cobrado después de un recordatorio* when:

1. it is a validated `payment` on a billing period;
2. the period was already late when it was paid. "When it was paid" is the
   member's act: `claimed_at` for an uploaded proof, else `created_at` for a payment
   staff recorded. Both must be after `due_date`; the due date itself does not count;
3. at least one reminder about that period was sent after the due date and before
   the payment, by email (`status = 'sent'`) or by WhatsApp (link opened);
4. it is counted in the month it was validated in, as `v_monthly_income` counts it.
   So the figure is always a part of that month's income, and the page shows it
   that way.

It is split in two:

- **Sin mensaje del equipo**: every reminder before the payment was an email.
  Rakin did all of the work. Because the log does not say whether the job or the
  button sent an email, an email sent by hand counts here too. Either way nobody on
  the team had to write a message.
- **Después de un WhatsApp del equipo**: at least one WhatsApp reminder was opened
  before the payment. Rakin wrote the message, and a person sent it.

Due-today reminders (`payment_due_today`, the email on day 0) do not make a payment
count. A payment on the due date is on time.

**What it over-counts.** People who would have paid a few days late anyway. Many
gyms have regular late payers, so this is the biggest error, and nothing in the data
can measure it.

**What it under-counts.** Payments by members with no email and no WhatsApp
reminder. Reminders sent outside Rakin. Cash paid in time but recorded by staff days
later, which looks late. A proof uploaded within the grace but validated next month,
which counts in that next month.

**Comparisons we considered and rejected:**

- *The gym's own on-time rate before Rakin.* Rakin has no data from before a gym
  joined. An import (#209) brings memberships, not payment dates.
- *Late periods that got no reminder.* Those are members with no email and
  WhatsApp turned off, or that staff chose not to message. They are a different
  group of people, not a fair comparison.
- *A holdout: some late members deliberately get no reminder.* This is the only
  honest way to measure cause and effect. No gym would agree to stop chasing money
  it is owed, and it should not be asked to.

So the summary states the fact, uses the words *después de* and never *gracias a*,
and always shows the figure as part of the month's income.

### Members back after a WhatsApp

**The rule.** A nudge counts as *volvió* when the person it was about
(`payload.about`) attended a class (`session.starts_at` in the gym's timezone) within
**14 days** after the nudge's `sent_at`. 14 days is the inactive list's own first
bucket (`app.schemas.inactive.Bucket`). A person nudged twice in the month is
counted once, from the first nudge.

It is always shown as **N of M**: of the M people the team messaged this month, N
came to a class within 14 days.

A renewal does not count as coming back. A plan that keeps billing only proves the
person is still paying, which the payment figures already show.

**What it over-counts.** People who were coming back anyway, after a holiday or an
injury. It also counts a nudge whose link was opened but never sent, since "opened"
is all the log knows. Showing M next to N keeps this visible.

**What it under-counts.** People who came back after 14 days. People messaged
outside Rakin. People who came but were not marked present.

### Other facts that show value without new tracking

These are counts. None of them is attributed to Rakin, and the page does not
present them as if they were.

| Figure | How it is counted | Sample copy |
| --- | --- | --- |
| Automatic emails sent | `message_log` emails with `status = 'sent'` from `statement`, `payment_overdue` and `receipt` | "Rakin envió 112 avisos de cobro y recibos por ti" |
| Payments the members recorded themselves | validated payments with `claimed_by` set, out of all validated payments | "38 de 52 pagos los informaron los mismos alumnos, con su comprobante" |
| Proofs reviewed | validated or rejected proofs; the median time from `claimed_at` to `validated_at` | "Revisaste 38 comprobantes; la mitad en menos de 5 horas" |
| Plans reactivated | `membership.reactivated_at` in the month | "3 planes vencidos volvieron a activarse" |
| Trials converted | paid plans with `converted_from`, by `created_at` in the month | "4 de 9 clases de prueba pasaron a plan" |
| Debt at the end of the month | the sum over `v_overdue` at month close, for active memberships | Needs the snapshot (#506): `v_overdue` only knows today |

Rakin does not claim time saved ("te ahorramos 6 horas"). No figure in the data
supports a number of minutes.

### What is missing

- Whether a WhatsApp was sent or read. This cannot be known through `wa.me`, and
  should not be tried.
- Whether the job or the button sent an overdue email. A `payload.by` key (`job` or
  `staff`) would answer it, but the split above does not need it, so nothing is filed.
- Closed months that survive retention. #378 purges `message_log.to_address` and
  `payload` after an agreed period. #446 keeps `billing_period_id` and `about` in the
  plain payload, but the purge would still take them, and with them any way to
  recompute an old month. #506's snapshot keeps the numbers.

## 2. Email open rates: can we, and should we

**What Resend offers.** Open tracking puts a 1-pixel image in the HTML. Click
tracking rewrites every link to go through Resend's redirect domain. Both report
webhook events (`email.opened`, `email.clicked`) to the same endpoint the bounce and
complaint events use (`app.api.webhooks`). Both are switched on per sending domain,
not per email. So "on for some emails" would mean a second sending domain. (Check
this in Resend's dashboard before anyone builds against it: it is how the domain
settings work today.)

**What turning it on would change for every email:**

- **Click tracking passes every sign-in link through Resend.** Every notice about a
  membership carries one (`page_link` in `app.notices`), and so does the terms
  invitation that #499 depends on. The token would then pass through a third party
  and sit in its logs. That weakens step 2 of #500's identification chain ("a link
  or code was sent to that address, and was used ... once", [question 2 of
  #500](../legal-research.md#2-identification)). It is a non-starter for sign-in
  links, which leaves almost no email it could be used on.
- **Open tracking records, for each member, when they opened each email, from which
  IP and which mail client.** The time is stored with Resend, and in our database if
  we keep the events.

**Under Ley 21.719 and our own texts:**

- **It is personal data processing.** An open event is linked to a known address,
  and so to an identified person (Ley 19.628 art. 2 f, personal data). A per-person history of who opens
  payment reminders is, on the broad reading of [question
  2](../legal-research.md#2-profiling), automated evaluation of behaviour.
- **The contract is not a basis for it.** A reminder works the same whether or not
  anyone knows it was opened, so it is not "necesario para ... la ejecución de un
  contrato" (art. 13 c). Asking for consent is no answer either: consent collected
  as part of a contract that does not need it is presumed not freely given (art. 12,
  [question 6](../legal-research.md#6-legal-basis)). That leaves the gym's legitimate
  interest (art. 13 d), which the gym's privacy notice would have to name
  (art. 14 ter d), together with the profiling line (art. 14 ter l).
- **The Términos de encargo would change.** Anexo A's Resend row lists "nombre,
  correo, contenido del aviso". Opens add the time, IP and mail client. Changing what
  a subprocessor processes means 30 days' notice and a new authorisation from every
  gym (cláusula 9), and accepting a new version is the in-app act of cláusula 17.
  Clause 3 ("envía ... correos") would also need "y registra si se abren".
- **Rakin's own privacy notice** says its logs keep no IP addresses (#500, question
  2). Open events keep IPs, though of members rather than administrators.
- **#500's "Aceptación electrónica" research stands as it is**, as long as sign-in
  links are never click-tracked. With them tracked, step 2 of its chain gets weaker.

**How reliable opens are.** Apple Mail Privacy Protection loads every image when
mail arrives, for everyone who turned it on, so an Apple Mail user "opens"
everything. Gmail loads images through its own proxy, which hides the reader's IP
and device and caches the image, so a second open may not show. Most of a gym's members use one of the two. An
open rate would mostly measure which mail app people use.

**A better signal, with no pixel.** The sign-in link in each notice already records
`auth_link.used_at`. A `GET` on the link only shows a page with a button, and the
button's `POST` spends it (`app.magiclink.web`), so mail scanners cannot trigger it.
A used link therefore means a person tapped it. What is missing is which notice
issued the link: `auth_link` has `person_id` but no notice. Linking the two makes
"the overdue email's link was used" a fact recorded on Rakin's own server, under the
same rows sign-in already writes, with no third party involved. It under-counts:
anyone already signed in on the app has no reason to tap.

**Recommendation.** Open tracking **off**, click tracking **off**, for every email.
That needs no change to Anexo A, the notices or the Términos. If the team later
wants a measure of whether people engage with the emails, #508 counts uses of
the email's own link, per template and per month, and keeps only the counts.

## 3. Privacy and the message log

**Counts and timestamps only.** Every rule in section 1 reads rows that already
exist: `message_log` filtered by `template`, `channel`, `payload.billing_period_id`
and `payload.about`, joined to `ledger_entry`, `billing_period` and `attendance`. Those
are the plain reference keys #446 keeps outside the sealed payload. None of them
needs `to_address` or the sealed values. The current month is computed when the page
is asked for. A closed month is written once, as numbers only (#506):
`(gym_id, month, figure, value)`, with no `person_id`. So the summary keeps no
person-level history longer than the log already does, and outlives the log's purge
without keeping any people in it.

**Not profiling.** No person is labelled "pays after a reminder" or "comes back when
messaged". The page shows no list of names behind a figure. Whoever wants to know
who came back already has Alumnos and attendance, under the permissions those
screens have. That keeps the summary out of art. 2 w), even on the broad reading.

**Inside the processor contract.** Cláusula 3 already says the company "calcula
cobros, deudas y asistencia" for the gym. Totals of that gym's own data, shown to
that gym, are part of serving it (cláusula 1), and need no new version of the
Términos. **What is outside it:** the company using one gym's numbers, or a total
across gyms ("Rakin recuperó $40 millones este año"), for its own marketing. That is
a purpose of the company's own (art. 15 bis), and the gym's commercial information.
If the company wants such a figure, it asks each gym in writing first. It is not
part of any ticket here.

**Who sees it.** Owners and admins see it, as `money_read` (the `LedgerReadSession`
gate in `app.permissions`), because every payment figure is money. Club federado's
tesorero and president hold `money_read` too and see it as well. Coaches do not see
it, not even the "back after a WhatsApp" part, because the inactive list that part
comes from is also behind `money_read`. The monthly email goes to the titular only
(section 4).

## 4. The summary itself

**Both a page and an email.** The page is the record: in the app, beside the
ledger's KPIs, any month chosen. The email is the reminder that the page exists: on
the first day of each month, to the titular, with the past month's three or four
lines and a link to the page. It is not essential: the titular can turn it off in
Ajustes. Its content is the gym's name, the titular's name and totals, which
Anexo A's Resend row already covers.

**What it says.** The sentences come from the gym's vocabulary (`app.domain.vocabulary`,
#345), here "alumnos", "academia", "profe":

> **Noviembre en Academia Ejemplo**
>
> Rakin envió **64 recordatorios de pago**. Después de ellos llegaron **31 pagos
> atrasados, por $1.240.000**: el 18 % de lo cobrado en el mes. 23 llegaron sin que
> nadie del equipo escribiera.
>
> El equipo escribió por WhatsApp a **12 alumnos** que no venían hace más de 14 días.
> **5** volvieron a clases dentro de dos semanas.
>
> 38 de 52 pagos los informaron los mismos alumnos con su comprobante.

**Keeping it from looking inflated:**

- *Después de*, never *gracias a*, *recuperado* or *ganado*.
- Every money figure is shown as part of the month's income, and every person
  figure next to how many people it is out of.
- No percentage with fewer than 5 people or payments behind it: the page writes
  "1 de 3", not "33 %".
- A short "Cómo contamos esto" under the figures, in plain Spanish: the rule from
  section 1, including that some would have paid anyway.
- No trend arrows or "+40 % vs. octubre" until a gym has three full months. A
  partial first month says "desde el 12 de noviembre".

**A gym with nothing to show yet.** Each line appears only when its figure exists.
With no reminders yet: "Aún no se ha enviado ningún recordatorio este mes. Cuando
Rakin envíe uno, aquí verás lo que se pagó después." With the WhatsApp channel off,
the WhatsApp line is replaced by one sentence on turning it on in Ajustes. No email
goes out for a month with nothing in it.

**Any activity.** Nothing in the rules is specific to martial arts. Grades play no
part, and "clase" is the word the app already uses for every activity. The member,
place and coach words come from `Words`.

## 5. Build plan

Smallest useful first, each filed with its spec: #505 to #508.

1. **#505, the page, from the data there is.** `app.domain.value_summary`
   holds the rules of section 1, plus the SQL under `GET /api/summary?month=`,
   behind `money_read`. The page is in the app, beside the ledger. No migration.
   Tests cover each rule's edges: a payment on the due date, a reminder after the
   payment, a proof uploaded late but validated the next month, a second nudge, a
   gym with nothing yet.
2. **#506, keep closed months.** A migration adds `gym_month_figure`
   (`gym_id`, `month`, `figure`, `value`, `rules_version`, `computed_at`; RLS by gym,
   `money_read`), and a nightly job writes the past month on the 1st. The page then
   reads closed months from it, and adds the month-end debt figure. Must land before
   #378 purges `message_log.payload`. `rules_version` keeps a later change to a rule
   from silently rewriting old months.
3. **#507, the email to the titular.** A `monthly_summary` template, sent
   on the 1st after #506's job, to the titular only, non-essential (it has an
   unsubscribe), in the gym's vocabulary. Skipped for a month with nothing in it.
4. **#508 (later, optional), count the uses of each email's own link.** A migration adds
   `auth_link.message_id`, filled when `app.notices` issues a page link. #506's
   job counts the links used per template in the month, before #378's 30-day
   `auth_link` purge takes them. No pixel and no Resend tracking. Filed `later`.

Not filed: Resend open or click tracking (section 2, off), and a `payload.by` key
(section 1, not needed).
