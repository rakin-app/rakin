# Sport fit: does Rakin work for gyms beyond martial arts? (#336)

Spike, November 2026. No product code: this doc walks through Rakin as five kinds of gym
would use it, says what works, what is awkward and what is missing, lists the
martial-arts wording and logic that should be optional, and ranks the gaps. The build
tickets at the end carry out the ones a climbing gym and a rowing club need first.

Method: the stack in a worktree with `make seed`, plus two empty gyms made with
`app.gyms create --grading none` (a climbing gym and a rowing club), set up from Ajustes
in Chrome at 1280 and 390. A week of running them is judged from the code paths cited
below, read in full, and from `docs/product.md` and `docs/technical.md`.

## For the owner, in short

- **The money side already fits every gym.** Monthly fees, prepaid months, packs of N
  classes, trials, freezes, proofs of transfer, reminders to the guardian, Cobros extra
  split across a group (a regatta's fuel and fees, a seminar, gear) and the
  accountant's export do not care what the gym teaches.
- **Belts stay hidden when no activity grades.** A gym that picks "Escalada" or
  "Natación" without grades sees no belts on the ficha, the roster, Alumnos, Hoy or the
  student page. Two small leaks remain, both in the import (section 3).
- **Three things stop a climbing gym today.** A climber who walks in at 19:40 has no
  class to be marked in; a day pass can be priced but never sold; and there is nowhere
  to say that someone signed the waiver or passed the belay check, or when it expires.
- **Two things stop a rowing club today.** Club dues run per season with the same dates
  for everyone, which no plan can express; and the club is run by a board, which the
  #307 tickets (#308 to #322) already cover.
- **Every gym that is not martial arts reads a dojo's words.** Rakin calls the gym an
  "academia", its people "alumnos" and the coach "profe"; every new gym starts with a
  "Competición" program and "Sparring" and "Drilling" blocks, and the student page
  shows "Sparring en total" to a climber. A gym should say what it calls itself and its
  members, and sparring should be a module a gym turns on.
- **Fitness and yoga studios are not a near fit.** They live on booking a spot in a
  class with a capacity and a waitlist, which Rakin deliberately does not do before v3
  (`docs/product.md`, non-goals). Do not sell to one before that.
- **Kids' academies are close.** Guardians already pay and get the messages. They need
  the sibling discount to be settable (#25), one payment for several children (#66) and
  a term plan (the same ticket as the rowing club's season).
- **Recommended order:** wording and sparring first (they touch every new gym), then
  open-gym check-in, drop-ins and requirements for the climbing gym, then the season
  plan for the rowing club, alongside the board tickets already filed.

## What exists today

- **Plans** (`app.domain.membership.PlanKind`, `app.schemas.plans`): monthly (anchored
  on the signup day or the 1st), prepaid N months, a credits pack (N classes, expiry in
  days), drop-in and trial. Prepaid runs from each member's own start
  (`app.domain.billing`, around line 262). A **drop-in can be created but never sold**:
  `membership.create` raises "a drop-in is a single attendance, not a membership", Asignar
  plan leaves it out (`PlanStart.tsx`) and the import refuses it (`member_import/rows.py`).
  #130 owns that.
- **Discounts**: `membership.discount_pct` is applied to every period, but no endpoint or
  screen writes it; only the seed sets one. #25 owns that.
- **Cobros extra** (`app.api.extra_charges`, #195): one-off charges by category (rifa,
  seminario, equipamiento, gasto compartido, otro), a fixed amount each or a total split,
  to everyone active, a program, a saved group or hand-picked people (no membership
  needed). Paid at once or in 2 to 12 monthly instalments (#356), admin-created only.
- **Attendance** (`app.api.attendance`): a row is `(session_id, membership_id)`, so every
  mark needs a session and a membership that is active, trial, lapsed or frozen. Staff tap
  names on the roster; there is no self check-in. Sessions come from the weekly schedule
  (`app.domain.schedule`, 14 days ahead) or are started "now" (`app.api.sessions`). A
  credits pack is spent by the class type's `credit_cost` when someone is marked. The only
  walk-in path is a trial guest typed in on the roster.
- **Class types** have a `kind` of `class` or `open_mat` (0028); an open mat is one
  sparring block and does not count as a class by default. One coach per session, no
  space or location, no capacity or booking.
- **Groups** (`app.api.groups`) are saved lists of people for Cobros extra, not squads on
  a roster. **Programs** (adults, kids) are the only roster filter.
- **People**: one guardian per dependent per gym; every message about a dependent goes to
  the guardian (`app.contacts`). A proof pays one period or one cobro line. Custom fields
  are text, number, date or enum, optionally sensitive (encrypted) and role-limited;
  nothing reads them to warn or block. Files on a person: none (proofs and the logo
  only).
- **Grading** (`app.api.grading`, `app.api.grades`): one scheme per gym in
  `gym.settings.grading`, presets BJJ, judo, karate (generic, Shotokan, Kyokushin, Goju-ryu), taekwondo, kenpo,
  aikido, muay thai, levels and none. The gate is
  `gym_uses_grades()` (`app.api.activities`): any activity with "Usa grados". It is read
  in the frontend through `useGrades()`; the backend serves grades either way.
- **New gym** (`app.gyms create`): the gym, programs Adultos and Niños (#347), block
  kinds Calentamiento, Técnica, Drilling, Juegos, Sparring and Otro (0028's trigger), a
  graded activity only if `--grading` names one, and the owner. No plans, class types or
  fields. Activity presets in Ajustes (`frontend/src/api/activities.ts`): BJJ, Judo,
  Karate, Taekwondo, Kenpo, Aikido, Muay Thai (graded); Boxeo, MMA, Lucha, Ballet, Danza, Música, Piano,
  Escalada, Natación, Fútbol, Fuerza / CrossFit, Yoga; Otra.
- **Club officers** are designed in `expenses-and-officers.md` (#307) and not built:
  #308 to #322 are open.

## 1. Five kinds of gym, and their week

### Martial arts academy (the baseline)

1. Take attendance at each class from the weekly schedule. **Works.**
2. Chase who is overdue, validate transfers. **Works.**
3. Promote a student and see who is ready. **Works** (one scheme per gym; per activity is
   #251).
4. Sign up a family with two kids, one paying parent. **Awkward**: the guardian gets the
   messages, but pays each child's month with its own proof (#66), and the sibling
   discount cannot be set (#25).
5. A seminar or a tournament fee. **Works** as a Cobro extra.

### Climbing gym

1. **Check in walk-ins all day** (open hours, no class). **Missing.** The only route is an
   "open mat" class type with a slot of up to 24 hours: the roster is every member in the
   program, search and tap, with no arrival time, and the visit is written as sparring
   time ("Open mat … cuenta como sparring", `MatTime.tsx`). Hoy's "Sin asistencia" would
   flag every quiet day.
2. **Sell a day pass or a bono de 10.** The bono **works** as a credits pack, but only
   spent at a session (item 1). The day pass is **missing** (#130).
3. **Make sure nobody climbs without the induction, belay check and signed waiver.**
   **Missing.** A date custom field can hold "Inducción hecha el", but nothing shows it at
   the door or warns when it expires; no waiver text or signature is stored.
4. **Rent shoes and a harness.** **Awkward**: a Cobro extra per rental, made by an admin.
   Not core for the first climbing gym: most charge it at the counter with the entry.
5. **Run an 8-session intro course.** **Awkward**: a credits pack of 8 with an expiry, in
   its own program, works for someone who is only on the course; a member on a monthly
   plan cannot also hold the course in the screens (the ficha shows one live membership,
   `PersonPlan.tsx`; the roster takes one per person, `DISTINCT ON (m.person_id)` in
   `app.api.attendance`). The API allows two.

### Rowing club

1. **Bill the season's dues** (annual, or March to December, the same dates for every
   member). **Works** (#351): a fixed-period plan, "Período fijo", bills the same dates to
   every member; a late joiner owes the full price from their start, which an adjustment
   on the period lowers. "Duplicar para el próximo período" copies it for the next season
   and moves the members across.
2. **Charge a regatta's travel to the crew going.** **Works**: a Cobro extra split across
   a saved group or hand-picked people, paid at once or in instalments (#356).
3. **Keep the medical certificate and the swim test current.** **Missing**, as for the
   climbing gym's waiver.
4. **Run the club as a board** (presidente, tesorero, secretario). **Missing, filed**:
   #308 to #322.
5. **Take attendance at water and land sessions by squad.** **Works** with class types
   ("Agua", "Tierra") and a program per squad; one coach per session is enough for a club
   this size. A member who pays dues but does not row (a socio) is a plan with no program,
   and shows on every roster that admits any program: **awkward**, later.

Boats and club equipment: not core for the first club. They are tracked in a spreadsheet
by the boatman and Rakin does not need to own them.

### Fitness, CrossFit, functional and yoga studios

1. Sell class packs and drop-ins. Packs **work** (`credit_cost` per class type); drop-ins
   are **missing** (#130).
2. **Book a spot in a class with a capacity, a waitlist and late cancellation.**
   **Missing**, and a non-goal before v3 (`docs/product.md`). This is the studio's whole
   front door, and the reason studios are not a near fit.
3. Attendance, overdue and inactivity lists: **work**.

### Kids' sports academies (football, swimming, dance, gymnastics)

1. **Parents pay and get the messages.** **Works** (`app.contacts`: the guardian).
2. **Siblings with a family discount.** **Missing** in the screens (#25).
3. **One transfer for two children.** **Missing** (#66).
4. **Bill by term or school year.** **Works** (#351): the same fixed-period plan as the
   rowing club's season.
5. **A swimming or gymnastics level.** **Works** (#353): a scheme with no colours, from
   the "Niveles" preset, reads as levels: "Nivel" in the filters, niveles and subniveles
   with no belt in the editor.
6. **The end-of-year showcase or tournament.** **Works** as a Cobro extra plus an ad hoc
   session.

## 2. Gym type × area

| Area | Martial arts | Climbing | Rowing | Fitness / yoga | Kids academy |
|---|---|---|---|---|---|
| Plans and billing | works | awkward: no day pass (#130), packs only spent at a session | works | awkward: no drop-in | missing: sibling discount (#25) |
| Attendance | works | missing: open-gym check-in | works | missing: booking, capacity | works |
| Progression | works (per activity: #251) | not needed; levels awkward | not needed (categories are a custom field) | not needed | awkward: levels read as belts |
| Requirements before taking part | not needed | missing: waiver, induction, belay check | missing: medical certificate, swim test | not needed | awkward: medical certificate for some |
| People | awkward: one proof per child (#66) | works | missing: board (#308–#322); awkward: socios on rosters | works | awkward: one proof per child (#66) |
| Equipment and spaces | not needed | not core (rentals as Cobros extra) | not core (boats) | missing: spaces with capacity (v3) | not needed |
| Events | works (Cobros extra) | works | works | not needed | works |
| Wording | works | awkward | awkward | awkward | awkward |
| Onboarding from Ajustes | works after `app.gyms create` | awkward: dojo defaults | awkward: dojo defaults | awkward | awkward |

Self-serve sign-up of a gym (#184) is the same for every type: the PM still runs
`app.gyms create`. Everything after that can be set up from Ajustes.

## 3. Martial-arts wording and logic

### Wording

There is one locale, `frontend/src/i18n/es.ts`, and no per-gym vocabulary: every noun is
fixed in the copy and the email templates (`backend/app/notices/templates/`).

| Term | Where | Verdict |
|---|---|---|
| **alumno / alumnos / exalumno** (about 110 lines of `es.ts`) | nav "Alumnos", "Nuevo alumno", "Alumno desde", the ledger export's "Alumno" column (`ledger_export.py`), the welcome email, the import template's "Alumnos" tab and headers (`member_import/template.py`), the route `/admin/alumnos` | **a per-gym word**: alumno, socio, deportista or miembro |
| **academia** (27 lines; "gimnasio" in 37 others) | Hoy's "Configura tu academia", the join form, the privacy page ("un sistema de gestión para academias"), Ajustes' "RUT de la academia", the join-approved and freeze-rejected emails, the unsubscribe page | **a per-gym word**: academia, club, gimnasio or centro. Today the same gym is called both |
| **profe** (3 lines) | Hoy's "Admins y profes", the timer's "el profe divide la clase", the student's "cuando tu profe use el cronómetro" | **say "coach"**, the role's name everywhere else |
| **clase** | nav "Clases", the credits pack "Paquete de clases", "tu primera clase" (WhatsApp) | **fine** for any gym that runs sessions; open-gym check-in needs "visita" or "entrada" for its own screen |
| **Sparring**, **Drilling** | default block kinds for every gym (0028), "Sparring en total" on the ficha and the student page (`MatTime.tsx`, always shown) | **only when the gym spars** |
| **Open mat**, "rounds de sparring" | the class type's kind, the schedule, the timer, the student's training time | **only when the gym spars**; an open-gym check-in is a different thing (section 4) |
| **Competición**, **Kids** | default programs of every new gym (`gyms.py`, `seed/data.py`) | start with "Adultos" and "Niños" only |
| "Pasaje de guardia" | the tags' example (`es.ts` around line 1886) | a neutral example |
| **cinturón**, **franja**, "rayas" | the Alumnos and Grupos filter, the Graduación editor, the import's Grados notes | **only when grading is on** (the import too, since #352), and only while a rank has colours: a scheme with none says "Nivel" and "Subnivel" (#353) |
| **grado**, **graduación** | the ficha, Ajustes › Graduación, Importar | **only when grading is on**; fine words for levels |

No "tatami", "dojo", "kimono", "sensei" or "profesor" appears in the product's copy. The
grading presets' names (BJJ, judo, the karate styles, taekwondo, kenpo, aikido, muay thai) are seen only when chosen.

### Logic

- **Sparring is not a module.** Every gym gets a Sparring block kind (`is_sparring`) and
  Drilling; the "Open mat" class kind is always offered; "Sparring en total" always shows
  on the training-time card (`MatTime.tsx`, `MyMatTime` on `MeHome.tsx`), which also
  waits for "tu profe" to use the timer in a gym that never will. An admin can rename or
  archive the kinds; the labels stay.
- **Grading is gated in the screens and the import (#352).** The import template gets a
  Grados tab only when an activity grades (`gym_uses_grades`), whatever ranks the stored
  scheme keeps; the upload lists a sheet's Grados tab as ignored, with one line saying
  why, and the import writes no grade from it (`api/member_import.py`,
  `MemberImport.tsx`). `?belt=` on Alumnos is dropped while grading is off.
- **The gate is gym-wide.** A gym with BJJ and ballet shows the Graduación card to its
  ballet students. #251 (a scheme per activity) owns that.
- **Every change of rank is a "promotion".** Fine for climbing grades and swim levels; a
  rowing category by age is derived, not earned, and belongs in a custom field.

## 4. Gaps, ranked

Each gap is marked *needed before that type's first gym* or *later*. The ones for a
climbing gym and a rowing club come first.

| # | Gap | For | When | Ticket |
|---|---|---|---|---|
| 1 | What the gym calls itself and its members, in the screens | every type | needed before the climbing gym and the rowing club | #344 |
| 2 | The same words in emails, the export and the import template | every type | needed before the climbing gym and the rowing club | #345 |
| 3 | Sparring, open mat and Drilling only for a gym that spars | every type | needed before the climbing gym and the rowing club | #346 |
| 4 | New gyms start with Adultos and Niños, no Competición | every type | needed before the climbing gym and the rowing club | #347 |
| 5 | Open-gym check-in: a visit with no scheduled class, spending a pack | climbing | needed before the climbing gym | #348 |
| 6 | Day pass and drop-in sold at the door | climbing, fitness | needed before the climbing gym | #130 |
| 7 | Requirements to train (waiver, induction, medical certificate, swim test) with their dates and expiry, on the ficha | climbing, rowing | needed before the climbing gym and the rowing club | #349 |
| 8 | Requirements shown where people are marked, and expiring ones on Hoy | climbing, rowing | needed before the climbing gym and the rowing club | #350 |
| 9 | A plan with fixed dates for everyone: season, year or term | rowing, kids | needed before the rowing club | #351 |
| 10 | Roles beyond owner, admin and coach; the board | rowing | needed before the rowing club | #308, #309, #310, #311 |
| 11 | Sibling and scholarship discount set from the ficha | kids, martial arts | needed before the first kids' academy | #25 |
| 12 | One payment for several children | kids, martial arts | needed before the first kids' academy | #66 |
| 13 | Grading off means off in the import, and `?belt=` | every non-grading type | later | #352 |
| 14 | Levels that are not belts: "Nivel" wording, no stripes | kids, climbing | later | #353 |
| 15 | A course beside a membership (two live plans in the screens) | climbing | later | #354 |
| 16 | An enrolment fee (matrícula) charged when a plan starts | kids, rowing | later | #355 |
| 17 | Instalments on a Cobro extra | rowing | later | #356 |
| 18 | The waiver signed on the phone, kept as a PDF | climbing | later (v2 in `technical.md`) | — |
| 19 | QR self check-in | climbing, fitness | later (v2 in `product.md`) | — |
| 20 | Booking, capacity and waitlists | fitness | later (v3 in `product.md`) | — |
| 21 | Trial → conversion count | every type | later | #27 |
| 22 | The board's later pieces (handover, officers on the student page, expenses) | rowing | later | #312, #314–#322 |

Equipment, boats and bookable spaces are not core for any type's first gym, and have no
ticket.

## 5. Notes for the build tickets

- **Words, not translations.** A gym picks from short lists: the place (academia, club,
  gimnasio, centro, escuela) and its people (alumnos, socios, deportistas, miembros), each
  with its singular and plural and grammatical gender. The copy takes them as values;
  routes and API names stay as they are. The default is today's words, so the pilot sees
  no change.
- **Sparring as a gym setting**, default on for a gym with a combat activity (BJJ, Judo,
  Karate, Taekwondo, Muay Thai, Boxeo, MMA, Lucha) and off otherwise. Off hides the
  Sparring total, the open-mat kind and its copy, and archives (never deletes) the
  Sparring and Drilling kinds; existing time is kept.
- **A check-in is an attendance at an open-access session of the day.** The class type
  gets a third kind, `open_access`, with no sparring block, counted as a visit. The first
  check-in of the day creates that day's session, so attendance keeps one shape, the
  pack keeps being spent by `credit_cost`, "Sin asistencia" leaves open-access sessions
  out, and inactivity keeps working. The screen is a search box with the day's arrivals
  under it, each with its time (`marked_at`).
- **Requirements are per gym, dated per person.** A requirement has a name, whether it
  expires (and after how many months) and who sees it; a person's record is a date done
  and an optional note. A sensitive one (a medical certificate) follows the custom
  fields' encryption and `visible_to`. The roster and the check-in show a warning, never
  a refusal: the coach decides who trains.
- **A fixed-period plan** is prepaid with a start and end date the gym sets (1 March to
  31 December), the same for every member. A member who joins later pays the full price
  unless staff change the amount on that period with an adjustment, as today; prorating
  is v2.

## Build tickets

Climbing gym and rowing club first, in this order: #344, #345, #346, #347, #348, #130,
#349, #350, #351, with #308 to #311 for the board. Then #25 and #66 for the first kids'
academy. Later: #352 to #356, #27.

- #344 Vocabulario del gimnasio: what the gym calls itself and its members, in the screens
- #345 Vocabulario en correos, exportación y plantilla (needs #344)
- #346 Sparring opcional: sparring, open mat and Drilling only for a gym that spars
- #347 Programas iniciales: new gyms start with Adultos and Niños
- #348 Acceso libre: check a member in at the door with no scheduled class
- #349 Requisitos para entrenar: waivers, inductions and certificates with their dates, on the ficha
- #350 Requisitos al marcar: a warning on the roster and the check-in, and what expires on Hoy (needs #349; the check-in part needs #348)
- #351 Plan de período fijo: a season, year or term with the same dates for every member
- #352 Grados apagados: the import and `?belt=` follow grading being off
- #353 Niveles: progressions that are not belts read as levels
- #354 Un curso además del plan: two live memberships in the ficha and the roster
- #355 Matrícula: an enrolment fee charged when a plan starts
- #356 Cuotas en cobros extra: a Cobro extra paid in instalments
