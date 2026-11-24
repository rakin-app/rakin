# Guiding a new gym's owner past the first-steps list (#566)

Spike, 23 November 2026. No product code. It answers #566's four questions from a walk
through a fresh gym (`app.gyms create`, empty, at 1280 and 390 wide, as a climbing gym
would set itself up), the code as it stands at `8b76f21`, and UX QA run 3 on #341. The
build tickets are #573 to #577 ([section 5](#5-build-plan)).

## For the owner, in short

- **The list sends the owner to the right screens, but in an order that doesn't work.**
  Plans come before programs, Equipo comes last though Horario needs a coach, and
  **Horario isn't on the list at all**. So a gym can tick "Programas y clases" and still
  have an empty Clases screen that never says why.
- **No tour.** A tour breaks every time a screen changes, covers half a phone screen,
  and is hard to follow with a screen reader. Rakin's screens change every week.
- **The recommendation is a mix of two things.** First, a better first-steps list: each
  step says what "listo" means and what comes next, in an order that works. Second,
  help on the screens themselves: one line in each empty state, and a closed
  "¿Qué es esto?" beside the four hard choices (kind of plan, program, kind of class,
  role).
- **The help needs almost no "hide" button.** An empty state goes away once there is
  data, and a closed "¿Qué es esto?" takes one line. Only the first-steps list can be
  hidden, and it can be opened again from Ajustes.
- **Ticket 1 is small: copy and one screen (Hoy).** It can ship before the beta gyms
  start.
- **One question is still for you:** what the two beta gyms ask while they set up
  ([section 6](#6-questions-for-the-owner)). Their answers decide whether how-to pages
  are worth making, and the copy in section 3 should be checked against their words.

## 1. Where new owners get stuck

This is a walk through every step of "Configura tu academia" on a gym fresh from
`app.gyms create`. Before the list, the owner passes Términos (#570 covers that
screen). The gym starts with the **Academia** role template (Administrador, Coach) and
two programs, **Adultos** and **Niños** (`app.gyms.PROGRAMS`, #347).

### The list itself (Hoy)

| # | What happens | Why it stalls a new owner |
|---|---|---|
| L1 | The steps are: actividades, datos y cuenta, planes, programas y clases, alumnos, equipo | **Horario is missing.** A class type is not a class. Clases stays "Sin clases" all week until a weekly class exists, and neither Hoy nor Clases says so |
| L2 | "Programas y clases" is ticked as soon as one class type exists (`Today.tsx`, `hasClasses`) | The tick says the classes are done when none will ever appear in Clases |
| L3 | Planes is step 3, Programas step 4 | A plan has a **Programa** field. The programs already exist (Adultos, Niños), but nothing has explained what a program is by the time the owner picks one |
| L4 | Equipo is the last step | Horario's **Coach** select lists only the team. A gym whose coaches aren't invited can't name them on its schedule |
| L5 | "Invita a tu equipo" is ticked once anyone is invited | A gym where the owner teaches alone can never reach "6 de 6". Nothing says the step is optional |
| L6 | "Elegir actividades" links to `#actividades` | The page opens at the top, on Perfil, and Actividades is below the fold |
| L7 | Steps 1 and 2 go to the same screen, under different link text ("Elegir actividades", "Ir a Ajustes") | It reads as two places |
| L8 | On a phone, ticked steps keep their full height with their links | With four done, the next pending step is below the fold. The list doesn't point at "next" |
| L9 | The list goes away for good once the gym has a member and a class type, remembered in `localStorage` (`setupDoneKey`) | It can't be found again, and a second device shows it again. The other steps (plans, bank account, team) may still be undone when it goes |

### Ajustes › Academia (activities, vocabulary, grades)

| # | What happens | Why it stalls |
|---|---|---|
| A1 | Adding the first activity **saves new words for the whole app**. "Escalada" switched the gym to gimnasio, socios and instructor (`app.domain.vocabulary`) | The only feedback is "Escalada agregada.". The vocabulary selects that changed are above the fold, and the menu now says "Socios". It feels like something broke |
| A2 | The words come before the activities on the page, though the activity is what sets them | The order asks the owner to decide something the next card will overwrite |
| A3 | "Usa grados (cinturones, niveles)" decides whether **Graduación** appears in Ajustes at all | Nothing says that a section appears, or where |
| A4 | Privacidad asks again for the razón social and RUT just typed in Términos | Duplicate work. The join link refuses to start until it's done (Inscripción says so and links there, which helps) |
| A5 | The bank account is one card on a long form with one Guardar | Fine on a desktop (Guardar stays in view). On a phone it's the bottom of a long page |

### Ajustes › Planes

| # | What happens | Why it stalls |
|---|---|---|
| P1 | Six kinds in one select: Mensual, Prepago, Período fijo, Paquete de clases, Clase suelta, Prueba | Their names don't say when to use each. "Prepago" and "Período fijo" both mean paying ahead |
| P2 | **Programa** defaults to "Cualquier programa" | Two plans at once (#354) are allowed **only in different programs** (`LIVE_PLAN` in `app.api.memberships`). A plan left on "Cualquier programa" rules out any second plan. The form never says so. The refusal comes later, on the ficha |
| P3 | "Clase suelta" can be created here but is sold on a class's roster ("Agregar visitante", #130) | Nothing here says where it is used |
| P4 | Empty state: "Todavía no hay planes. Crea el primero para inscribir alumnos." | Says nothing about which kind to start with |

### Ajustes › Programas y clases, and Horario

| # | What happens | Why it stalls |
|---|---|---|
| C1 | "Clase" means three things: a class type ("Nueva clase", "Nombre de la clase"), a weekly class in Horario ("Nueva clase fija"), and a dated class in Clases | The owner can't tell whether "Nueva clase" puts something on the calendar. It doesn't |
| C2 | The kind help reads "Escalada libre: solo rounds de escalada libre, sin bloques de técnica" | "Rounds" and "técnica" are dojo words (`kindHint`). For a climbing gym it says nothing. And "Escalada libre" vs "Acceso libre" is the climbing gym's main choice, unexplained |
| C3 | Actividad defaults to "Ninguna" with one activity in the gym | An extra choice with an obvious answer |
| C4 | "Clases que descuenta" is asked of every class type | It matters only with a paquete de clases, which most gyms haven't made yet |
| C5 | Horario's coach select is labelled "Coach", and its topic hint says "el coach" | Hardcoded, not the gym's word ("instructor" here) |
| C6 | An "Acceso libre" type needs no Horario (Entrada makes the day's class at the first check-in, `app.api.check_in`), and Horario refuses one | Nothing says so. A climbing gym looks for a schedule it doesn't need |
| C7 | Clases' empty week says "Sin clases." seven times | No pointer to Horario for someone who can set it up |
| C8 | Every gym starts with **Niños**, and a program can't be deleted | Wrong for a federation or an adults-only gym. It can be deactivated, but nothing says so |

### Ajustes › Equipo

| # | What happens | Why it stalls |
|---|---|---|
| E1 | "¿Cómo se organiza tu equipo?" offers the templates while the Academia template's roles **already exist** below it | "Usar Academia" looks like it would add roles that are already there. Picking Club federado looks like it replaces them, but it adds |
| E2 | The invite form lists roles as bare checkboxes ("Administrador", "Coach") | What each role sees is only in the Cargos table further down, as permission names. Nothing says a coach never sees money or Ajustes |
| E3 | The template's role is "Coach" whatever the gym calls its coaches | Can be renamed in Cargos, but nothing says so |
| E4 | After the invite, the person's row looks like everyone else's | **No "hasn't signed in yet" state**, and no way to resend. Inviting again says "Esa persona ya está en el equipo." |
| E5 | The invited coach **can** be picked in Horario before they sign in (checked) | Good, but nothing says so, and that's what lets an owner build the schedule on day one |

### Phone (390)

There's no sideways scroll on any screen walked. The steps are tall (about 200px each),
so L8 matters most here. The forms read well, and their help lines are already in
`aria-describedby`.

### From UX QA run 3 (#341)

The new owner's first screen is Términos, and run 3 found it looks unfinished on a
phone (#570). Its other findings are about money screens a new gym doesn't see yet.
None of them overlaps this list.

## 2. Which kind of guidance fits Rakin

| | Guided tour | Contextual help | Richer first steps | How-to pages or videos |
|---|---|---|---|---|
| Phone | Poor: an overlay over half a 390 screen, arrows to things that scroll away | Good: one line in the flow | Good: it is Hoy | Leaves the app. Videos are heavy on mobile data |
| Screen reader | Poor: focus traps, "step 3 of 7" over a page that isn't read | Good: text in the page, a native disclosure | Good: already a list with "(listo)" / "(pendiente)" | Fine if written as text, poor as video |
| Gym's vocabulary | Possible, but each step is copy to keep in sync | Uses the `w.*` words like every string | Same | Each page would need writing once per vocabulary, or neutral words |
| As screens change | **Breaks on every change** of layout or selector | Lives in the screen's own component and changes with it | Lives in Hoy, changes when a step changes | Goes stale silently |
| Cost | A library or a homegrown overlay, plus upkeep | Copy plus one small disclosure component | Copy plus Hoy | Writing and hosting, plus upkeep |

**Recommendation: richer first steps plus contextual help. No tour.** How-to pages wait
for the beta gyms' answers (section 6). If they're asked for, they belong on rakin.app
as text with screenshots, linked from a "¿Qué es esto?", not as videos.

Contextual help takes three forms, and only these three:

1. **An empty state that says what goes here and what to do first.** It goes away by
   itself once there is data.
2. **A hint line under a field**, as the forms already have. Where one exists, fix it
   rather than add another.
3. **A "¿Qué es esto?" disclosure** (a native `<details>`) beside a choice that needs
   more than one line: kind of plan, program, kind of class, role. Closed by default. It
   is the `Disclosure` component #570 asks for, so this work and #570 share it.

## 3. What to explain, screen by screen

The copy is in Spanish, written in the default words. Words in braces follow the gym's
vocabulary (`w.*` in `frontend/src/i18n/es.ts`): {lugar} is academia, club or gimnasio,
{alumnos} is alumnos or socios, and {profe} is profe, coach or instructor. A string
that changes an existing one names its key.

### 3.1 Hoy: "Configura tu {lugar}"

The new order. Each step has a title, a line on what it is for, and, once done, a
line on what comes next:

| # | Step | Done when | Hint (pending) | Done line |
|---|---|---|---|---|
| 1 | Qué enseña tu {lugar} | ≥ 1 activity | Tus actividades, y si usan grados. Con la primera elegimos las palabras de la app. | Listo. Revisa las palabras en Ajustes › {Lugar} si no te calzan. |
| 2 | Cuenta bancaria | bank account saved | Dónde te transfieren tus {alumnos}. Aparece en su página al pagar. | Listo. |
| 3 | Programas y tipos de clase | ≥ 1 active class type | Un programa agrupa clases y planes: Adultos, Niños, Competencia. Dentro, los tipos de clase que das. | Listo. Ahora pon esas clases en el horario. |
| 4 | Invita a tu equipo *(opcional)* | ≥ 1 other person on the team | Tus {profes} y admins. Puedes ponerlos en el horario antes de que entren. Si enseñas solo, sáltate este paso. | Invitación enviada. Le llega un link por correo. |
| 5 | Horario | ≥ 1 weekly class, **or** an active "Acceso libre" type | Las clases de cada semana: día, hora y {profe}. Sin horario, Clases queda vacío. | Listo. Tus clases ya están en Clases. |
| 6 | Planes | ≥ 1 active plan | Lo que pagan tus {alumnos}. ¿No sabes cuál? Ajustes › Planes explica cada tipo. | Listo. |
| 7 | Agrega {alumnos} | ≥ 1 member | A mano, desde una planilla o con el link de inscripción, que llenan ellos. | Listo. |

- Step 5 with only "Acceso libre" types reads "No necesitas horario: las visitas se
  marcan en Entrada." and is ticked.
- **The next pending step is marked**: its title has "Siguiente" beside it, and it is
  the only one with its links shown as buttons. **Done steps collapse** to their title
  and tick on a phone (a row of about 48px, the link still there as the row).
- The link from step 1 opens Ajustes › {Lugar} **scrolled to Actividades** (fix the
  `#actividades` hash).
- The title stays "Configura tu {lugar}", and the progress stays "4 de 7 listos". The
  optional step counts only when done: "4 de 6 listos" for a gym that skipped it.
- A **"Ocultar"** button at the card's end hides it, asking first: "¿Ocultar los primeros
  pasos? Los encuentras en Ajustes › Cuenta.". It also hides by itself, as today, once
  steps 3, 6 and 7 are done.
- Ajustes › Cuenta gets **"Ver primeros pasos"**, which shows the card on Hoy again.

### 3.2 Clases, empty

For someone with `gym_setup`, the empty week shows this once, above the week, instead
of seven "Sin clases.":

> **Todavía no hay clases en el horario.** Las clases de cada semana se crean en
> Ajustes › Horario, y aparecen aquí dos semanas antes. [Ir al horario]

For a coach: "Todavía no hay clases esta semana." with no link.

### 3.3 Ajustes › {Lugar} (activities, vocabulary, grades)

- **Actividades comes first**, before Perfil's words. Its hint (`activities.hint`):
  > Lo que enseña tu {lugar}: una o varias. Con la primera elegimos las palabras de la
  > app, que cambias abajo. Si una actividad usa grados (cinturones, niveles), aparece
  > la sección Graduación.
- **After the first activity is added**, the status line says what changed:
  > Escalada agregada. La app ahora dice «gimnasio», «socios» e «instructor». Cámbialo
  > en Palabras de la app.
- After "Usa grados" is turned on: "Escalada usa grados. Configúralos en Ajustes ›
  Graduación." with a link.
- The words card is titled **"Palabras de la app"**, with the existing hint.
- **Privacidad starts filled in** with the razón social and RUT from the Términos the
  owner accepted (the backend has them on the acceptance), still editable. Its hint
  gets: "Los tomamos de los términos que aceptaste."

### 3.4 Ajustes › Planes

Empty state (`plans.empty`):

> **Todavía no hay planes.** La mayoría de los {lugares} parte con un plan Mensual y una
> Prueba. Crea el primero para inscribir {alumnos}.

**"¿Qué tipo de plan?"** beside the Tipo de plan select. One line per kind:

> - **Mensual**: se cobra cada mes, el día que la persona empezó o el día 1. Lo más común.
> - **Prepago**: varios meses pagados de una vez (3, 6, 12), desde el día que empieza
>   cada persona.
> - **Período fijo**: las mismas fechas para todos, como una temporada, un semestre o un
>   año. Quien entra tarde paga el precio completo.
> - **Paquete de clases**: un número de clases que se descuentan al marcar asistencia, y
>   vencen a los días que digas. Sirve para bonos de 10 o un curso de 8 clases.
> - **Clase suelta**: una visita, pagada una vez. Se vende desde la lista de una clase,
>   con «Agregar visitante».
> - **Prueba**: gratis, por unas clases, unos días o lo que se cumpla primero. Después
>   la conviertes en un plan pagado.

**"¿Qué es el programa?"** beside the Programa select:

> El programa dice a qué clases da acceso el plan. «Cualquier programa» abre todas.
> **Una persona puede tener dos planes a la vez solo si son de programas distintos**:
> por ejemplo, un plan Mensual de Adultos y un curso de Competencia. Si vas a vender
> algo además del plan de siempre, crea un programa para eso.

Its field hint (new): "Cualquier programa: no permite un segundo plan al mismo tiempo."

### 3.5 Ajustes › Programas y clases

Section line (`descriptions.programs`): "Cómo se agrupan tus clases y tus planes."

Head line, above the programs:

> Un **programa** agrupa clases y planes (Adultos, Niños, Competencia). Dentro de cada
> uno van sus **tipos de clase**: lo que das, sin día ni hora. El día y la hora van en
> **Horario**.

- "Nueva clase" becomes **"Nuevo tipo de clase"**. "Nombre de la clase" becomes "Nombre",
  and "Este programa todavía no tiene clases." becomes "Este programa todavía no tiene
  tipos de clase.". This resolves C1 on this screen. Horario's "clase fija" stays: it
  is the one that puts classes on the calendar.
- After a type is created (`classTypeCreated`): "Tipo de clase Escalada guiada creado.
  Ponlo en el horario para que aparezca en Clases. [Ir al horario]". For an "Acceso
  libre" type: "… Las visitas se marcan en Entrada."
- **"¿Qué tipo elijo?"** beside Tipo, replacing `kindHint`'s dojo wording:
  > - **Clase**: tiene día, hora y {profe}. Se pone en el horario.
  > - **{Práctica libre}**: como una clase, con día y hora, pero sin una parte guiada.
  >   No cuenta como clase, salvo que lo marques.
  > - **Acceso libre**: sin horario. La persona llega cuando quiere y se marca en
  >   Entrada. Para un muro de escalada o una sala abierta todo el día.

  `{Práctica libre}` is `w.OpenMat`, the gym's own name for it.
- **Actividad** defaults to the gym's only activity when it has one.
- **"Clases que descuenta"** shows only once the gym has a Paquete de clases plan.
  Otherwise it is 1, unseen.
- The program card's deactivate button says what it does when there are no plans or
  classes in it: "¿No usas Niños? Desactívalo: deja de aparecer al crear planes y
  clases."

### 3.6 Ajustes › Horario

- Head line (`schedule.intro`): "Las clases de cada semana, con día, hora y {profe}.
  Rakin las crea con dos semanas de anticipación en Clases. Los tipos de clase de
  Acceso libre no van aquí: se marcan en Entrada."
- The coach select's label is the gym's word: "{Profe}" (`form.coach`), and the topic
  and tags hints say "el {profe}".
- Under the coach select: "Tu equipo, incluso quienes todavía no entran. ¿Falta alguien?
  Invítalo en Equipo." with a link.
- Empty state, with no class types yet (replaces `form.noClassTypes`): "Primero crea un
  tipo de clase en Programas y clases." with a link.

### 3.7 Ajustes › Equipo, roles and permissions (#308)

- Head line (`staff.intro`): "Quién está en el equipo y qué puede hacer. Cada persona
  entra con su correo, sin contraseña."
- **The template question shows only while the gym has no roles.** A gym made by
  `app.gyms create` already has the Academia template, so it never sees the question.
  "Agregar plantilla" in Cargos stays for adding the club's roles.
- **The invite form's roles each say what that person sees**, under the checkbox, built
  from the role's permissions:
  > - **Administrador**: todo menos los gastos: {alumnos}, pagos, clases y ajustes.
  > - **Coach**: Hoy, las clases y su asistencia, y la lista de {alumnos} sin montos;
  >   puede agregar {alumnos} sin plan. No ve pagos ni ajustes.

  For any role, the line is the permissions' short help joined. With none: "Aparece
  en el equipo, sin acceso a nada más."
- Cargos gets a head line: "Un cargo es un conjunto de permisos. Renómbralos como los
  llamen en tu {lugar}: Coach puede ser «Instructor» o «Sensei»."
- **An invite not yet accepted**: the row says **"Invitación enviada · todavía no
  entra"** until the person has signed in to this gym once (an `auth_session` row for
  the person and gym). The row's panel gets **"Reenviar invitación"**, which sends the
  same sign-in email again, with the status "Le reenviamos el link a {email}.".
- After an invite (`invited`): "Invitamos a Tomás. Le llegará un link a {email}. Ya
  puedes ponerlo en el horario."

### 3.8 Seen once, then out of the way (#566 question 4)

| Guidance | How it goes away | Remembered | Found again |
|---|---|---|---|
| First-steps card | Its required steps are done, or "Ocultar" | Per person per gym, in the browser, as today (`setupDoneKey`). A second device shows it once more until the gym is set up there too, which is acceptable for a list that is useful when shown | Ajustes › Cuenta › "Ver primeros pasos" |
| Empty-state lines | Data arrives | Nothing to remember | They come back if the data goes (a plan deactivated) |
| "¿Qué es esto?" | Closed by default. The person closes it | Nothing: it opens closed every time | It is always there, one line |
| Hint lines | Never | — | — |

No server-side "dismissed" table. Nothing here is worth a migration: the only thing
that hides is a card that already hides once its work is done.

## 4. What is deliberately left out

- **A tour, and any overlay that points at elements.**
- **Videos.**
- **Changing the template roles' names to the gym's vocabulary** when the gym is
  created. The roles exist before an activity is chosen. Cargos' new head line says
  how to rename them.
- **Deleting a program.** Deactivating it is enough once it's explained.
- **Términos' layout**, which is #570's.
- **Sign-up and the trial** (#184, #565).

## 5. Build plan

In order. The first is copy and Hoy only, small enough to ship before the beta gyms
start.

| # | Ticket | What | Size |
|---|---|---|---|
| 1 | #573 | Hoy's first steps: new order, Horario as a step, "Siguiente", done lines, done steps collapsed on a phone, Equipo optional, `#actividades` scroll, Ocultar and "Ver primeros pasos" | S: `Today.tsx`, `es.ts`, `AccountSettings.tsx` |
| 2 | #574 | Empty states and head lines: Clases' empty week, Planes, Programas y clases ("tipo de clase"), Horario (the gym's word for the coach, the team hint), Equipo's intro and invite message | S: copy, two links |
| 3 | #575 | "¿Qué es esto?": a `Disclosure` component (shared with #570), the plan kinds, the program and two plans at once, the class kinds without dojo words; Actividad defaulting to the only one; "Clases que descuenta" only with a pack | M |
| 4 | #576 | Equipo: template question only with no roles, each role says what it sees, "todavía no entra" and "Reenviar invitación", Cargos' rename line | M: backend (signed-in flag, resend), frontend |
| 5 | #577 | Ajustes › {Lugar}: Actividades first, the words change announced, Graduación pointed to, Privacidad filled in from the accepted Términos | M: backend (prefill), frontend |

## 6. Questions for the owner

#566 asks what the beta gyms ask during onboarding. This spike ran without them, so
these go to the owner before ticket 3's copy is final:

1. **What did the two beta gyms ask while setting up?** In particular, whether they
   got lost between programs, plans and Horario, or on roles.
2. **The federation's yearly fee plus a monthly class fee**: two plans in two programs,
   or a cobro extra for the yearly fee? Section 3.4's copy assumes two programs. If
   they use a cobro extra, Planes should say so.
3. **Would they read a how-to page on rakin.app?** If yes, a sixth ticket writes three
   pages (planes, equipo, horario), linked from the matching "¿Qué es esto?".
