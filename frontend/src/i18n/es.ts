/**
 * Every user-facing string in the SPA. Components read from here and never
 * inline copy (enforced by `react/jsx-no-literals` in eslint.config.js).
 * English, when it comes, is a second file with the same shape.
 */

import type { MembershipStatus } from '../api/people'
import { w } from './vocabulary'

// A word per membership status, where only some of them need one.
type Statuses = Partial<Record<MembershipStatus, string>>

const MONTHS = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
] as const

// Under a free-text note or reason: a gym may not keep health data, even with consent
// (art. 16 bis, #384).
const NO_HEALTH = 'Sin datos de salud: ni lesiones ni enfermedades.'

// Where someone stands on a requirement (#349), on the ficha and the student page.
const REQUIREMENT_STATES = {
  ok: 'Al día',
  expiring: 'Vence pronto',
  expired: 'Vencido',
  pending: 'Pendiente',
} as const

// A requirement someone is short on, where they are marked and on Hoy (#350), name first
// so the state need not agree with it: "Certificado médico: vencido".
const requirementFlag = (flag: { name: string; state: keyof typeof REQUIREMENT_STATES; expires_on: string | null }) =>
  `${flag.name}: ${
    flag.state === 'expiring' && flag.expires_on !== null
      ? `vence el ${es.common.longDay(flag.expires_on)}`
      : REQUIREMENT_STATES[flag.state].toLowerCase()
  }`

export const es = {
  app: {
    name: 'rakin',
  },
  nav: {
    label: 'Principal',
    today: 'Hoy',
    get students() {
      return w.Members
    },
    classes: 'Clases',
    payments: 'Pagos',
    // Money in and money out side by side (#316), for who holds «Ver gastos».
    finances: 'Finanzas',
    settings: 'Ajustes',
    // Their own student page, for staff who also train at the gym (#214).
    myPage: 'Mi página',
    // A coach's phone (#358): the top bar's menu with "Cerrar sesión".
    account: 'Cuenta',
    // The public uptime page (#519), in a new tab: every staff role, never a member.
    status: 'Estado del servicio',
    statusLine: 'Revisa aquí si Rakin está funcionando.',
    pendingBadge: (n: number) => (n === 1 ? '1 comprobante por revisar' : `${n} comprobantes por revisar`),
  },
  signIn: {
    title: 'Entrar a Rakin',
    // The browser tab: `Entrar · Academia Sur`, as the admin screens name theirs (#213).
    tab: 'Entrar',
    // On a gym's own address (meta.rakin.app): its name, Rakin above it.
    titleAt: (gym: string) => `Entrar a ${gym}`,
    intro: 'Escribe tu correo y te enviamos un link para entrar. No necesitas clave.',
    emailLabel: 'Correo',
    submit: 'Enviarme el link',
    sending: 'Enviando…',
    // The same whatever the address: it never says whether an account exists.
    sent: (email: string) =>
      `Si el correo ${email} está registrado, te llegará un link y un código para entrar. Vencen en 15 minutos y sirven una sola vez. Si no llega en un par de minutos, revisa spam o promociones.`,
    // The code that comes with the link (#276): the app on an iPhone's home screen never
    // opens a link from mail, so it is typed here instead.
    sentTitle: 'Te enviamos un link y un código',
    codeLabel: 'Código del correo',
    codeHint: 'Escríbelo aquí para entrar en esta ventana, o toca el link del correo.',
    codeSubmit: 'Entrar',
    codeChecking: 'Entrando…',
    codeInvalid: 'Ese código no es el del correo. Revísalo e inténtalo de nuevo.',
    codeExpired: 'Ese código venció. Pide otro y usa el más reciente.',
    codeTooMany: (minutes: number | null) =>
      minutes === null
        ? 'Demasiados intentos. Inténtalo de nuevo en unos minutos o toca el link del correo.'
        : `Demasiados intentos. Inténtalo de nuevo en ${minutes === 1 ? '1 minuto' : `${minutes} minutos`} o toca el link del correo.`,
    codeUnreachable: (gym: string) =>
      `Este correo no tiene acceso a ${gym}. Si entrenas ahí, pídele ${w.toThePlace} que lo registre.`,
    codeFailed: 'No pudimos entrar. Revisa tu conexión e inténtalo de nuevo.',
    resend: 'Enviar otro',
    resent: 'Te enviamos otro link y otro código. Usa el más reciente.',
    another: 'Usar otro correo',
    tooMany: (minutes: number | null) =>
      minutes === null
        ? 'Pediste varios links seguidos. Inténtalo de nuevo en unos minutos.'
        : `Pediste varios links seguidos. Inténtalo de nuevo en ${minutes === 1 ? '1 minuto' : `${minutes} minutos`}.`,
    invalid: 'Revisa el correo: no parece una dirección válida.',
    failed: 'No pudimos enviar el link. Revisa tu conexión e inténtalo de nuevo.',
    // Why they are here, when the session ended rather than never began (#212).
    expired: 'Tu sesión venció. Entra de nuevo para seguir.',
    // Signed in, but on no team and with no student page here (#418).
    noPanel: 'Este correo no tiene acceso al panel. Entra con el correo con que te registraron.',
  },
  signOut: {
    label: 'Cerrar sesión',
    working: 'Cerrando sesión…',
    failed: 'No pudimos cerrar la sesión. Inténtalo de nuevo.',
  },
  admin: {
    // The wa.me payment reminders on Hoy, the proof review and the ficha (#55).
    reminders: {
      // The button's own label, short so it never wraps (#358): "Aviso 2".
      next: (n: number) => `Aviso ${n}`,
      // `ordinal` is "1.er", "2.º": the reminder this one would be.
      write: (name: string, ordinal: string) => `Recordar por WhatsApp a ${name} (${ordinal} aviso)`,
      // A dependent's reminder goes to their guardian.
      writeFor: (contact: string, name: string, ordinal: string) =>
        `Recordar por WhatsApp a ${contact}, por ${name} (${ordinal} aviso)`,
      sent: (ordinal: string, when: string) => `${ordinal} aviso ${when}`,
      dueToday: (amount: string, plan: string) => `Vence hoy · ${amount} · ${plan}`,
      rejected: (note: string) => `Comprobante rechazado: ${note}`,
      // After rejecting a proof: the follow-up by WhatsApp beside the email.
      followUp: (name: string) => `Avisar por WhatsApp a ${name}`,
      // The overdue email (#260), sent now from the ficha, Hoy and Pagos.
      email: {
        send: 'Enviar recordatorio',
        sendTo: (name: string) => `Enviar recordatorio por correo a ${name}`,
        sendFor: (contact: string, name: string) => `Enviar recordatorio por correo a ${contact}, por ${name}`,
        sent: (name: string) => `Recordatorio enviado a ${name}.`,
        last: (when: string) => `Último recordatorio: ${when}`,
        // Beside the disabled button (#266): why it cannot send now.
        sentToday: 'Ya se envió hoy',
        noEmail: 'Sin correo',
        today: 'hoy',
        yesterday: 'ayer',
        daysAgo: (n: number) => `hace ${n} días`,
        refused: {
          emailed_today: 'Ya se envió un recordatorio hoy.',
          no_email: 'No tiene correo para enviarlo.',
        },
        failed: 'No pudimos enviar el recordatorio. Inténtalo de nuevo.',
      },
    },
    today: {
      title: 'Hoy',
      heading: (day: string) => `Hoy, ${day}`,
      countersLabel: 'Resumen',
      // Between the parts of a row's line, where one is set apart (the warning, #358).
      separator: ' · ',
      after: (parts: readonly string[]) => parts.map((part) => ` · ${part}`).join(''),
      loading: 'Cargando…',
      retry: 'Reintentar',
      // Without the role Hoy cannot tell what to show: say so instead of a blank page.
      roleError: 'No pudimos cargar tu acceso.',
      proofs: {
        title: 'Por validar',
        count: (n: number) => (n === 1 ? '1 comprobante' : `${n} comprobantes`),
        error: 'No pudimos cargar los comprobantes.',
        empty: 'No hay comprobantes por revisar.',
        // A guardian who sent the proof for a dependent.
        sentFor: (sender: string, person: string) => `${sender} (por ${person})`,
        detail: (amount: string, month: string) => `Transfirió ${amount} · ${month}`,
        review: 'Revisar',
        reviewLabel: (name: string) => `Revisar el comprobante de ${name}`,
      },
      overdue: {
        title: 'Vencidos',
        total: (amount: string) => `${amount} pendientes`,
        error: 'No pudimos cargar los vencidos.',
        empty: 'Nadie tiene pagos vencidos.',
        // The overdue fact, the one part of the row in the warning colour (#358); the
        // amount and the plan follow it.
        since: (days: number) => `Venció hace ${days === 1 ? '1 día' : `${days} días`}`,
        // A debt outlives its plan (#207): the row says what became of the membership.
        membership: { lapsed: 'plan caducado', cancelled: 'dado de baja', frozen: 'congelado' } as Statuses,
        // A member owing on several periods, of one plan or more: one row, the total (#271).
        periods: (n: number) => `${n} cobros vencidos`,
        paid: 'Pagó',
        paidLabel: (name: string) => `Registrar el pago de ${name}`,
        periodOf: (name: string, plan: string, month: string) => `${name}, ${plan} de ${month}`,
        method: 'Medio de pago',
        submit: (amount: string) => `Registrar ${amount}`,
        cancel: 'Cancelar',
        working: 'Guardando…',
        recorded: (name: string, amount: string) => `Pago registrado: ${name}, ${amount}.`,
        refused: {
          paid: 'Eso ya está pagado.',
          failed: 'No pudimos registrar el pago. Inténtalo de nuevo.',
        },
        showAll: (n: number) => `Ver los ${n} vencidos`,
      },
      // Minors with no guardian (#368): nothing reaches them until the gym adds one.
      missingGuardian: {
        title: 'Falta apoderado',
        count: (n: number) => (n === 1 ? '1 menor' : `${n} menores`),
        hint: 'Son menores de 18 años sin apoderado: Rakin no les escribe. Vincula a su apoderado desde la ficha de este, con «Agregar a alguien a cargo».',
        open: 'Ver ficha',
        openLabel: (name: string) => `Ver la ficha de ${name}`,
      },
      // "Requisitos" (#350): who lacks one or whose one expired, then whose one expires soon.
      requirements: {
        title: 'Requisitos',
        count: (n: number) => w.memberCount(n),
        hint: 'Pendientes o vencidos, y los que vencen en los próximos 30 días. Se registran en su ficha.',
        flag: requirementFlag,
        showAll: (n: number) => `Ver los ${n}`,
        open: 'Ver ficha',
        openLabel: (name: string) => `Ver la ficha de ${name}`,
      },
      // Due today, or a rejected proof to follow up: each a tap from its WhatsApp reminder.
      remind: {
        title: 'Por avisar',
        count: (n: number) => (n === 1 ? '1 pago' : `${n} pagos`),
      },
      inactive: {
        counter: 'Sin venir 14 d',
        title: 'A quién llamar',
        error: 'No pudimos cargar a quién llamar.',
        empty: 'Todos vinieron en las últimas dos semanas.',
        count: (n: number) => w.memberCount(n),
        // The five most recently away are on Hoy; the rest are in Alumnos.
        showAll: (n: number) => `Ver los ${n}`,
        absent: (days: number) => `${days} días sin venir`,
        never: (days: number) => `No ha venido desde que entró, hace ${days} días`,
        payment: {
          up_to_date: 'al día en pagos',
          trial: 'en prueba',
          overdue: (amount: string) => `debe ${amount}`,
        },
        nudged: (when: string) => `avisado ${when}`,
        write: (name: string) => `Escribir por WhatsApp a ${name}`,
        // A dependent's nudge goes to their guardian.
        writeFor: (contact: string, name: string) => `Escribir por WhatsApp a ${contact}, por ${name}`,
      },
      unmarked: {
        title: 'Sin asistencia',
        count: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
        error: 'No pudimos cargar las clases sin asistencia.',
        empty: 'Todas las clases de la semana tienen asistencia.',
        row: (when: string, classType: string) => `${when} · ${classType}`,
        detail: (program: string, coach: string) => `${program} · ${coach}`,
        take: 'Pasar lista',
        takeLabel: (name: string) => `Pasar lista de ${name}`,
      },
      // How the trials of the last `days` days went (#27).
      trials: {
        title: 'Pruebas',
        aside: (days: number) => `Últimos ${days} días`,
        converted: (converted: number, started: number) =>
          `${converted} de ${started} ${started === 1 ? 'prueba pasó' : 'pruebas pasaron'} a un plan`,
        running: (n: number) => (n === 1 ? '1 sigue en prueba' : `${n} siguen en prueba`),
      },
      // A coach's Hoy: today's classes, each a tap from its attendance.
      classes: {
        title: 'Clases de hoy',
        count: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
        error: 'No pudimos cargar las clases de hoy.',
        empty: 'No hay clases hoy.',
        create: 'Crear clase',
        present: (n: number) => (n === 0 ? 'sin asistencia' : n === 1 ? '1 presente' : `${n} presentes`),
        cancelled: 'cancelada',
        take: 'Tomar asistencia',
        takeLabel: (name: string) => `Tomar asistencia de ${name}`,
        // A cancelled class takes no attendance; its page is still where it is reactivated (#213).
        view: 'Ver clase',
        viewLabel: (name: string) => `Ver ${name}`,
      },
      // A new gym's first day: what to set up, each step a link to where it is done.
      setup: {
        get title() {
          return `Configura tu ${w.place}`
        },
        get error() {
          return `No pudimos revisar los primeros pasos de tu ${w.place}.`
        },
        progress: (done: number, total: number) => `${done} de ${total} listos`,
        // After a step's title, for a screen reader: the tick says it to the eye.
        state: (done: boolean) => (done ? ' (listo)' : ' (pendiente)'),
        steps: {
          activities: {
            get title() {
              return `Qué enseña tu ${w.place}`
            },
            hint: 'Una o varias actividades, y si usan grados.',
            link: 'Elegir actividades',
          },
          gym: {
            get title() {
              return `Datos ${w.ofThePlace} y cuenta bancaria`
            },
            get hint() {
              return `Dónde te transfieren tus ${w.members}.`
            },
            link: 'Ir a Ajustes',
          },
          plans: {
            title: 'Planes',
            get hint() {
              return `Qué pagan tus ${w.members} y cada cuánto.`
            },
            link: 'Crear planes',
          },
          classes: {
            title: 'Programas y clases',
            hint: 'Las clases que das, en cada programa.',
            link: 'Crear clases',
          },
          members: {
            get title() {
              return `Agrega ${w.members}`
            },
            hint: 'A mano, desde una planilla o con el link de inscripción.',
            manual: 'Agregar a mano',
            import: 'Importar planilla',
            joinLink: 'Link de inscripción',
          },
          staff: {
            title: 'Invita a tu equipo',
            get hint() {
              return `Admins y ${w.coaches}, cada uno con su acceso.`
            },
            link: 'Invitar',
          },
        },
      },
      ago: {
        now: 'recién',
        minutes: (n: number) => `hace ${n}\u00a0min`,
        hours: (n: number) => `hace ${n}\u00a0h`,
        yesterday: 'ayer',
      },
    },
    joinRequests: {
      title: (n: number) => `Solicitudes (${n})`,
      age: (years: number) => (years === 1 ? '1 año' : `${years} años`),
      guardian: (name: string) => `Apoderado: ${name}`,
      program: (name: string) => `Programa: ${name}`,
      sent: (day: string) => `Enviada el ${day}`,
      emailInGym: (name: string) => `Ya hay alguien sin RUT con este correo: ${name}`,
      noWhatsapp: 'Sin WhatsApp',
      rutInGym: (name: string) => `Ya hay alguien con este RUT: ${name}`,
      plan: 'Plan',
      noPlan: 'Sin plan',
      get planHint() {
        return `Sin plan, queda como ${w.member} sin plan y se lo asignas después.`
      },
      coachHint: 'Queda sin plan: el dueño o un admin se lo asigna.',
      approve: 'Aprobar',
      approveLabel: (name: string) => `Aprobar la solicitud de ${name}`,
      reject: 'Rechazar',
      rejectLabel: (name: string) => `Rechazar la solicitud de ${name}`,
      confirmReject: (name: string) => `¿Rechazar la solicitud de ${name}? Sus datos se borran.`,
      confirm: 'Sí, rechazar',
      cancel: 'Cancelar',
      working: 'Guardando…',
      approved: (name: string) => `${name} ya es ${w.member}.`,
      rejected: (name: string) => `Solicitud de ${name} rechazada.`,
      failed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
      get family() {
        return `Esta persona ya tiene otro apoderado en ${w.thePlace}, o su apoderado está a cargo de alguien más. Revísalo en su ficha.`
      },
      get hasMembership() {
        return `Ya es ${w.member} con un plan. Apruébala sin plan para unir la solicitud a su ficha.`
      },
      hasLeft: 'Fue dado de baja: reactívalo desde su ficha, o aprueba sin plan.',
      ignoredEmail: (email: string) => `Su ficha mantiene su correo; ${email} no se usará.`,
      oldestShown: (n: number) => `Mostrando las ${n} más antiguas.`,
    },
    // A freeze asked for from /me (#270), on Hoy and on the plan card of the ficha.
    freezeRequests: {
      title: (n: number) => `Solicitudes de congelamiento (${n})`,
      dates: (from: string, to: string) => `Del ${from}, vuelve el ${to}`,
      reason: (reason: string, note: string | null) => (note ? `${reason} · ${note}` : reason),
      askedBy: (name: string) => `La pidió ${name}`,
      onCard: 'Pide congelar su plan',
      approve: 'Aprobar',
      approveLabel: (name: string) => `Aprobar el congelamiento de ${name}`,
      reject: 'Rechazar',
      rejectLabel: (name: string) => `Rechazar el congelamiento de ${name}`,
      from: 'Desde',
      until: 'Vuelve el',
      datesHint: 'Puedes cambiar las fechas antes de aprobar. El próximo pago se corre esos días.',
      fromNeeded: 'Elige hoy o un día después.',
      untilNeeded: 'Elige el día en que vuelve (después de “Desde”).',
      confirmApprove: 'Aprobar y congelar',
      get note() {
        return `Nota para ${w.theMember} (opcional)`
      },
      confirmReject: 'Rechazar solicitud',
      cancel: 'Cancelar',
      working: 'Guardando…',
      approved: (name: string, day: string) => `Congelamiento de ${name} aprobado. Vuelve el ${day}.`,
      rejected: (name: string) => `Solicitud de ${name} rechazada.`,
      refused: 'No se puede congelar así: revisa que el plan siga activo, sin otra congelación, y las fechas.',
      failed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
    },
    // The belt filter of Alumnos and the group builder (#219), by the scheme's order.
    rankFilter: {
      orHigher: (label: string) => `${label} o superior`,
      ranks: 'Adultos',
      kids: 'Kids',
    },
    students: {
      get title() {
        return w.Members
      },
      get searchLabel() {
        return `Buscar ${w.member}`
      },
      // The list's column labels on a desktop, where each row is one line (#199).
      columns: {
        get name() {
          return w.Member
        },
        phone: 'Teléfono',
        rut: 'RUT',
        plan: 'Plan',
        status: 'Estado',
      },
      searchPlaceholder: 'Nombre, teléfono o RUT',
      filtersLabel: 'Filtros',
      // The button over plan, programa and cinturón (#358), and how many of them are set.
      moreFiltersLabel: (n: number) => (n === 0 ? 'Filtros' : n === 1 ? 'Filtros, 1 activo' : `Filtros, ${n} activos`),
      statusLabel: 'Estado',
      planLabel: 'Plan',
      allPlans: 'Todos los planes',
      inactivePlan: (name: string) => `${name} (inactivo)`,
      programLabel: 'Programa',
      allPrograms: 'Todos los programas',
      inactiveProgram: (name: string) => `${name} (programa inactivo)`,
      rankLabel: 'Cinturón',
      allRanks: 'Todos los cinturones',
      // A scheme with no colours is levels (#353): a swimming school's, a climbing gym's.
      levelLabel: 'Nivel',
      allLevels: 'Todos los niveles',
      clearFilters: 'Limpiar filtros',
      count: (n: number) => w.memberCount(n, n.toLocaleString('es-CL')),
      pickPlan: 'Elegir un plan…',
      noPlan: 'Sin plan: solo la persona',
      get empty() {
        return `Todavía no hay ${w.members}.`
      },
      get noMatches() {
        return `Ningún ${w.member} coincide con la búsqueda.`
      },
      get loading() {
        return `Cargando ${w.members}…`
      },
      get error() {
        return `No pudimos cargar ${w.theMembers}.`
      },
      retry: 'Reintentar',
      more: 'Ver más',
      status: {
        active: 'Activo',
        trial: 'Prueba',
        frozen: 'Congelado',
        // Not "Vencido", which is a payment past due (#193, #207): the plan itself ran out.
        lapsed: 'Caducado',
        cancelled: 'Cancelado',
      },
      guardianOf: (name: string) => `Apoderado: ${name}`,
      dependentsCount: (n: number) => (n === 1 ? '1 a cargo' : `${n} a cargo`),
      importLink: 'Importar planilla',
      get newLink() {
        return `${w.memberIs('Nuevo', 'Nueva')} ${w.member}`
      },
      // The filter for who has left the gym, and how each of them reads on it.
      left: 'Dados de baja',
      leftOn: (day: string) => `De baja desde el ${day}`,
      // No phone and "No tiene WhatsApp" unticked: the filter, and how a row says so.
      missingPhone: 'Falta teléfono',
      // No RUT and no email: found again only by name.
      missingRut: 'Falta RUT',
      // A minor with no guardian: nothing is sent to them until one is added (#368).
      missingGuardian: 'Falta apoderado',
      // Away 14 days or more: Hoy's "A quién llamar", in full.
      away: 'Sin venir 14 d',
      noWhatsapp: 'Sin WhatsApp',
      // On the row of someone who owes, overdue or due soon (#265): the ficha's
      // "Registrar pago", opened under the row; "Pagó", as Hoy says it (#358).
      pay: 'Pagó',
      payLabel: (name: string) => `Registrar pago de ${name}`,
    },
    newMember: {
      get title() {
        return `${w.memberIs('Nuevo', 'Nueva')} ${w.member}`
      },
      get eyebrow() {
        return w.Members
      },
      // At the top of the form (#294): today's form, or "Agregar exalumno".
      kindLabel: '¿Entrena aquí?',
      kind: { current: 'Entrena aquí', former: 'Ya no entrena aquí' },
      // "Ya no entrena aquí": someone who trained here before Rakin and already left.
      former: {
        intro:
          'Para tener en Rakin a quien ya dejó de entrenar: queda en "Dados de baja", sin plan, y Rakin nunca le escribe. Después puedes agregar su historial en su ficha.',
        phone: 'Teléfono (opcional)',
        phoneHint: 'Nadie le va a escribir: solo queda en su ficha.',
        get since() {
          return `${w.Member} desde (opcional)`
        },
        leftOn: 'Fecha de baja',
        get submit() {
          return `Guardar ${w.formerMember}`
        },
        needed: {
          leftOn: 'Elige un día de hoy hacia atrás, de los últimos 60 años.',
          since: 'Elige un día de los últimos 60 años, no después de la fecha de baja.',
        },
        refused: {
          invalid: 'Revisa los datos: el teléfono, el RUT, el correo o una fecha no son válidos.',
          get failed() {
            return `No pudimos guardar ${w.memberIs('al', 'a la')} ${w.formerMember}. Inténtalo de nuevo.`
          },
        },
      },
      firstName: 'Nombre',
      lastName: 'Apellido',
      phone: 'Teléfono (WhatsApp)',
      get phoneHint() {
        return `Celular chileno: +56 9 1234 5678. ${w.ThePlace} le escribe por WhatsApp.`
      },
      phoneHintMinor: 'Opcional: los avisos van al apoderado.',
      phoneOptional: 'Teléfono (opcional)',
      noWhatsapp: 'No tiene WhatsApp',
      email: 'Correo',
      rut: 'RUT',
      rutHint: 'El RUT o el correo identifica a la persona. Si no tiene RUT, basta el correo.',
      dob: 'Fecha de nacimiento (opcional)',
      guardianTitle: 'Apoderado',
      guardianMinor: 'Es menor de edad: necesita un apoderado que pague y reciba los avisos.',
      get guardianOptional() {
        return `Si alguien más paga por ${w.memberIs('este', 'esta')} ${w.member}, agrégalo como apoderado.`
      },
      guardianAdd: 'Agregar apoderado',
      guardianRemove: 'Quitar apoderado',
      get guardianExisting() {
        return `Ya está en ${w.thePlace}`
      },
      guardianNew: 'Es nuevo',
      guardianSearch: 'Buscar al apoderado',
      guardianPick: 'Elegir',
      guardianPickLabel: (name: string) => `Elegir a ${name} como apoderado`,
      guardianPicked: (name: string) => `Apoderado: ${name}`,
      guardianChange: 'Cambiar',
      guardianName: 'Nombre del apoderado',
      guardianRut: 'RUT del apoderado',
      guardianPhone: 'Teléfono del apoderado (WhatsApp)',
      guardianPhoneOptional: 'Teléfono del apoderado (opcional)',
      guardianEmail: 'Correo del apoderado',
      noMatches: 'Nadie coincide.',
      fieldsTitle: 'Otros datos',
      planTitle: 'Plan',
      plan: 'Plan (opcional)',
      noPlan: 'Sin plan por ahora',
      startedOn: 'Desde',
      welcome: 'Enviar el correo de bienvenida',
      welcomeHint: {
        plan: 'Le explica cómo pagar y subir el comprobante, y trae su link para entrar.',
        noPlan: 'Le llega su link para entrar a su página.',
        get noEmail() {
          return `Necesita un correo: escribe el ${w.ofTheMember}.`
        },
        noGuardianEmail: 'Necesita un correo: escribe el del apoderado, que es quien lo recibe.',
      },
      get submit() {
        return `Guardar ${w.member}`
      },
      working: 'Guardando…',
      cancel: 'Cancelar',
      needed: {
        firstName: 'Escribe el nombre.',
        identity: 'Escribe el RUT o el correo.',
        phone: 'Escribe un celular chileno, o marca "No tiene WhatsApp".',
        guardian: 'Un menor de edad necesita un apoderado.',
        guardianName: 'Escribe el nombre del apoderado.',
        guardianIdentity: 'Escribe el RUT o el correo del apoderado.',
        guardianPhone: 'Escribe el celular del apoderado, o marca "No tiene WhatsApp".',
        guardianPicked: 'Elige al apoderado, o agrega uno nuevo.',
        guardianUnreachable:
          'Ese apoderado no tiene teléfono. Agrégalo en su ficha, o marca ahí "No tiene WhatsApp".',
      },
      duplicate: {
        get rut_in_gym() {
          return `Ese RUT ya es de ${w.aMember} ${w.ofThePlace}.`
        },
        get email_in_gym() {
          return `Ese correo ya es de ${w.aMember} ${w.ofThePlace}.`
        },
        open: 'Abrir su ficha',
      },
      refused: {
        invalid: 'Revisa los datos: el teléfono, el RUT, el correo o una fecha no son válidos.',
        // When the API names the fields, each says why under itself, as the join form does (#211).
        fields: 'Revisa los campos marcados.',
        rut: 'RUT no válido: revisa el dígito verificador.',
        email: 'Correo no válido.',
        phone: 'Escribe un celular, como +56 9 1234 5678.',
        dob: 'Escribe una fecha pasada.',
        one_level: 'Ese apoderado está a cargo de otro apoderado: elige a otra persona.',
        get failed() {
          return `No pudimos guardar ${w.toTheMember}. Inténtalo de nuevo.`
        },
      },
    },
    import: {
      get title() {
        return `Importar ${w.members}`
      },
      get eyebrow() {
        return w.Members
      },
      get intro() {
        return `Sube la planilla ${w.ofThePlace} (CSV o Excel). Primero revisamos cada fila sin guardar nada; después importas. Puedes volver a importarla: a quien ya está lo encontramos por su RUT (o su correo, o su nombre si no tiene ninguno) y no se duplica.`
      },
      get templateHint() {
        return `¿Empiezas de cero, o traes ${w.members} antiguos, ${w.formerMembers}, sus pagos y sus grados? Usa la plantilla de Rakin.`
      },
      csvTab: 'Si es un CSV, ¿qué contiene?',
      tabs: {
        get alumnos() {
          return w.Members
        },
        pagos: 'Pagos',
        grados: 'Grados',
      },
      template: 'Descargar plantilla',
      fileLabel: 'Planilla',
      choose: 'Elegir archivo',
      reading: 'Leyendo la planilla…',
      tooLarge: 'El archivo pesa más de 5 MB.',
      refused: {
        unreadable: 'No pudimos leer el archivo. Guárdalo como CSV o Excel (.xlsx) e inténtalo de nuevo.',
        empty: 'La planilla no tiene filas con datos.',
        get too_many_rows() {
          return `La planilla tiene demasiadas filas (el máximo es 2.000 en ${w.Members} y en Grados, y 20.000 en Pagos).`
        },
        too_many_empty_rows:
          'La planilla sigue con miles de filas vacías después de los datos. Copia los datos a una hoja nueva e inténtalo de nuevo.',
        too_large: 'El archivo pesa más de 5 MB.',
        failed: 'No pudimos procesar la planilla. Inténtalo de nuevo.',
      },
      // The members' tab's rows, and each other tab the workbook has.
      fileSummary: (name: string, rows: number, others: { tab: string; rows: number }[]) => {
        const count = (n: number) => (n === 1 ? '1 fila' : `${n.toLocaleString('es-CL')} filas`)
        if (others.length === 0) return `${name}: ${count(rows)}`
        const tabs = rows > 0 ? [{ tab: w.Members, rows }, ...others] : others
        return `${name}: ${tabs.map((tab) => `${count(tab.rows)} en ${tab.tab}`).join(', ')}`
      },
      // A Grados tab in a gym none of whose activities grades (#352).
      get gradosIgnored() {
        return `Grados: no se importa, porque ninguna actividad ${w.ofThePlace} entrega grados.`
      },
      otherFile: 'Elegir otra planilla',
      mappingTitle: '¿Qué es cada columna?',
      tabMappingTitle: (tab: string) => `${tab}: ¿qué es cada columna?`,
      mappingHint: 'Las ya reconocidas vienen marcadas. Las que no marques no se importan.',
      unnamedColumn: (n: number) => `Columna ${n}`,
      sample: (value: string) => `Ej.: ${value}`,
      skip: 'No importar',
      fields: {
        name: 'Nombre',
        last_name: 'Apellido',
        phone: 'Teléfono',
        email: 'Correo',
        rut: 'RUT',
        dob: 'Fecha de nacimiento',
        plan: 'Plan',
        due_on: 'Próximo pago (vencimiento)',
        started_on: 'Inicio del plan',
        guardian_name: 'Nombre del apoderado',
        guardian_rut: 'RUT del apoderado',
        guardian_email: 'Correo del apoderado',
        guardian_phone: 'Teléfono del apoderado',
        get member_since() {
          return `${w.Member} desde`
        },
        left_on: 'Fecha de baja',
        left_reason: 'Motivo de baja',
        prior_classes: 'Clases antes de Rakin',
      },
      paymentFields: {
        rut: 'RUT',
        email: 'Correo',
        name: 'Nombre',
        paid_on: 'Fecha de pago',
        amount_clp: 'Monto',
        covers_month: 'Mes que paga',
        method: 'Método',
        plan_name: 'Plan',
        note: 'Nota',
      },
      gradeFields: {
        rut: 'RUT',
        email: 'Correo',
        name: 'Nombre',
        rank: 'Grado',
        sub_rank: 'Sub-grado',
        awarded_on: 'Fecha',
        note: 'Nota',
      },
      nameRequired: 'Marca la columna con el nombre para seguir.',
      // A plan's matrícula on the memberships the import starts (#355).
      enrolment: 'Cobrar la matrícula de los planes que la tienen',
      enrolmentHint:
        'Déjalo sin marcar si ya la pagaron. Marcado, a quien empieza un plan con matrícula se le cobra como cobro extra, con vencimiento el día que empezó.',
      paymentsRequired:
        'En Pagos, marca la columna de la fecha de pago, la del monto y la de quién es (RUT, correo o nombre).',
      gradesRequired: 'En Grados, marca la columna del grado, la de la fecha y la de quién es (RUT, correo o nombre).',
      ranksTitle: 'Grados de la planilla',
      get ranksHint() {
        return `Elige a qué grado ${w.ofThePlace} corresponde cada valor. Un valor sin elegir se informa como error.`
      },
      get noRanks() {
        return `${w.ThePlace} aún no tiene grados: configúralos antes de importar los de la planilla.`
      },
      pickRank: 'Elegir un grado…',
      plansTitle: 'Planes de la planilla',
      plansHint:
        'Elige a qué plan corresponde cada valor. «Sin plan» importa a la persona sin membresía; un valor sin elegir se informa como error.',
      pickPlan: 'Elegir un plan…',
      noPlan: 'Sin plan: solo la persona',
      check: 'Revisar sin guardar',
      checking: 'Revisando…',
      back: 'Volver a las columnas',
      failed: 'No pudimos revisar la planilla. Inténtalo de nuevo.',
      reviewTitle: 'Revisión',
      doneTitle: 'Importación lista',
      summary: (imported: number, refused: number) =>
        `${imported === 1 ? '1 fila se importa' : `${imported} filas se importan`}, ${
          refused === 1 ? '1 tiene errores' : `${refused} tienen errores`
        }.`,
      doneSummary: (name: string, imported: number, refused: number) =>
        `${name}: ${imported === 1 ? '1 fila importada' : `${imported} filas importadas`}, ${
          refused === 1 ? '1 con errores' : `${refused} con errores`
        }.`,
      created: (people: number, links: number, memberships: number) =>
        // `people` counts the guardians the sheet creates too, so it can pass the row
        // count: say so whenever the sheet links any (#419).
        `${people === 1 ? '1 persona nueva' : `${people} personas nuevas`}${
          links > 0 ? ', contando apoderados' : ''
        }; ${links} ${links === 1 ? 'vínculo de apoderado' : 'vínculos de apoderado'}, ${memberships} ${
          memberships === 1 ? 'membresía' : 'membresías'
        }.`,
      nothingNew: 'No hay nada nuevo: todo lo de la planilla ya estaba.',
      history: (people: number, former: number) =>
        [
          people > 0 && `Historial completado: ${people === 1 ? '1 persona' : `${people} personas`}.`,
          former > 0 && `${former === 1 ? `1 ${w.formerMember}` : `${former} ${w.formerMembers}`}, sin plan.`,
        ]
          .filter(Boolean)
          .join(' '),
      paymentsCreated: (n: number, amount: number) =>
        `Pagos anteriores nuevos: ${n.toLocaleString('es-CL')}, por $${amount.toLocaleString('es-CL')}.`,
      paymentsTitle: 'Pagos anteriores',
      paymentsSummary: (created: number, existing: number, refused: number) =>
        [
          created === 1 ? '1 pago nuevo' : `${created.toLocaleString('es-CL')} pagos nuevos`,
          existing > 0 && (existing === 1 ? '1 ya estaba' : `${existing.toLocaleString('es-CL')} ya estaban`),
          refused > 0 && (refused === 1 ? '1 con errores' : `${refused.toLocaleString('es-CL')} con errores`),
        ]
          .filter(Boolean)
          .join(', ') + `. Quedan en el historial de cada ${w.member}: no se cobran ni cambian lo que debe.`,
      paymentsErrorsTitle: 'Pagos con errores',
      paymentsErrorsHint:
        'Estas filas no se importan. Corrígelas en la planilla y vuelve a subirla: lo ya importado no se duplica.',
      paymentError: {
        required: 'falta',
        invalid_rut: 'no es un RUT válido',
        invalid_email: 'no es un correo válido',
        invalid_date: 'no es una fecha válida (hasta 60 años atrás, nunca después de hoy)',
        invalid_amount: 'no es un monto en pesos mayor que cero',
        invalid_method: 'no es Efectivo, Transferencia ni Otro',
        get unknown_person() {
          return `no está en ${w.Members} ni en ${w.thePlace}`
        },
        ambiguous_name: 'hay dos personas con ese nombre: agrega RUT o correo',
        covers_plan: 'ya está en su plan de Rakin: regístralo con «Pagado hasta» en su ficha',
        repeated: 'se repite en una fila anterior (misma persona, fecha, monto y mes)',
        too_long: 'es demasiado largo',
      },
      // Importar's recent imports, and "Deshacer importación" (#300).
      recentTitle: 'Importaciones recientes',
      get recentHint() {
        return `Deshacer una importación quita los pagos anteriores y grados que trajo, y devuelve el historial a como estaba. Las personas y planes que creó se mantienen, y al importar de nuevo no se actualizan: si una columna corrida dejó mal sus datos (un teléfono en el RUT), corrígelos en su ficha, o elimina desde su ficha ${w.memberIs('los', 'las')} ${w.formerMembers} que creó.`
      },
      unnamedFile: 'Planilla sin nombre',
      recentWho: (by: string | null, day: string) => (by ? `${by} · ${day}` : day),
      recentCounts: (people: number, history: number, payments: number, grades: number) =>
        [
          people > 0 && (people === 1 ? '1 persona nueva' : `${people.toLocaleString('es-CL')} personas nuevas`),
          history > 0 && `historial de ${history === 1 ? '1 persona' : `${history.toLocaleString('es-CL')} personas`}`,
          payments > 0 && (payments === 1 ? '1 pago anterior' : `${payments.toLocaleString('es-CL')} pagos anteriores`),
          grades > 0 && (grades === 1 ? '1 grado' : `${grades.toLocaleString('es-CL')} grados`),
        ]
          .filter(Boolean)
          .join(' · ') || 'Sin cambios',
      undone: (day: string, by: string | null, reason: string) =>
        `Deshecha el ${day}${by ? ` por ${by}` : ''}. Motivo: ${reason}`,
      undo: 'Deshacer importación',
      undoForm: {
        title: 'Deshacer importación',
        checking: 'Revisando qué se deshace…',
        removes: (payments: number, grades: number, people: number) => {
          const n = (count: number) => count.toLocaleString('es-CL')
          const rows = [
            payments > 0 && (payments === 1 ? '1 pago anterior' : `${n(payments)} pagos anteriores`),
            grades > 0 && (grades === 1 ? '1 grado' : `${n(grades)} grados`),
          ].filter(Boolean)
          const removed = rows.length > 0 ? `Se eliminan ${rows.join(' y ')} de esta importación.` : ''
          const restored =
            people > 0
              ? `El historial de ${people === 1 ? '1 persona' : `${n(people)} personas`} (${w.member} desde, clases antes de Rakin, fecha y motivo de baja) vuelve a como estaba.`
              : ''
          return [removed, restored].filter(Boolean).join(' ') || 'Esta importación no dejó historial que deshacer.'
        },
        kept: (n: number) =>
          n === 1
            ? '1 dato cambiado después de importar se mantiene.'
            : `${n.toLocaleString('es-CL')} datos cambiados después de importar se mantienen.`,
        get stays() {
          return `Las personas y planes que creó se mantienen. ${w.memberIs('Un', 'Una')} ${w.formerMember} que creó se puede eliminar desde su ficha.`
        },
        reason: 'Motivo',
        reasonNeeded: 'Escribe el motivo.',
        submit: 'Deshacer importación',
        working: 'Deshaciendo…',
        cancel: 'Cancelar',
        failed: 'No pudimos deshacer la importación. Inténtalo de nuevo.',
        alreadyUndone: 'Esta importación ya se deshizo.',
      },
      undoDone: 'Importación deshecha.',
      gradesCreated: (n: number) => (n === 1 ? 'Grados nuevos: 1.' : `Grados nuevos: ${n}.`),
      gradesTitle: 'Grados',
      gradesSummary: (created: number, existing: number, refused: number) =>
        [
          created === 1 ? '1 grado nuevo' : `${created} grados nuevos`,
          existing > 0 && (existing === 1 ? '1 ya estaba' : `${existing} ya estaban`),
          refused > 0 && (refused === 1 ? '1 con errores' : `${refused} con errores`),
        ]
          .filter(Boolean)
          .join(', ') + '. El más reciente de cada persona queda como su grado actual.',
      gradesExistingHint:
        'Los que ya estaban no se cambian, ni siquiera su nota: una nota corregida en la planilla no se aplica.',
      gradesErrorsTitle: 'Grados con errores',
      gradesErrorsHint:
        'Estas filas no se importan. Corrígelas en la planilla y vuelve a subirla: lo ya importado no se duplica.',
      gradeError: {
        required: 'falta',
        invalid_rut: 'no es un RUT válido',
        invalid_email: 'no es un correo válido',
        invalid_date: 'no es una fecha válida (hasta 60 años atrás, nunca después de hoy)',
        get unknown_rank() {
          return `no corresponde a ningún grado ${w.ofThePlace}`
        },
        get unknown_person() {
          return `no está en ${w.Members} ni en ${w.thePlace}`
        },
        ambiguous_name: 'hay dos personas con ese nombre: agrega RUT o correo',
        repeated: 'se repite en una fila anterior',
        too_long: 'es demasiado largo (máximo 500 caracteres)',
      },
      errorsTitle: 'Filas con errores',
      errorsHint: 'Estas filas no se importan. Corrígelas en la planilla y vuelve a subirla: lo ya importado no se duplica.',
      rowLabel: (row: number, name: string) => (name ? `Fila ${row} · ${name}` : `Fila ${row}`),
      error: {
        required: 'falta',
        repeated: 'se repite en una fila anterior',
        invalid_phone: 'no es un celular chileno',
        invalid_email: 'no es un correo válido',
        invalid_rut: 'no es un RUT válido',
        invalid_date: 'no es una fecha válida',
        get own_guardian() {
          return `es el mismo RUT ${w.ofTheMember}`
        },
        unknown_plan: 'no corresponde a ningún plan',
        inactive_plan: 'es un plan desactivado',
        dropin_plan: 'es una clase suelta, no una membresía',
        ended_plan: 'es un plan cuyo período ya terminó',
        due_before_start: 'es anterior al inicio del plan',
        get has_guardian() {
          return `${w.theMember} ya tiene otro apoderado`
        },
        one_level: 'el apoderado está a cargo de otra persona',
        has_left: 'fue dado de baja: reactívalo desde su ficha',
        ambiguous_name: 'Nombre repetido: agrega RUT o correo',
        get rut_in_gym() {
          return `ya es de otra persona ${w.ofThePlace}`
        },
        get email_in_gym() {
          return `ya es de otra persona ${w.ofThePlace}`
        },
        get left_before_start() {
          return `es anterior a «${w.Member} desde»`
        },
        invalid_number: 'no es un número de clases',
        too_long: 'es demasiado largo (máximo 200 caracteres)',
        minor: 'falta: es menor de 18 años',
      },
      fieldError: (field: string, problem: string) => `${field}: ${problem}`,
      missingPhoneTitle: (n: number) => (n === 1 ? 'Falta teléfono: 1 fila' : `Falta teléfono: ${n} filas`),
      get missingPhoneHint() {
        return `Se importan igual, marcadas «Falta teléfono» en ${w.Members}. Agrega el celular en su ficha (el del apoderado, si es menor) o marca «No tiene WhatsApp».`
      },
      missingIdentityTitle: (n: number) => (n === 1 ? 'Falta RUT: 1 fila' : `Falta RUT: ${n} filas`),
      get missingIdentityHint() {
        return `Se importan igual, marcadas «Falta RUT» en ${w.Members}. Sin RUT ni correo, al volver a importar los encontramos por su nombre (y su fecha de nacimiento o teléfono si hay dos con el mismo nombre): agrega el RUT en su ficha.`
      },
      keptTitle: 'Ya existen: no se actualizan',
      get keptHint() {
        return `Lo que ${w.thePlace} ya tiene no se sobrescribe; el historial solo se completa si estaba vacío, y a quien ya entrena aquí no se le da de baja. Si algo cambió, edítalo en la ficha ${w.ofTheMember}.`
      },
      formerTitle: (n: number) => (n === 1 ? `${w.FormerMembers}: 1 fila` : `${w.FormerMembers}: ${n} filas`),
      get formerHint() {
        return `Tienen «Fecha de baja»: se agregan como ${w.formerMembers}, sin plan ni cobros, y no les llega ningún mensaje.`
      },
      kept: (fields: string[]) => `Ya existe: no se actualiza ${fields.join(', ')}.`,
      // A former student created by the sheet: their plan is not imported.
      formerKept: (fields: string[]) => `No se importa: ${fields.join(', ')}.`,
      apply: (n: number) => (n === 1 ? 'Importar 1 fila' : `Importar ${n} filas`),
      applying: 'Importando…',
      applyFailed: 'No pudimos importar. No se guardó nada; inténtalo de nuevo.',
      get toStudents() {
        return `Ver ${w.members}`
      },
      again: 'Importar otra planilla',
    },
    family: {
      toggle: 'Familia',
      toggleLabel: (name: string) => `Familia de ${name}`,
      loading: 'Cargando familia…',
      error: 'No pudimos cargar la familia.',
      guardian: 'Apoderado',
      dependents: 'A cargo',
      none: 'No tiene a nadie a cargo.',
      unlink: 'Desvincular',
      unlinkLabel: (name: string) => `Desvincular a ${name}`,
      unlinkConfirm: (name: string) => `¿Desvincular a ${name}? Ambos siguen en ${w.thePlace}; solo deja de estar a cargo.`,
      unlinkCancel: 'Cancelar',
      addTitle: 'Agregar a alguien a cargo',
      close: 'Cerrar',
      addHint: 'Sin teléfono ni correo: todo le llega al apoderado.',
      name: 'Nombre',
      rut: 'RUT (opcional)',
      dob: 'Fecha de nacimiento (opcional)',
      add: 'Agregar',
      get linkTitle() {
        return `O vincular a ${w.aMember} que ya está`
      },
      linkSearch: 'Buscar a quién vincular',
      link: 'Vincular',
      linkLabel: (name: string) => `Vincular a ${name}`,
      get noMatches() {
        return `Ningún ${w.member} coincide.`
      },
      refused: {
        has_guardian: 'Esa persona ya tiene un apoderado.',
        // Unlinking a minor's guardian (#368).
        minor: 'Es menor de 18 años: no puede quedar sin apoderado.',
        one_level:
          'Un apoderado no puede estar a cargo de otro, y quien está a cargo no puede ser apoderado.',
        invalid: 'Revisa los datos: el RUT o la fecha no son válidos.',
        failed: 'No pudimos guardar el cambio. Inténtalo de nuevo.',
      },
    },
    member: {
      get back() {
        return `Volver a ${w.Members}`
      },
      loading: 'Cargando ficha…',
      error: 'No pudimos cargar la ficha.',
      get notFound() {
        return `No encontramos a ${w.memberIs('este', 'esta')} ${w.member}.`
      },
      retry: 'Reintentar',
      since: (month: string) => `${w.Member} desde ${month}`,
      // `Azul · 2 grados · alumno desde mar 2024`: the rank, and a member since. Said
      // whole, so it does not read as the belt's date, which Graduación has (#213).
      rankSince: (rank: string, month: string) => `${rank} · ${w.member} desde ${month}`,
      noPlan: 'Sin plan',
      paymentLabel: 'Estado de pago',
      dueDay: (plan: string, day: number) => `${plan} · vence el ${day}`,
      until: (plan: string, day: string) => `${plan} · hasta el ${day}`,
      overdue: (days: number) => `Vencido ${days} d`,
      frozenUntil: (day: string) => `Congelado · vuelve el ${day}`,
      freezeBooked: (from: string, to: string) => `Congelación programada: del ${from} al ${to}`,
      pendingMonth: (month: string) => `${month} pendiente`,
      pendingPeriods: (n: number) => `${n} períodos pendientes`,
      upToDate: 'Al día',
      upToDateNext: (day: string) => `Al día · vence el ${day}`,
      paidThrough: (day: string) => `Al día · pagado hasta el ${day}`,
      nothingToRecord: 'Está al día y no tiene un período abierto: el pago se registra cuando se genere el próximo cobro.',
      // Dado de baja: no charge is coming, so none to wait for (#213).
      nothingToRecordLeft: 'Su plan terminó y no debe nada: no hay pagos por registrar.',
      whatsapp: (name: string) => `WhatsApp a ${name}`,
      whatsappGuardian: (name: string) => `WhatsApp a ${name}, su apoderado`,
      ledgerError: 'No pudimos cargar los pagos.',
      editPerson: 'Editar datos',
      exitLabel: 'Dar de baja o eliminar',
      // Their sign-in link (#246): the welcome, and how the latest one went.
      access: {
        title: 'Acceso',
        to: (address: string) => `Su link para entrar llega a ${address}.`,
        toGuardian: (name: string, address: string) => `Su link para entrar llega a ${name}, su apoderado: ${address}.`,
        noEmail: 'Sin correo: agrégalo en Datos para enviarle su link para entrar.',
        never: 'Aún no le hemos enviado la bienvenida.',
        waiting: 'Enviando la bienvenida…',
        sent: (day: string) => `Bienvenida enviada el ${day}.`,
        failed: (day: string) => `No se pudo enviar la bienvenida el ${day}. Revisa el correo y vuelve a intentarlo.`,
        // An address Resend reported (#104): no mail goes to it, from any gym.
        bounced: (day: string) =>
          `Los correos a esta dirección rebotan desde el ${day}, así que ya no le enviamos ninguno. Corrígela en Datos.`,
        complained: (day: string) =>
          `El ${day} marcó uno de nuestros correos como spam, así que ya no le enviamos ninguno a esta dirección.`,
        bounceDetail: (detail: string) => `Su servidor respondió: ${detail}`,
        suppressedLast: (day: string) => `La bienvenida del ${day} no se envió: esa dirección no recibía correos.`,
        send: 'Enviar link para entrar',
        resend: 'Reenviar link para entrar',
        working: 'Enviando…',
        error: 'No pudimos enviarlo. Vuelve a intentarlo.',
      },
      editForm: {
        title: 'Editar datos',
        name: 'Nombre y apellido',
        phone: 'Teléfono (WhatsApp)',
        noWhatsapp: 'No tiene WhatsApp',
        email: 'Correo',
        rut: 'RUT',
        dob: 'Fecha de nacimiento (opcional)',
        save: 'Guardar',
        cancel: 'Cancelar',
        working: 'Guardando…',
        saved: 'Datos guardados.',
        nameNeeded: 'Escribe el nombre.',
        refused: {
          get rut_in_gym() {
            return `Ese RUT ya es de ${w.memberIs('otro', 'otra')} ${w.member} ${w.ofThePlace}.`
          },
          get email_in_gym() {
            return `Ese correo ya es de ${w.memberIs('otro', 'otra')} ${w.member} ${w.ofThePlace}.`
          },
          open: 'Abrir su ficha',
          get phone() {
            return `${w.memberIs('Un', 'Una')} ${w.member} necesita un teléfono. Si no tiene WhatsApp, marca "No tiene WhatsApp".`
          },
          identity: 'Deja el RUT o el correo: uno de los dos dice quién es.',
          // A birth date that makes them a minor, and they have no guardian (#368).
          minor:
            'Con esa fecha es menor de 18 años y necesita un apoderado. Vincúlalo primero desde la ficha del apoderado, con «Agregar a alguien a cargo».',
          invalid: 'Revisa los datos: el teléfono, el RUT, el correo o la fecha no son válidos.',
          failed: 'No pudimos guardar los cambios. Inténtalo de nuevo.',
        },
      },
      missingPhone: 'Falta teléfono: agrégalo en Editar datos, o marca "No tiene WhatsApp".',
      noWhatsapp: 'Sin WhatsApp: no le llegan recordatorios por WhatsApp.',
      missingRut: 'Falta RUT: agrega su RUT (o su correo) en Editar datos para que no se confunda con otra persona del mismo nombre.',
      missingGuardian:
        'Falta apoderado: es menor de 18 años, y Rakin no le escribe hasta que tenga uno. En la ficha del apoderado, usa «Agregar a alguien a cargo» y vincúlalo.',
      // "Requisitos" (#349): each of the gym's requirements, and where they stand on it.
      requirements: {
        title: 'Requisitos',
        error: 'No pudimos cargar sus requisitos.',
        state: REQUIREMENT_STATES,
        done: (day: string) => `Hecho el ${day}`,
        until: (day: string) => `vence el ${day}`,
        expiredOn: (day: string) => `venció el ${day}`,
        record: 'Registrar',
        recordLabel: (name: string) => `Registrar ${name}`,
        recorded: (name: string) => `Registrado: ${name}.`,
        form: {
          title: (name: string) => `Registrar ${name}`,
          doneOn: 'Fecha',
          doneOnHint: 'Hoy, o el día en que lo hizo.',
          note: 'Nota (opcional)',
          noteHint: NO_HEALTH,
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          future: 'La fecha es hoy como máximo.',
          failed: 'No pudimos registrarlo. Inténtalo de nuevo.',
        },
      },
      // "Privacidad" (#370): what their data rest on, and who accepted which notice when.
      consent: {
        title: 'Privacidad',
        loading: 'Cargando…',
        error: 'No pudimos cargar su registro de privacidad.',
        basis: {
          contract: 'Base legal: el contrato de membresía.',
          guardian_consent: 'Base legal: el consentimiento de su apoderado, aparte de la membresía.',
        },
        given: 'Su apoderado dio su consentimiento.',
        withdrawn:
          'Su apoderado retiró su consentimiento. La membresía sigue igual; puede darlo de nuevo desde su página.',
        missing:
          'Falta el consentimiento de su apoderado. Se lo pide su página, en Rakin, y el correo de bienvenida le dice dónde.',
        get none() {
          return `Sin registro: ${w.thePlace} lo agregó a mano o por planilla, sin el formulario de inscripción.`
        },
        // One act of the register: when, who, and the notice's version.
        event: {
          notice_accepted: (by: string) => `${by} aceptó la política de privacidad en la inscripción`,
          consent_given: (by: string, page: boolean) =>
            `${by} dio su consentimiento ${page ? 'desde su página' : 'en la inscripción'}`,
          consent_withdrawn: (by: string) => `${by} retiró su consentimiento desde su página`,
        },
        // An act whose actor left the gym: only ever a guardian, since the person is here.
        get goneGuardian() {
          return `Su apoderado, que ya no está en ${w.thePlace},`
        },
        version: (day: string) => `política del ${day}`,
        // Before the register kept the version.
        noVersion: 'versión no registrada',
      },
      // "Historial" (#293): what the gym knew before Rakin, never billed.
      history: {
        title: 'Historial',
        empty: 'Nada anterior a Rakin todavía.',
        memberSince: (day: string) => `${w.Member} desde ${day}`,
        priorClasses: (n: number) => (n === 1 ? '1 clase antes de Rakin' : `${n} clases antes de Rakin`),
        add: 'Agregar historial',
        start: 'Fecha de inicio y clases',
        // A belt earned before Rakin (#296), with the Graduación's form.
        grade: 'Grado anterior',
        gradeSaved: 'Grado anterior guardado.',
        saved: 'Historial guardado.',
        // "Historial de pagos" (#295): what they paid before Rakin, a year at a time.
        payments: 'Pagos anteriores',
        paymentsError: 'No pudimos cargar sus pagos anteriores.',
        year: (year: number, count: number) => `${year} · ${count === 1 ? '1 pago' : `${count} pagos`}`,
        earlier: (n: number) => `Ver años anteriores (${n})`,
        fewer: 'Ver menos años',
        // A line: the month it paid, else the day; then how, the plan, where it came from.
        line: {
          month: (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`,
          payment: 'Pago',
          paid: (day: string) => `pagado el ${day}`,
          method: { cash: 'efectivo', transfer: 'transferencia', other: 'otro' },
          typed: (by: string, day: string) => `agregado por ${by} · ${day}`,
          typedNobody: (day: string) => `agregado el ${day}`,
          imported: (file: string, by: string | null, day: string) =>
            by ? `importado de ${file} · ${by} · ${day}` : `importado de ${file} · ${day}`,
        },
        remove: {
          title: (what: string) => `Eliminar ${what}`,
          intro:
            'Para un error de tipeo: se borra del historial y queda registrado quién lo borró y por qué. Para corregirlo, elimínalo y agrégalo de nuevo.',
          reason: 'Motivo',
          reasonNeeded: 'Escribe por qué lo eliminas.',
          submit: 'Eliminar',
          cancel: 'Cancelar',
          working: 'Eliminando…',
          failed: 'No pudimos eliminarlo. Inténtalo de nuevo.',
          done: 'Pago eliminado del historial.',
        },
        paymentsForm: {
          title: 'Agregar pagos anteriores',
          intro:
            'Lo que pagó antes de Rakin, mes a mes. Solo se muestra en su ficha: no cuenta en Pagos ni se le cobra.',
          from: 'Desde',
          to: 'Hasta',
          amount: 'Monto por mes',
          method: 'Método',
          methodUnknown: 'No se sabe',
          methods: { cash: 'Efectivo', transfer: 'Transferencia', other: 'Otro' },
          day: 'Día de pago',
          plan: 'Plan (opcional)',
          planPlaceholder: 'Mensual 3x semana',
          months: 'Meses',
          // "ene 2024", a row of the list.
          month: (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]!.slice(0, 3)} ${iso.slice(0, 4)}`,
          rowDay: (month: string) => `Día de pago de ${month}`,
          rowAmount: (month: string) => `Monto de ${month}`,
          rowMethod: (month: string) => `Método de ${month}`,
          removeRow: (month: string) => `Quitar ${month}: ese mes no pagó`,
          total: (count: number, amount: string) => `${count === 1 ? '1 pago' : `${count} pagos`} · ${amount}`,
          inPlan: (month: string) => `Desde ${month} está en su plan: usa Pagado hasta.`,
          duplicate: 'Ya está en el historial',
          duplicates: (n: number) =>
            n === 1
              ? '1 pago es igual a uno que ya está en el historial: se guardará otra vez.'
              : `${n} pagos son iguales a otros que ya están en el historial: se guardarán otra vez.`,
          rangeNeeded: 'Elige desde y hasta, de los últimos 60 años hasta este mes.',
          tooMany: (max: number) => `Hasta ${max} meses a la vez.`,
          amountNeeded: 'Escribe el monto de cada mes.',
          dayNeeded: 'Escribe un día del 1 al 31.',
          noneLeft: 'No queda ningún mes para guardar.',
          coversPlan: (day: string) =>
            `Su plan empezó el ${day}: ese mes y los siguientes se registran con Pagado hasta, no en el historial.`,
          outsideWindow: 'Hay un mes de hace más de 60 años o posterior a hoy. Revisa desde y hasta.',
          submit: (count: number) => (count === 1 ? 'Guardar 1 pago' : `Guardar ${count} pagos`),
          cancel: 'Cancelar',
          working: 'Guardando…',
          failed: 'No pudimos guardar los pagos. Inténtalo de nuevo.',
          saved: (count: number) =>
            count === 1 ? '1 pago guardado en el historial.' : `${count} pagos guardados en el historial.`,
        },
        form: {
          title: 'Fecha de inicio y clases',
          intro:
            'Desde cuándo entrena aquí y cuántas clases tuvo antes de Rakin. Solo se muestra en su ficha: no cambia su plan ni lo que se le cobra.',
          get since() {
            return `${w.Member} desde (opcional)`
          },
          classes: 'Clases antes de Rakin',
          sinceNeeded: 'Elige un día de hoy hacia atrás, de los últimos 60 años.',
          classesNeeded: 'Escribe un número entero, 0 o más.',
          submit: 'Guardar',
          cancel: 'Cancelar',
          working: 'Guardando…',
          failed: 'No pudimos guardar el historial. Inténtalo de nuevo.',
        },
      },
      leave: 'Dar de baja',
      leftBanner: (day: string) => `Dado de baja desde el ${day}. Su historial sigue aquí.`,
      // Under the banner, for the owner and admins only (#294).
      leftBannerReason: (reason: string) => `Motivo: ${reason}`,
      // "Motivo" (#294), on Dar de baja and "Agregar exalumno": the chips fill the text.
      leftReason: {
        label: 'Motivo (opcional)',
        chipsLabel: 'Motivos',
        chips: ['Precio', 'Horario', 'Se cambió', 'Motivo personal', 'Otro'],
        hint: `Solo lo ven tú y los administradores. ${NO_HEALTH} Si es eso, basta con "Motivo personal".`,
      },
      leaveForm: {
        title: 'Dar de baja',
        intro:
          'Termina su plan desde ese día: no se le cobra nada más y sale de las listas, de la asistencia y de Hoy. Lo que debe sigue pendiente en Pagos, y su historial (pagos, asistencia, grados, tiempo de entrenamiento) se mantiene.',
        on: 'Desde',
        submit: 'Dar de baja',
        cancel: 'Cancelar',
        working: 'Guardando…',
        onNeeded: 'Elige un día de hoy hacia atrás, de los últimos 60 años.',
        failed: 'No pudimos darlo de baja. Inténtalo de nuevo.',
      },
      reactivate: 'Reactivar',
      returnForm: {
        title: 'Reactivar',
        get intro() {
          return `Vuelve a la lista de ${w.members}. Si eliges un plan, empieza en él desde ese día.`
        },
        plan: 'Plan (opcional)',
        noPlan: 'Sin plan por ahora',
        startedOn: 'Desde',
        submit: 'Reactivar',
        cancel: 'Cancelar',
        working: 'Guardando…',
        done: 'Reactivado.',
        failed: 'No pudimos reactivarlo. Inténtalo de nuevo.',
      },
      remove: 'Eliminar',
      removeForm: {
        title: 'Eliminar',
        get intro() {
          return `Borra todo lo que ${w.thePlace} tiene de esta persona: su ficha, planes, cargos anulados, asistencia y grados. No se puede deshacer. Es para un error al agregarlo o si pide que borren sus datos. El registro ${w.ofThePlace} guarda quién lo eliminó, cuándo y por qué, sin sus datos.`
        },
        confirm: (name: string) => `Para confirmar, escribe su nombre: ${name}`,
        submit: 'Eliminar para siempre',
        cancel: 'Cancelar',
        working: 'Eliminando…',
        checking: 'Revisando…',
        reason: 'Motivo',
        get reasonNeeded() {
          return `Escribe por qué se elimina: queda en el registro ${w.ofThePlace}.`
        },
        // What blocks deleting, and how to clear it (#256).
        refused: {
          payment: (amount: string) =>
            `Tiene un pago de ${amount}: devuélvelo primero. El dinero recibido no se borra; si fue real, puedes darlo de baja.`,
          pending: () => 'Tiene un comprobante por validar: recházalo primero.',
          owes: (amount: string) =>
            `Debe ${amount}: anula sus cargos primero («Anular plan» o «Anular cargo»), o dale de baja si la deuda es real.`,
          staff: () => `Es parte del equipo ${w.ofThePlace}, o ha dado clases: no se puede eliminar.`,
          guardian: () => `Es apoderado de ${w.memberIs('otros', 'otras')} ${w.members}: desvincúlalos en Familia antes de eliminarlo.`,
        },
        failed: 'No pudimos eliminarlo. Inténtalo de nuevo.',
      },
      // What an earlier plan, lapsed say, still owes once a new one started (#249).
      earlierDebt: 'Deuda anterior',
      earlierDebtLine: (plan: string, pending: string) => `${plan} · ${pending}`,
      // A plan change saved, waiting for the first period not yet billed (#249).
      planChangeBooked: (plan: string, day: string) => `Pasa a ${plan} desde el ${day}`,
      assignPlan: 'Asignar plan',
      // A second plan beside the one running, a course beside a monthly plan (#354).
      addPlan: 'Agregar otro plan',
      // A plan card and its Libro, named by the plan while there are two (#354).
      planLabel: (label: string, plan: string) => `${label} · ${plan}`,
      // A plan's matrícula, as a plan starts on Asignar plan or Nuevo alumno (#355).
      enrolment: {
        paid: 'Ya pagó la matrícula',
        charged: (fee: string) => `El plan tiene matrícula: se cobra ${fee} una vez, como cobro extra, con vencimiento el día que empieza.`,
        notCharged: (fee: string) => `No se cobra la matrícula de ${fee}.`,
      },
      assignForm: {
        title: 'Asignar plan',
        get intro() {
          return `Empieza en el plan desde el día que elijas, y se le cobra como a cualquier ${w.member} del plan.`
        },
        plan: 'Plan',
        noPlan: 'Elige un plan',
        startedOn: 'Desde',
        planNeeded: 'Elige un plan.',
        welcome: 'Enviar el correo de bienvenida',
        welcomeHint: 'Le explica cómo pagar y subir el comprobante, y trae su link para entrar.',
        noEmail: 'Necesita un correo para la bienvenida: agrégalo en Datos.',
        submit: 'Asignar plan',
        cancel: 'Cancelar',
        working: 'Guardando…',
        done: (plan: string) => `Plan asignado: ${plan}.`,
        // The trial the plan converts (#27): one still running ends as it is saved.
        converts: (trial: string, since: string, running: boolean) =>
          running
            ? `Pasa de la prueba (${trial}, desde el ${since}): la prueba termina al guardar.`
            : `Cuenta como paso de la prueba (${trial}, del ${since}) a un plan.`,
        // Said before saving, when a lapsed plan still owes or has billed past the day asked (#271).
        debt: (amount: string) => `Debe ${amount} de un plan anterior. Queda como deuda anterior: se cobra aparte del nuevo plan.`,
        moved: (billed: string, starts: string) =>
          `El plan anterior ya cobró hasta el ${billed}: el nuevo empieza el ${starts}, para no cobrar dos veces los mismos días.`,
        // Off every period from the first (#25): a sibling starting with one, say.
        discount: 'Con descuento',
        failed: 'No pudimos asignar el plan. Inténtalo de nuevo.',
      },
      // A percentage off every period, and why (#25): on the plan card, and its form.
      discountLine: (pct: number, reason: string | null) => `Descuento ${pct}%${reason ? ` · ${reason}` : ''}`,
      discount: 'Descuento',
      discountForm: {
        title: 'Descuento',
        intro: 'Un porcentaje menos en cada cobro del plan: por hermanos, una beca o lo que sea.',
        pct: 'Porcentaje',
        pctNeeded: 'Escribe un porcentaje entre 1 y 100.',
        reason: 'Motivo',
        // Offered as chips under the reason; any other is written in.
        reasons: ['Hermanos', 'Beca'],
        reasonsLabel: 'Motivos frecuentes',
        reasonNeeded: 'Escribe el motivo del descuento.',
        checking: 'Calculando…',
        next: (from: string, amount: string, to: string) =>
          `Se aplica desde el cobro del ${from}: ${amount} por el período hasta el ${to}.`,
        // Taking it off: the next charge at full price.
        full: (from: string, amount: string) => `Desde el cobro del ${from} se cobra el precio completo: ${amount}.`,
        billed: 'Los cobros ya generados no cambian: para uno de ellos, usa «Cambiar monto» en el Libro.',
        submit: 'Guardar descuento',
        remove: 'Quitar descuento',
        cancel: 'Cancelar',
        working: 'Guardando…',
        done: (pct: number, reason: string) => `Descuento guardado: ${pct}% por ${reason}.`,
        removed: 'Descuento quitado.',
        refused: {
          conflict: 'Este plan ya no admite un descuento.',
          failed: 'No pudimos guardar el descuento. Inténtalo de nuevo.',
        },
      },
      changePlan: 'Cambiar plan',
      changeForm: {
        title: 'Cambiar plan',
        plan: 'Nuevo plan',
        noPlan: 'Elige un plan',
        // The plan it is on, offered while a change is pending: choosing it withdraws it.
        stay: (plan: string) => `Seguir en ${plan}`,
        none: 'No hay otro plan mensual o de varios meses activo al que cambiarlo.',
        planNeeded: 'Elige un plan.',
        checking: 'Calculando…',
        current: (plan: string, day: string) =>
          `El período actual no cambia: sigue en ${plan} hasta el ${day}, sin devoluciones ni cobros extra.`,
        next: (plan: string, from: string, amount: string, to: string) =>
          `Desde el ${from} pasa a ${plan}. El próximo cobro es de ${amount}, el ${from}, por el período hasta el ${to}.`,
        frozen: 'Está congelado: si la congelación cambia, el cambio de plan se corre con ella.',
        withdraw: (plan: string, current: string) => `Se anula el cambio a ${plan}: sigue en ${current}.`,
        submit: 'Confirmar cambio',
        cancel: 'Cancelar',
        working: 'Guardando…',
        done: (plan: string, day: string) => `Cambio guardado: pasa a ${plan} desde el ${day}.`,
        withdrawn: 'Cambio de plan anulado.',
        refused: {
          conflict: 'Esta membresía ya no puede cambiar de plan.',
          plan: 'Ese plan ya no está disponible para un cambio.',
          failed: 'No pudimos cambiar el plan. Inténtalo de nuevo.',
        },
      },
      record: 'Registrar pago',
      freeze: 'Congelar',
      editFreeze: 'Editar congelación',
      endFreeze: 'Terminar congelación',
      callOffFreeze: 'Anular congelación',
      refund: 'Devolver',
      // Fixing a mistake (#256): the whole plan voided with a reason, under "Corregir plan" (#279).
      voidPlan: 'Anular plan',
      // One "Corregir" per Libro line, offering only that line's fixes, and "Corregir plan" (#279).
      fix: {
        charge: (month: string, plan: string | null) => `Corregir cargo ${month}${plan ? ` · ${plan}` : ''}`,
        payment: (month: string) => `Corregir pago ${month}`,
        changeAmount: 'Cambiar monto',
        voidCharge: 'Anular cargo',
        // A charge voided by mistake, owed again (#278).
        restoreCharge: 'Restaurar cargo',
        refund: 'Reembolsar',
        plan: 'Corregir plan',
        extraCharge: 'Cobro extra',
        // A line with one fix names it in the title, with no chip (#419).
        only: (title: string, fix: string) => `${title}: ${fix.toLowerCase()}`,
        // What the fix does as it is typed: the period's debt and the plan's balance.
        owed: (month: string, before: string, after: string) => `Debe en ${month}: ${before} → ${after}`,
        balance: (before: string, after: string) => `Saldo: ${before} → ${after}`,
        // Another plan's charge, under "Deuda anterior": its plan, and whether it is owed or voided.
        otherPlans: 'Otros planes',
        voided: (amount: string) => `anulado ${amount}`,
      },
      voidedBadge: 'Anulado',
      voidedBanner: (reason: string, day: string) => `Plan anulado el ${day}: ${reason}`,
      // The trial a paid plan converted (#27).
      convertedFrom: (trial: string, since: string) => `Viene de la prueba (${trial}, del ${since})`,
      voidForm: {
        title: 'Anular cargo',
        intro: 'Para un cargo hecho por error: deja de deberse en todas partes. Queda en el libro, tachado y con el motivo.',
        reason: 'Motivo',
        reasonNeeded: 'Escribe por qué se anula.',
        submit: (amount: string) => `Anular cargo de ${amount}`,
        cancel: 'Cancelar',
        working: 'Anulando…',
        done: (month: string, amount: string) => `Cargo de ${month} anulado: ${amount}.`,
      },
      restoreForm: {
        title: 'Restaurar cargo',
        intro: 'Para un cargo anulado por error: vuelve a deberse, como si no se hubiera anulado. Quedan en el libro la anulación y la restauración.',
        reason: 'Motivo',
        reasonNeeded: 'Escribe por qué se restaura.',
        submit: 'Restaurar cargo',
        cancel: 'Cancelar',
        working: 'Restaurando…',
        done: (month: string, amount: string) => `Cargo de ${month} restaurado: vuelve a deberse ${amount}.`,
      },
      // Why a restore was refused (#278).
      restoreRefused: {
        not_a_void: 'Ese movimiento no es una anulación.',
        restored: 'Ese cargo ya se restauró.',
        plan_voided: 'El plan se anuló completo: para volver a cobrarlo, asígnalo de nuevo.',
        failed: 'No pudimos restaurarlo. Inténtalo de nuevo.',
      },
      voidPlanForm: {
        title: 'Anular plan',
        intro:
          'Para un plan asignado por error: termina desde su inicio, se anulan todos sus cargos sin pagar y no se cobra más. Distinto de dar de baja, que termina un plan real y mantiene lo que se debe.',
        reason: 'Motivo',
        reasonNeeded: 'Escribe por qué se anula.',
        submit: 'Anular plan',
        cancel: 'Cancelar',
        working: 'Anulando…',
        done: 'Plan anulado. Sus cargos sin pagar ya no se deben.',
      },
      // Why a void was refused, and how to clear it (#256).
      voidRefused: {
        paid: (amount: string) => `Tiene un pago de ${amount}: devuélvelo primero con «Devolver».`,
        pending: 'Tiene un comprobante por validar: recházalo primero.',
        nothing_owed: 'Ese cargo ya no se debe: nada que anular.',
        failed: 'No pudimos anularlo. Inténtalo de nuevo.',
      },
      // "Reactivar plan" (#284): a lapsed plan Active again, billing from where it left off or from today.
      reactivatePlan: 'Reactivar plan',
      moreActions: 'Más acciones',
      reactivateForm: {
        title: 'Reactivar plan',
        get intro() {
          return `El plan vuelve a quedar activo. Pagar lo que debía no lo reactiva solo: puede que ${w.theMember} se haya ido.`
        },
        loading: 'Calculando lo que se cobra…',
        billFrom: '¿Desde cuándo se cobra?',
        last: 'Desde donde quedó',
        lastHint: (count: number, month: string, total: string) =>
          count === 0
            ? 'No hay cuotas pendientes desde que caducó.'
            : `Cobra ${count === 1 ? 'la cuota' : `${count} cuotas`} desde ${month}: ${total}.`,
        today: 'Desde hoy',
        todayHint: (day: string, total: string) => `No cobra los meses sin plan. Cobra desde el ${day}: ${total}.`,
        reason: 'Motivo',
        reasonNeeded: 'Escribe por qué se reactiva.',
        next: 'Continuar',
        cancel: 'Cancelar',
        // The second step: what it bills, before it is saved.
        confirmTitle: 'Al reactivar se cobra',
        nothing: 'Nada por ahora: la próxima cuota llega en su fecha.',
        period: (month: string, amount: string) => `${month} · ${amount}`,
        total: (amount: string) => `Total ${amount}`,
        back: 'Volver',
        submit: 'Reactivar plan',
        working: 'Reactivando…',
        done: (total: string) => `Plan reactivado. Se cobraron ${total}.`,
        doneNothing: 'Plan reactivado.',
      },
      // Why a reactivation was refused, and what to do first.
      reactivateRefused: {
        not_lapsed: 'Este plan no está caducado.',
        not_recurring: 'Un pack o una prueba no se reactiva: asígnale uno nuevo.',
        period_ended: 'El período del plan terminó: cámbialo al plan del próximo período.',
        unpaid: (amount: string, month: string) =>
          `Debe ${amount} desde ${month}, ya fuera del plazo de gracia: caducaría de nuevo esta noche. Registra el pago o anula ese cargo primero.`,
        live_plan: (plan: string) => `Ya tiene otro plan vigente (${plan}): no puede tener dos a la vez.`,
        failed: 'No pudimos reactivarlo. Inténtalo de nuevo.',
      },
      // After a payment settles the last debt of a lapsed plan: offered, never done on its own.
      reactivateOffer: '¿Volvió? El plan sigue caducado hasta que lo reactives.',
      // "Cambiar monto" (#279): the charge's new amount, the difference written as an adjustment.
      amountForm: {
        title: 'Cambiar monto',
        current: (amount: string) => `Monto actual: ${amount}`,
        amount: 'Monto nuevo (CLP)',
        reason: 'Motivo',
        submit: (amount: string) => `Cambiar a ${amount}`,
        cancel: 'Cancelar',
        working: 'Guardando…',
        amountNeeded: 'Escribe el monto nuevo.',
        sameAmount: 'Es el monto actual: escribe otro.',
        // Lower than what came in already: the rest is given back first.
        paidMore: (paid: string) => `Ya se pagaron ${paid}: para cobrar menos, devuelve primero lo que sobra con «Devolver».`,
        reasonNeeded: 'Escribe por qué cambia el monto.',
        done: (month: string, before: string, after: string) => `Monto de ${month} cambiado: ${before} → ${after}.`,
        refused: {
          exceeds: 'Ya se pagó más que eso: devuelve primero lo que sobra con «Devolver».',
          failed: 'No pudimos cambiar el monto. Inténtalo de nuevo.',
        },
      },
      refundForm: {
        title: 'Devolución',
        payment: 'Pago a devolver',
        paymentOption: (month: string, day: string, amount: string) => `Pago ${month} · ${day} · ${amount} por devolver`,
        amount: 'Monto devuelto (CLP)',
        method: 'Medio de devolución',
        note: 'Nota (opcional)',
        submit: (amount: string) => `Devolver ${amount}`,
        cancel: 'Cancelar',
        working: 'Guardando…',
        amountNeeded: 'Escribe el monto devuelto.',
        done: (amount: string) => `Devolución registrada: ${amount}.`,
        refused: {
          exceeds: 'Ese pago ya no tiene tanto por devolver.',
          failed: 'No pudimos registrar la devolución. Inténtalo de nuevo.',
        },
      },
      freezeForm: {
        title: 'Congelar membresía',
        from: 'Desde',
        fromNeeded: 'Elige hoy o un día después.',
        until: 'Vuelve el',
        untilHint: 'Desde ese día hasta que vuelve no se cobra: el próximo pago se corre esos días.',
        reason: 'Motivo',
        reasonHint: NO_HEALTH,
        submit: 'Confirmar congelación',
        cancel: 'Cancelar',
        working: 'Guardando…',
        untilNeeded: 'Elige el día en que vuelve (después de “Desde”).',
        reasonNeeded: 'Escribe el motivo.',
        done: (day: string) => `Membresía congelada. Vuelve el ${day}.`,
        booked: (from: string, to: string) => `Congelación programada del ${from} al ${to}.`,
        refused: {
          notActive: 'Solo una membresía activa y sin otra congelación programada se puede congelar.',
          failed: 'No pudimos congelar la membresía. Inténtalo de nuevo.',
        },
      },
      editFreezeForm: {
        title: 'Editar congelación',
        until: 'Vuelve el',
        untilHint: 'El próximo pago se corre los días que la congelación se alarga o se acorta.',
        reason: 'Motivo',
        reasonHint: NO_HEALTH,
        submit: 'Guardar cambios',
        cancel: 'Cancelar',
        working: 'Guardando…',
        untilNeeded: 'Elige un día después de hoy y del primer día.',
        reasonNeeded: 'Escribe el motivo.',
        done: (day: string) => `Congelación actualizada. Vuelve el ${day}.`,
        failed: 'No pudimos guardar los cambios. Inténtalo de nuevo.',
      },
      endFreezeForm: {
        title: 'Terminar congelación',
        endHint: 'Vuelve hoy. El próximo pago se adelanta los días que ya no estará congelado.',
        callOffHint: (from: string, to: string) => `La congelación del ${from} al ${to} no se hará.`,
        end: 'Terminar hoy',
        callOff: 'Anular congelación',
        cancel: 'Volver',
        working: 'Guardando…',
        ended: 'Congelación terminada. La membresía está activa.',
        calledOff: 'Congelación anulada.',
        failed: 'No pudimos terminar la congelación. Inténtalo de nuevo.',
      },
      form: {
        title: 'Registrar pago',
        period: 'Período',
        periodOption: (month: string, amount: string) => `${month} · ${amount} por pagar`,
        amount: 'Monto recibido (CLP)',
        method: 'Medio de pago',
        methods: { cash: 'Efectivo', transfer: 'Transferencia', other: 'Otro' },
        note: 'Nota (opcional)',
        submit: (amount: string) => `Registrar ${amount}`,
        cancel: 'Cancelar',
        working: 'Guardando…',
        amountNeeded: 'Escribe el monto recibido.',
        recorded: (amount: string) => `Pago registrado: ${amount}.`,
        credit: (amount: string) => ` Quedan ${amount} a favor.`,
        remainder: (amount: string) => ` Quedan ${amount} por pagar del período.`,
        refused: {
          paid: 'Ese período ya está pagado.',
          failed: 'No pudimos registrar el pago. Inténtalo de nuevo.',
        },
        // Paying ahead (#196): al día, with no period open.
        ahead: {
          intro: 'Está al día. Registra lo que paga por adelantado.',
          periods: 'Paga',
          // `3 meses · hasta el 10 feb · $135.000`
          option: (n: number, monthly: boolean, until: string, amount: string) =>
            `${n} ${monthly ? (n === 1 ? 'mes' : 'meses') : n === 1 ? 'período' : 'períodos'} · hasta el ${until} · ${amount}`,
          loading: 'Calculando los próximos períodos…',
          error: 'No pudimos calcular los próximos períodos.',
          recorded: (amount: string, day: string) => `Pago registrado: ${amount}. Pagado hasta el ${day}.`,
          // One for each 409 `code` of `POST /api/ledger/payments/ahead`.
          refused: {
            cannot_pay_ahead:
              'Ya no puede pagar por adelantado: tiene un período abierto o su plan cambió. Revisa su ficha.',
            amount_changed: 'El precio de esos períodos cambió. Revisa el nuevo total y vuelve a registrar.',
            already_billed: 'Esos períodos se generaron mientras tanto. Revisa su ficha antes de registrar.',
          },
        },
      },
      fields: {
        title: 'Datos',
        phone: 'Teléfono',
        email: 'Correo',
        rut: 'RUT',
        dob: 'Fecha de nacimiento',
        loading: 'Cargando datos…',
        error: 'No pudimos cargar los datos.',
        empty: 'Sin dato',
        sensitive: 'Sensible',
        edit: 'Editar datos',
        formTitle: 'Editar datos',
        choose: 'Sin elegir',
        save: 'Guardar',
        cancel: 'Cancelar',
        working: 'Guardando…',
        saved: 'Datos guardados.',
        refused: {
          invalid: 'Revisa los campos marcados.',
          failed: 'No pudimos guardar los datos. Inténtalo de nuevo.',
        },
      },
      attendance: {
        title: 'Asistencia',
        // With classes before Rakin, the total says how many of it they are (#293):
        // "clases en 30 días · 340 clases (320 antes de Rakin)".
        detail: (recent: number, total: number, before = 0) =>
          `${recent === 1 ? 'clase' : 'clases'} en 30 días · ${
            before > 0 ? `${total} ${total === 1 ? 'clase' : 'clases'} (${before} antes de Rakin)` : `${total} en total`
          }`,
        error: 'No pudimos cargar la asistencia.',
      },
      grading: {
        title: 'Graduación',
        error: 'No pudimos cargar la graduación.',
        none: 'Sin graduación registrada.',
        since: (day: string) => `desde ${day}`,
        sincePromotion: (n: number) =>
          n === 1 ? '1 clase desde la última graduación' : `${n} clases desde la última graduación`,
        // "62 / 80 clases para Morada": towards the next promotion, named by the scheme's own label.
        goal: (done: number, target: number, metric: 'classes_since_promotion' | 'time_in_rank', next: string | null) =>
          `${done} / ${target} ${
            metric === 'classes_since_promotion' ? (target === 1 ? 'clase' : 'clases') : target === 1 ? 'mes' : 'meses'
          } para ${next ?? 'la próxima graduación'}`,
        goalLabel: 'Avance a la próxima graduación',
        award: 'Registrar graduación',
        log: 'Historial',
        by: (name: string) => `registró ${name}`,
        form: {
          title: 'Registrar graduación',
          historyTitle: 'Grado anterior',
          historyIntro:
            'Un grado que obtuvo antes de Rakin, con la fecha en que lo recibió. Si es el más reciente, es su grado actual. No se le avisa.',
          rank: 'Rango',
          ranks: 'Adultos',
          kids: 'Kids',
          subRank: 'Grado',
          date: 'Fecha',
          note: 'Nota (opcional)',
          submit: 'Registrar',
          cancel: 'Cancelar',
          working: 'Guardando…',
          done: (rank: string) => `Graduación registrada: ${rank}.`,
          refused: {
            awarded_in_future: 'La fecha no puede ser posterior a hoy.',
            awarded_too_early: 'La fecha no puede ser de hace más de 60 años.',
            get grading_scheme_invalid() {
              return `Revisa el sistema de grados ${w.ofThePlace} antes de registrar.`
            },
            failed: 'No pudimos registrar la graduación. Inténtalo de nuevo.',
          },
        },
      },
      ledger: {
        title: 'Libro',
        empty: 'Sin movimientos todavía.',
        charge: (month: string) => `Cargo ${month}`,
        payment: (month: string) => `Pago ${month}`,
        // An adjustment by which way it goes (#210): a discount takes from what is owed.
        adjustment: (favor: boolean, month: string) => `${favor ? 'Descuento' : 'Recargo'} ${month}`,
        credit: 'Saldo a favor',
        refund: (month: string) => `Devolución ${month}`,
        generated: (day: string) => `generado ${day}`,
        // The discount a charge was billed at (#25).
        discounted: (pct: number, reason: string | null) => `descuento ${pct}%${reason ? ` (${reason})` : ''}`,
        unpaid: 'sin pago',
        // A charge partly paid: what has come in against it so far.
        partlyPaid: (amount: string) => `abonado ${amount}`,
        validatedBy: (name: string) => `validó ${name}`,
        pending: 'por validar',
        rejected: 'rechazado',
        method: { transfer: 'transferencia', cash: 'efectivo', other: 'otro' },
        freezeStart: 'Congelación',
        freezeEnd: 'Fin de congelación',
        returns: (day: string) => `vuelve el ${day}`,
        // A voided charge, struck through, and the void beside it (#256).
        voided: (reason: string, by: string | null, day: string) =>
          `Anulado: ${reason}${by ? `, por ${by}` : ''}, ${day}`,
        void: (month: string) => `Anulación ${month}`,
        // A void restored (#278): the charge is owed again.
        restored: (reason: string, by: string | null, day: string) =>
          `Restaurado: ${reason}${by ? `, por ${by}` : ''}, ${day}`,
        restore: (month: string) => `Restauración ${month}`,
        all: (n: number) => `Ver todo el libro (${n})`,
        fewer: 'Ver menos',
      },
      // Every fix to the person's billing, with who, why, and before and after (#277).
      corrections: {
        title: 'Correcciones',
        error: 'No pudimos cargar las correcciones.',
        void: (month: string) => `Anuló cargo ${month}`,
        planVoid: (month: string) => `Anuló plan · cargo ${month}`,
        restore: (month: string) => `Restauró cargo ${month}`,
        // An adjustment by which way it went, as the Libro names it.
        adjustment: (favor: boolean, month: string) => `${favor ? 'Descuento' : 'Recargo'} ${month}`,
        dueDate: 'Cambió el vencimiento',
        reactivated: 'Reactivó el plan',
        cancelUndone: 'Deshizo la baja',
        // A discount set, changed or taken off (#25): its percentage before → after, and from when.
        discountSet: 'Puso descuento',
        discountChanged: 'Cambió el descuento',
        discountRemoved: 'Quitó el descuento',
        discountPct: (before: number, after: number) => `${before}% → ${after}%`,
        discountFrom: (day: string) => `desde el cobro del ${day}`,
        // What the period owed, before → after.
        owed: (before: string, after: string) => `${before} → ${after}`,
        balance: (before: string, after: string) => `Saldo ${before} → ${after}`,
        by: (name: string) => `por ${name}`,
        all: (n: number) => `Ver todas (${n})`,
        fewer: 'Ver menos',
      },
    },
    // "Entrada" (#348): checking people in at the door, with no class scheduled.
    checkIn: {
      title: 'Entrada',
      loading: 'Cargando…',
      retry: 'Reintentar',
      error: 'No pudimos cargar la entrada.',
      get none() {
        return `${w.placeIs('Este', 'Esta')} ${w.place} no tiene acceso libre. Un dueño o admin lo crea en Ajustes › Programas y clases, como una clase de tipo Acceso libre.`
      },
      // The same, said to who can make one (#418), with the way there.
      noneSetup: 'Todavía no tienes acceso libre. Créalo como una clase de tipo Acceso libre.',
      toPrograms: 'Ir a Programas y clases',
      pick: 'Acceso',
      cancelled: 'La entrada de hoy está cancelada: no se puede marcar a nadie hasta que un dueño o admin la reactive.',
      openDay: 'Ver el día',
      left: (n: number) => (n === 1 ? 'queda 1 clase' : `quedan ${n} clases`),
      overdue: 'Pago vencido',
      // A warning, never a refusal: the staff at the door decides.
      warning: { lapsed: 'Plan vencido', frozen: 'Plan congelado', noCredits: 'Sin clases en su paquete' },
      // A requirement they lack or whose record expired (#350): a warning too.
      requirement: requirementFlag,
      search: {
        label: (door: string) => `Buscar para ${door}`,
        placeholder: 'Nombre o RUT',
        hint: 'Escribe el nombre o el RUT de quien llega.',
        results: 'Resultados',
        empty: 'Nadie con ese nombre o RUT tiene un plan para entrar.',
        error: 'No pudimos buscar.',
        enter: 'Entrar',
        enterLabel: (name: string) => `Marcar la entrada de ${name}`,
        already: (time: string) => `Entró ${time}`,
        failed: 'No pudimos marcar la entrada. Inténtalo de nuevo.',
      },
      today: {
        title: 'Hoy',
        count: (n: number) => (n === 1 ? '1 entrada' : `${n} entradas`),
        empty: 'Nadie ha entrado hoy.',
        undo: 'Deshacer',
        undoLabel: (name: string) => `Deshacer la entrada de ${name}`,
        undoFailed: 'No pudimos deshacer la entrada. Inténtalo de nuevo.',
      },
      // On Clases and Hoy, for a gym with open access.
      card: {
        title: 'Entrada',
        detail: (n: number) => (n === 0 ? 'Nadie ha entrado hoy' : n === 1 ? '1 entrada hoy' : `${n} entradas hoy`),
        open: 'Abrir entrada',
      },
    },
    classes: {
      title: 'Clases',
      loading: 'Cargando…',
      retry: 'Reintentar',
      start: {
        title: 'Crear clase',
        classType: 'Tipo de clase',
        duration: 'Duración (min)',
        badDuration: 'La duración va de 1 a 1440 minutos.',
        // A class that already happened (#407): its day and time, today and now unless
        // changed; an earlier day's time is chosen, never the clock's.
        day: 'Día',
        time: 'Hora',
        chooseTime: 'Elige la hora a la que fue la clase.',
        futureDay: 'Ese día todavía no llega: las clases futuras salen del horario.',
        pastDay: 'La clase queda en ese día, con su asistencia, como si se hubiera registrado entonces.',
        submit: 'Crear clase',
        working: 'Creando…',
        get noClassTypes() {
          return `Todavía no hay tipos de clase. El dueño o un admin ${w.ofThePlace} los configura.`
        },
        error: 'No pudimos cargar los tipos de clase.',
        failed: 'No pudimos crear la clase. Inténtalo de nuevo.',
        close: 'Cerrar',
      },
      // First on Clases (#358): the class on now, else the next one today.
      now: {
        on: 'Ahora',
        next: 'Siguiente',
        take: 'Tomar asistencia',
        takeLabel: (name: string) => `Tomar asistencia de ${name}`,
      },
      today: {
        title: 'Hoy',
        count: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
        empty: 'Todavía no hay clases hoy.',
        error: 'No pudimos cargar las clases de hoy.',
        row: (time: string, classType: string) => `${time} · ${classType}`,
        detail: (program: string, coach: string) => `${program} · ${coach}`,
        noTopic: 'Sin tema',
        unmarked: 'Sin asistencia',
        cancelled: 'Cancelada',
        present: (n: number) => (n === 1 ? '1 presente' : `${n} presentes`),
      },
      // From 1024px: the week the day is in, and the class picked in it.
      week: {
        title: 'Semana',
        range: (from: string, to: string) => `${from} – ${to}`,
        error: 'No pudimos cargar este día.',
        empty: 'Sin clases.',
        picked: 'Clase elegida',
        pick: 'Elige una clase de la semana para ver su asistencia.',
        cancelled: 'Esta clase está cancelada.',
        upcoming: 'Todavía no empieza.',
        rosterError: 'No pudimos cargar la asistencia.',
        // Of those who came to this class type in the last 30 days.
        present: (present: number, regulars: number) =>
          `${present === 1 ? '1 presente' : `${present} presentes`} · ${regulars === 1 ? '1 habitual' : `${regulars} habituales`}`,
        presentLabel: 'Presentes',
        take: 'Tomar asistencia',
        open: 'Ver clase',
        // The week before or after, the day moving with it (#426).
        label: 'Cambiar de semana',
        previous: '← Semana anterior',
        next: 'Semana siguiente →',
      },
      days: {
        // A public holiday's name after the day's (#426): `lun 8 dic · La Inmaculada Concepción`.
        holiday: (day: string, name: string) => `${day} · ${name}`,
        label: 'Cambiar de día',
        previous: '← Anterior',
        next: 'Siguiente →',
        today: 'Hoy',
        empty: 'No hay clases este día.',
        jump: 'Ir a fecha',
      },
      // The day (on a phone) or its week (from 1024px), or the month the day is in (#426).
      view: {
        label: 'Vista',
        day: 'Día',
        week: 'Semana',
        month: 'Mes',
      },
      // The month's calendar: each day's classes, unmarked and cancelled ones (#426).
      month: {
        title: (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`,
        label: 'Cambiar de mes',
        previous: '← Mes anterior',
        next: 'Mes siguiente →',
        error: 'No pudimos cargar este mes.',
        // Monday first.
        weekdays: ['L', 'M', 'X', 'J', 'V', 'S', 'D'],
        weekdayNames: ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'],
        classes: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
        unmarked: (n: number) => `${n} sin asistencia`,
        cancelled: (n: number) => (n === 1 ? '1 cancelada' : `${n} canceladas`),
        // `miércoles 4 de noviembre: 3 clases, 2 sin asistencia, 1 cancelada`; a public
        // holiday's name after the day: `martes 8 de diciembre, La Inmaculada Concepción: sin clases`.
        cell: (
          weekday: string,
          iso: string,
          classes: number,
          unmarked: number,
          cancelled: number,
          holiday: string | null = null,
        ) => {
          const date = `${weekday} ${Number(iso.slice(8, 10))} de ${MONTHS[Number(iso.slice(5, 7)) - 1]}`
          const day = holiday === null ? date : `${date}, ${holiday}`
          const parts = [
            classes === 0 ? 'sin clases' : classes === 1 ? '1 clase' : `${classes} clases`,
            unmarked > 0 ? `${unmarked} sin asistencia` : null,
            cancelled > 0 ? (cancelled === 1 ? '1 cancelada' : `${cancelled} canceladas`) : null,
          ]
          return `${day}: ${parts.filter(Boolean).join(', ')}`
        },
      },
    },
    settings: {
      title: 'Ajustes',
      get adminsOnly() {
        return `Solo el dueño o un admin ${w.ofThePlace} ve los ajustes.`
      },
      roleError: 'No pudimos cargar los ajustes.',
      sectionsLabel: 'Secciones de ajustes',
      // The arrows over the tabs' faded edges, on a desktop where they do not all fit (#418).
      tabsBack: 'Ver secciones anteriores',
      tabsMore: 'Ver más secciones',
      sections: {
        get gym() {
          return w.Place
        },
        plans: 'Planes',
        programs: 'Programas y clases',
        blocks: 'Bloques',
        grading: 'Graduación',
        fields: 'Campos',
        requirements: 'Requisitos',
        staff: 'Equipo',
        joinLink: 'Inscripción',
        schedule: 'Horario',
        tags: 'Etiquetas',
        account: 'Cuenta',
      },
      // Each section's line in the list Ajustes opens on, on a phone (#177).
      descriptions: {
        gym: 'Nombre, cobro, cuenta bancaria y privacidad.',
        plans: 'Lo que vendes: mensualidades, packs y clases de prueba.',
        programs: 'Tus programas y sus tipos de clase.',
        schedule: 'Las clases de cada semana y los días cerrados.',
        tags: 'Los focos que se repiten en las clases, y sus horas.',
        blocks: 'Las partes de una clase en el timer.',
        get grading() {
          return `Opcional: grados o cinturones, si tu ${w.place} los usa, y cuándo alguien está listo para graduarse.`
        },
        get fields() {
          return `Datos extra en la ficha de cada ${w.member}.`
        },
        requirements: 'Declaraciones de riesgos, inducciones y certificados, con su fecha.',
        staff: 'Quién está en el equipo, sus cargos y qué puede hacer cada uno.',
        joinLink: 'El link para que se inscriban solos.',
        account: 'Tu nombre, tu email y cerrar sesión.',
      },
      backLabel: 'Volver a Ajustes',
      account: {
        title: 'Cuenta',
        name: 'Nombre',
        email: 'Email',
        none: 'Sin registrar',
      },
      loading: 'Cargando…',
      retry: 'Reintentar',
      // What an API 422 `type` means under a field; `range` and `value` say it per field.
      invalid: {
        required: 'Obligatorio.',
        tooLong: 'Demasiado largo.',
        choose: 'Elige una opción.',
        integer: 'Escribe un número entero, sin decimales.',
        failed: 'Revisa este campo.',
      },
      gym: {
        get title() {
          return w.Place
        },
        get error() {
          return `No pudimos cargar los datos ${w.ofThePlace}.`
        },
        get formLabel() {
          return `Datos ${w.ofThePlace}`
        },
        profile: 'Perfil',
        get name() {
          return `Nombre ${w.ofThePlace}`
        },
        slug: 'Dirección web',
        timezone: 'Zona horaria',
        // What the gym calls itself, its members and its coach (#344), each from a list
        // (`vocabulary.ts`). The first activity picks them; saved here, they stay.
        vocabulary: {
          place: 'Cómo se llama tu lugar',
          members: 'Cómo llamas a tus miembros',
          coach: 'Cómo llamas a quien enseña',
          hint: 'Las palabras de la app: el menú, los títulos, el formulario de inscripción y la página de cada persona.',
          // One button per activity whose words differ, as a one-tap suggestion.
          suggestionsLabel: 'Sugerencias según tus actividades',
          suggest: (activity: string) => `Usar las palabras de ${activity}`,
          suggested: 'Listo: guarda para usarlas.',
        },
        theme: 'Tema',
        get themeHint() {
          return `Los colores de la app, la página ${w.ofTheMember}, el formulario de inscripción y la entrada. El cronómetro sigue verde y rojo en todos.`
        },
        themes: { bosque: 'Bosque', oceano: 'Océano', volcan: 'Volcán' },
        themeDefault: 'Por defecto',
        themePreview: (name: string, saved: string) => `Así se ve ${name}. Guarda para dejarlo, o cancela para volver a ${saved}.`,
        themeCancel: 'Cancelar',
        themeSample: { collected: 'Cobrado', figure: '$2.115.000', paid: 'Pagado', overdue: 'Vencido', action: 'Registrar' },
        activities: {
          title: 'Actividades',
          get hint() {
            return `Lo que enseña tu ${w.place}: una o varias. Los grados (cinturones, niveles) aparecen en la app solo si una actividad los usa.`
          },
          none: 'Todavía no hay actividades.',
          usesGrades: 'Usa grados (cinturones, niveles)',
          classTypes: (n: number) => (n === 1 ? '1 tipo de clase' : `${n} tipos de clase`),
          add: 'Agregar actividad',
          pick: 'Elige…',
          other: 'Otra',
          name: 'Nombre de la actividad',
          adding: 'Agregando…',
          addSubmit: 'Agregar',
          rename: 'Renombrar',
          renameLabel: (name: string) => `Nuevo nombre para ${name}`,
          save: 'Guardar nombre',
          cancel: 'Cancelar',
          remove: 'Quitar',
          removeLabel: (name: string) => `Quitar ${name}`,
          removeConfirm: (name: string, classTypes: number) =>
            classTypes > 0
              ? `¿Quitar ${name}? Sus tipos de clase quedan, sin actividad.`
              : `¿Quitar ${name}?`,
          added: (name: string) => `${name} agregada.`,
          removed: (name: string) => `${name} quitada.`,
          renamed: (name: string) => `Ahora se llama ${name}.`,
          gradesOn: (name: string) => `${name} usa grados.`,
          gradesOff: (name: string) => `${name} no usa grados.`,
          taken: 'Ya hay una actividad con ese nombre.',
          required: 'Escribe el nombre.',
          failed: 'No pudimos guardar el cambio. Inténtalo de nuevo.',
          error: 'No pudimos cargar las actividades.',
        },
        logo: {
          title: 'Logo',
          get hint() {
            return `Se muestra en un círculo junto al nombre ${w.ofThePlace}: en la app, la página ${w.ofTheMember}, la entrada, la inscripción y los correos. PNG, JPEG o WebP, de hasta 5 MB.`
          },
          current: 'Así se ve el logo.',
          get none() {
            return `Sin logo: se muestran las iniciales ${w.ofThePlace}.`
          },
          upload: 'Subir logo',
          replace: 'Cambiar logo',
          remove: 'Quitar logo',
          removing: 'Quitando…',
          cropHint: 'Arrastra la imagen para encuadrarla en el círculo, o muévela con las flechas, y acércala con el control.',
          frame: 'Encuadre del logo',
          zoom: 'Acercar',
          save: 'Guardar logo',
          saving: 'Subiendo…',
          cancel: 'Cancelar',
          saved: 'Logo guardado.',
          removed: 'Logo quitado.',
          refused: {
            type: 'Ese archivo no es una imagen PNG, JPEG o WebP. Los SVG no se aceptan.',
            tooLarge: 'La imagen pesa más de 5 MB. Elige una más liviana.',
            unreadable: 'No pudimos leer esa imagen. Prueba con otro archivo.',
            failed: 'No pudimos guardar el logo. Inténtalo de nuevo.',
          },
          removeFailed: 'No pudimos quitar el logo. Inténtalo de nuevo.',
        },
        billing: 'Cobro',
        graceDays: 'Días de gracia',
        get graceDaysHint() {
          return `Días después del vencimiento de un pago antes de que el plan ${w.ofTheMember} caduque.`
        },
        reminderEveryDays: 'Recordar cada (días)',
        reminderEveryDaysHint: 'Los recordatorios de pago vencido salen el día del vencimiento y luego cada tantos días.',
        channels: 'Canales',
        email: 'El correo está siempre activo: lleva los avisos y los links de acceso.',
        whatsapp: 'Recordatorios por WhatsApp',
        summaryEmail: 'Resumen del mes por correo',
        summaryEmailHint: 'Al comenzar cada mes, el titular recibe lo que pasó el mes anterior después de los recordatorios.',
        bank: 'Datos bancarios',
        get bankHint() {
          return `Es lo que ven ${w.theMembers} para pagar por transferencia. Deja todos los campos vacíos para quitarlos.`
        },
        bankName: 'Banco',
        accountType: 'Tipo de cuenta',
        holder: 'Titular',
        rut: 'RUT del titular',
        number: 'Número de cuenta',
        bankEmail: 'Correo para avisos de transferencia (opcional)',
        privacy: 'Datos de privacidad',
        get privacyHint() {
          return `${w.ThePlace} es responsable de los datos de sus ${w.members} (Ley 21.719). Estos datos completan su política de privacidad, que se enlaza en el formulario de inscripción y en la página ${w.ofTheMember}. El link de inscripción funciona solo con ellos.`
        },
        privacyLegalName: 'Razón social',
        get privacyRut() {
          return `RUT ${w.ofThePlace}`
        },
        privacyEmail: 'Correo para solicitudes sobre datos personales',
        privacyAddress: 'Dirección (opcional)',
        privacyView: 'Ver política de privacidad',
        choose: 'Elige…',
        submit: 'Guardar',
        working: 'Guardando…',
        saved: 'Guardado.',
        invalid: 'Revisa los campos marcados.',
        failed: 'No pudimos guardar. Inténtalo de nuevo.',
        range: {
          grace_days: 'Entre 0 y 60 días.',
          reminder_every_days: 'Entre 1 y 30 días.',
        } as Record<string, string>,
        value: {
          timezone: 'No es una zona horaria válida.',
          'bank_account.rut': 'RUT no válido.',
          'bank_account.email': 'Correo no válido.',
          'bank_account.number': 'Solo dígitos y guiones.',
          'privacy.rut': 'RUT no válido.',
          'privacy.email': 'Correo no válido.',
        } as Record<string, string>,
      },
      plans: {
        title: 'Planes',
        error: 'No pudimos cargar los planes.',
        get empty() {
          return `Todavía no hay planes. Crea el primero para inscribir ${w.members}.`
        },
        add: 'Nuevo plan',
        edit: 'Editar',
        deactivate: 'Desactivar',
        reactivate: 'Reactivar',
        inactive: 'Inactivo',
        anyProgram: 'Cualquier programa',
        row: (first: string, second: string) => `${first} · ${second}`,
        kinds: {
          monthly: 'Mensual',
          prepaid: 'Prepago',
          fixed_period: 'Período fijo',
          credits: 'Paquete de clases',
          dropin: 'Clase suelta',
          trial: 'Prueba',
        },
        anchors: { signup: 'El día de inscripción', first: 'El día 1 de cada mes' },
        summary: {
          monthly: (price: string) => `${price} al mes`,
          prepaid: (price: string, months: number) => `${price} por ${months === 1 ? '1 mes' : `${months} meses`}`,
          fixed_period: (price: string, start: string, end: string) => `${price} del ${start} al ${end}`,
          credits: (price: string, credits: number, days: number) =>
            `${price} por ${credits === 1 ? '1 clase' : `${credits} clases`} · vencen en ${days === 1 ? '1 día' : `${days} días`}`,
          dropin: (price: string) => `${price} por clase`,
          enrolment: (fee: string) => `matrícula ${fee}`,
          trial: (classes: number | null, days: number | null) =>
            ['Gratis', classes === null ? null : classes === 1 ? '1 clase' : `${classes} clases`, days === null ? null : days === 1 ? '1 día' : `${days} días`]
              .filter((part) => part !== null)
              .join(' · '),
        },
        form: {
          create: 'Nuevo plan',
          edit: (name: string) => `Editar ${name}`,
          kind: 'Tipo de plan',
          name: 'Nombre',
          program: 'Programa',
          inactiveProgram: (name: string) => `${name} (desactivado)`,
          price: 'Precio (CLP)',
          enrolmentFee: 'Matrícula (CLP)',
          enrolmentHint: 'Opcional. Se cobra una vez, como cobro extra, a quien empieza el plan; no al reactivarlo ni al cambiarse a él.',
          anchor: 'Día de cobro',
          periodMonths: 'Meses que cubre',
          periodStart: 'Desde',
          periodEnd: 'Hasta',
          get periodHint() {
            return `Las mismas fechas para ${w.memberIs('todos', 'todas')} ${w.theMembers}, se inscriban cuando se inscriban. Quien entra después paga el precio completo.`
          },
          credits: 'Clases incluidas',
          creditExpiryDays: 'Vencen a los (días)',
          freeClasses: 'Clases gratis',
          freeDays: 'Días gratis',
          trialHint: 'La prueba dura esas clases, esos días, o lo que se cumpla primero.',
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          invalid: 'Revisa los campos marcados.',
          trialLimit: 'Indica las clases gratis, los días gratis o ambos.',
          failed: 'No pudimos guardar el plan. Inténtalo de nuevo.',
          range: {
            price_clp: 'Entre $0 y $100.000.000.',
            enrolment_fee_clp: 'Entre $1 y $100.000.000, o vacía para no cobrar matrícula.',
            period_months: 'Debe ser mayor que 0.',
            credits: 'Debe ser mayor que 0.',
            credit_expiry_days: 'Debe ser mayor que 0.',
            free_classes: 'Debe ser mayor que 0.',
            free_days: 'Debe ser mayor que 0.',
          } as Record<string, string>,
          value: {
            unknown_program: 'Ese programa no existe.',
            inactive_program: 'Ese programa está desactivado.',
            period_order: 'Debe ser igual o posterior a la fecha de inicio.',
            date_parsing: 'Indica una fecha.',
            date_from_datetime_parsing: 'Indica una fecha.',
          } as Record<string, string>,
        },
        nextPeriod: {
          open: 'Duplicar para el próximo período',
          title: (name: string) => `Próximo período de ${name}`,
          get intro() {
            return `Se crea un plan nuevo con estas fechas, y ${w.theMembers} que marques pasan a él cuando termine lo que ya pagaron. Este plan no se renueva solo.`
          },
          get members() {
            return `${w.Members} que pasan al nuevo período`
          },
          loading: 'Cargando…',
          error: 'No pudimos cargar la lista.',
          get none() {
            return `Este plan no tiene ${w.members} ${w.memberIs('activos', 'activas')}.`
          },
          frozen: 'plan congelado',
          pending: (plan: string) => `ya cambia a ${plan}`,
          submit: 'Crear y pasar',
          working: 'Creando…',
          failed: 'No pudimos crear el próximo período. Inténtalo de nuevo.',
          afterPeriod: (end: string) => `Debe ser posterior al ${end}, cuando termina este período.`,
          notOnPlan: 'Alguien de la lista ya no está en este plan. Vuelve a abrir el formulario.',
          done: (name: string, moved: number) =>
            `Plan ${name} creado. ${moved === 0 ? 'Nadie pasa a él todavía.' : `${w.memberCount(moved)} ${moved === 1 ? 'pasa' : 'pasan'} a él.`}`,
        },
        created: (name: string) => `Plan ${name} creado.`,
        saved: (name: string) => `Plan ${name} guardado.`,
        deactivated: (name: string) => `Plan ${name} desactivado. ${w.TheMembers} que ya lo tienen lo mantienen.`,
        reactivated: (name: string) => `Plan ${name} reactivado.`,
        toggleFailed: 'No pudimos cambiar el plan. Inténtalo de nuevo.',
      },
      programs: {
        title: 'Programas y clases',
        error: 'No pudimos cargar los programas y las clases.',
        empty: 'Todavía no hay programas. Crea uno, como Adultos o Kids, y luego sus clases.',
        add: 'Nuevo programa',
        rename: 'Renombrar',
        edit: 'Editar',
        deactivate: 'Desactivar',
        reactivate: 'Reactivar',
        inactive: 'Inactivo',
        noClassTypes: 'Este programa todavía no tiene clases.',
        addClassType: 'Nueva clase',
        classTypesLabel: (program: string) => `Clases de ${program}`,
        // What one attendance takes off a pack of classes (#177: "clase", not "crédito").
        credits: (n: number) => (n === 0 ? 'No descuenta clases' : n === 1 ? 'Descuenta 1 clase' : `Descuenta ${n} clases`),
        get openMat() {
          return w.OpenMat
        },
        openAccess: 'Acceso libre',
        notCounted: 'No cuenta como clase',
        toggleFailed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
        programForm: {
          create: 'Nuevo programa',
          rename: (name: string) => `Renombrar ${name}`,
          name: 'Nombre del programa',
        },
        classTypeForm: {
          create: (program: string) => `Nueva clase en ${program}`,
          edit: (name: string) => `Editar ${name}`,
          name: 'Nombre de la clase',
          program: 'Programa',
          inactiveProgram: (name: string) => `${name} (desactivado)`,
          creditCost: 'Clases que descuenta',
          creditCostHint: 'Lo que descuenta cada asistencia de un paquete de clases. 0 para una clase gratis.',
          kind: 'Tipo',
          // The open mat under the gym's name for it (#346): "Open mat", "Escalada libre".
          kinds: {
            class: 'Clase',
            get open_mat() {
              return w.OpenMat
            },
            open_access: 'Acceso libre',
          },
          get kindHint() {
            return `${w.OpenMat}: solo rounds de ${w.practice}, sin bloques de técnica. Acceso libre es sin clases: cada visita se marca en Entrada, a cualquier hora.`
          },
          countsAsClass: 'Cuenta como clase',
          get countsAsClassHint() {
            return `Si asistir suma a las clases ${w.ofTheMember}, y a su meta de graduación si ${w.thePlace} usa grados.`
          },
          activity: 'Actividad',
          get activityHint() {
            return `Opcional: a qué actividad ${w.ofThePlace} pertenece esta clase.`
          },
          noActivity: 'Ninguna',
        },
        cancel: 'Cancelar',
        submit: 'Guardar',
        working: 'Guardando…',
        invalid: 'Revisa los campos marcados.',
        failed: 'No pudimos guardar. Inténtalo de nuevo.',
        programTaken: 'Ya hay un programa con ese nombre.',
        classTypeTaken: 'Este programa ya tiene una clase con ese nombre.',
        range: { credit_cost: 'Entre 0 y 100 clases.' } as Record<string, string>,
        value: {
          unknown_program: 'Ese programa no existe.',
          inactive_program: 'Ese programa está desactivado. Reactívalo o elige otro.',
        } as Record<string, string>,
        programCreated: (name: string) => `Programa ${name} creado.`,
        programRenamed: (name: string) => `Programa renombrado a ${name}.`,
        programDeactivated: (name: string) =>
          `Programa ${name} desactivado. Sus clases y planes lo mantienen, pero no se le pueden agregar nuevos.`,
        programReactivated: (name: string) => `Programa ${name} reactivado.`,
        classTypeCreated: (name: string) => `Clase ${name} creada.`,
        classTypeSaved: (name: string) => `Clase ${name} guardada.`,
        classTypeDeactivated: (name: string) => `Clase ${name} desactivada. Las clases ya dadas la mantienen.`,
        classTypeReactivated: (name: string) => `Clase ${name} reactivada.`,
      },
      schedule: {
        title: 'Horario',
        intro:
          'Las clases fijas de cada semana. Rakin las crea con dos semanas de anticipación, así aparecen en Clases antes de empezar.',
        error: 'No pudimos cargar el horario.',
        empty: 'Todavía no hay clases fijas.',
        add: 'Nueva clase fija',
        edit: 'Editar',
        delete: 'Eliminar',
        deleteYes: 'Sí, eliminar',
        deleteConfirm:
          'Se borran las próximas clases de este horario que no tengan asistencia. Las que ya se hicieron quedan como clases sueltas.',
        deleteFailed: 'No pudimos eliminarla. Inténtalo de nuevo.',
        inactive: 'Tipo desactivado: no crea clases',
        // ISO weekdays, Monday first.
        weekdays: ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
        row: (days: string, time: string, classType: string) => `${days} ${time} · ${classType}`,
        detail: (program: string, coach: string, topic: string | null, tags: string[] = []) =>
          [program, coach, topic, ...tags].filter(Boolean).join(' · '),
        validity: (from: string | null, to: string | null) =>
          from && to ? `Del ${from} al ${to}` : from ? `Desde el ${from}` : to ? `Hasta el ${to}` : 'Todas las semanas',
        created: (name: string) => `Clase fija de ${name} creada. Sus clases ya están en Clases.`,
        saved: (name: string) => `Horario de ${name} actualizado.`,
        deleted: (name: string) => `Clase fija de ${name} eliminada.`,
        form: {
          create: 'Nueva clase fija',
          edit: (name: string) => `Editar ${name}`,
          classType: 'Tipo de clase',
          inactiveType: (name: string) => `${name} (desactivado)`,
          weekdays: 'Días',
          noDays: 'Elige al menos un día.',
          time: 'Hora',
          duration: 'Duración (min)',
          badDuration: 'La duración va de 1 a 1440 minutos.',
          coach: 'Coach',
          topic: 'Tema (opcional)',
          topicHint: 'El tema con que parte cada clase; el coach lo puede cambiar.',
          tags: 'Etiquetas (opcional)',
          tagsHint: 'Las etiquetas con que parte cada clase; el coach las puede cambiar.',
          archivedTag: 'Una de las etiquetas está archivada: quítala.',
          validFrom: 'Desde',
          fromDate: 'A partir de',
          fromHint: 'Las clases antes de esta fecha, y las ya hechas o con asistencia, no cambian.',
          validTo: 'Hasta (opcional)',
          validToHint: 'Vacío: todas las semanas.',
          endsTooSoon: 'Termina antes de empezar.',
          noClassTypes: 'Primero crea un tipo de clase en Programas y clases.',
          afterEnd: 'Esta clase fija ya terminó en esa fecha.',
          get openMatPlan() {
            return `Una clase de tipo ${w.OpenMat} es un solo bloque de ${w.practice}, y alguna de las próximas clases tiene otro registro en el timer. Corrígelo antes.`
          },
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          invalid: 'Revisa los campos.',
          failed: 'No pudimos guardar. Inténtalo de nuevo.',
        },
        closed: {
          title: 'Días cerrados',
          intro: 'Feriados y otros días sin clases: ese día no se crea ninguna clase del horario.',
          add: 'Cerrar día',
          day: 'Fecha',
          label: 'Motivo (opcional)',
          labelPlaceholder: 'Ej.: Feriado',
          past: 'Elige hoy o un día que venga.',
          empty: 'No hay días cerrados próximos.',
          error: 'No pudimos cargar los días cerrados.',
          reopen: 'Abrir',
          closedDone: (day: string) => `${day}: cerrado. Sus clases del horario se quitaron.`,
          reopened: (day: string) => `${day}: abierto otra vez.`,
          failed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
        },
      },
      blocks: {
        title: 'Bloques de clase',
        get intro() {
          return `Las partes en que ${w.theCoach} divide la clase con el cronómetro, en el orden en que se ofrecen. El tiempo de los bloques de ${w.practice} suma al total de ${w.practice} de cada ${w.member}.`
        },
        error: 'No pudimos cargar los bloques.',
        empty: 'Todavía no hay bloques.',
        add: 'Nuevo bloque',
        edit: 'Editar',
        // Desactivar, as in Planes and Programas (#177).
        archive: 'Desactivar',
        restore: 'Reactivar',
        delete: 'Eliminar',
        archived: 'Inactivo',
        // The tag on a kind that counts as the practice: run in rounds, whatever its name (#346).
        sparring: 'En rounds',
        upMark: '↑',
        downMark: '↓',
        up: (name: string) => `Subir ${name}`,
        down: (name: string) => `Bajar ${name}`,
        created: (name: string) => `Bloque ${name} creado.`,
        saved: (name: string) => `Bloque ${name} guardado.`,
        deleted: (name: string) => `Bloque ${name} eliminado.`,
        archivedDone: (name: string) => `Bloque ${name} desactivado. El tiempo ya registrado se mantiene.`,
        restored: (name: string) => `Bloque ${name} reactivado.`,
        inUse: (blocks: number) =>
          `Ya se usó en ${blocks === 1 ? '1 bloque' : `${blocks} bloques`} de clases: desactívalo en vez de eliminarlo.`,
        toggleFailed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
        reorderFailed: 'No pudimos cambiar el orden. Inténtalo de nuevo.',
        form: {
          create: 'Nuevo bloque',
          edit: (name: string) => `Editar ${name}`,
          name: 'Nombre',
          get sparring() {
            return `Cuenta como ${w.practice}`
          },
          get sparringHint() {
            return `Un bloque de ${w.practice} se corre en rounds, y su tiempo suma al total de ${w.practice} ${w.ofTheMember}.`
          },
          sparringInUse: (blocks: number) =>
            `Ya se usó en ${blocks === 1 ? '1 bloque' : `${blocks} bloques`} de clases, así que no puede cambiar si cuenta como ${w.practice}.`,
          taken: 'Ya hay un bloque con ese nombre.',
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          invalid: 'Revisa los campos marcados.',
          failed: 'No pudimos guardar el bloque. Inténtalo de nuevo.',
          range: {} as Record<string, string>,
          value: {} as Record<string, string>,
        },
      },
      tags: {
        title: 'Etiquetas',
        get intro() {
          return `Los focos que se repiten de una clase a otra, como Pasaje de guardia o Fuerza. El coach los marca en cada clase, y suman las horas de cada ${w.member} y ${w.ofThePlace}.`
        },
        error: 'No pudimos cargar las etiquetas.',
        empty: 'Todavía no hay etiquetas.',
        add: 'Nueva etiqueta',
        // Archivar, not Desactivar: it stays on the classes that have it.
        archive: 'Archivar',
        restore: 'Reactivar',
        archived: 'Archivada',
        archiveHint: 'Una etiqueta archivada sigue en las clases que la tienen y suma sus horas, pero no se puede poner en clases nuevas.',
        restoreHint: 'Reactivada, se puede poner otra vez en las clases.',
        created: (name: string) => `Etiqueta ${name} creada.`,
        saved: (name: string) => `Etiqueta ${name} guardada.`,
        archivedDone: (name: string) => `Etiqueta ${name} archivada. Sigue en sus clases y en sus horas.`,
        restored: (name: string) => `Etiqueta ${name} reactivada.`,
        toggleFailed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
        form: {
          create: 'Nueva etiqueta',
          edit: (name: string) => `Editar ${name}`,
          name: 'Nombre',
          nameHint: 'Ej.: Pasaje de guardia, Fuerza, Fuerza de dedos.',
          taken: 'Ya hay una etiqueta con ese nombre.',
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          invalid: 'Revisa los campos marcados.',
          failed: 'No pudimos guardar la etiqueta. Inténtalo de nuevo.',
          range: {} as Record<string, string>,
          value: {} as Record<string, string>,
        },
      },
      staff: {
        title: 'Equipo',
        error: 'No pudimos cargar el equipo.',
        intro: 'Quién está en el equipo y qué puede hacer.',
        add: 'Invitar',
        // What each permission is called in Cargos and "Puede:", with its line of help.
        permissions: {
          money_read: 'Ver ingresos',
          money_write: 'Registrar pagos',
          expenses_read: 'Ver gastos',
          expenses_write: 'Registrar gastos',
          get members_manage() {
            return `Gestionar ${w.members}`
          },
          get members_add() {
            return `Agregar ${w.members}`
          },
          attendance: 'Tomar asistencia',
          get gym_setup() {
            return `Configurar ${w.thePlace}`
          },
          team_manage: 'Gestionar equipo',
        } as Record<string, string>,
        // Short, for the 1280 table's head.
        short: {
          money_read: 'Ingresos',
          money_write: 'Pagos',
          expenses_read: 'Gastos',
          expenses_write: 'Reg. gastos',
          get members_manage() {
            return w.Members
          },
          members_add: 'Agregar',
          attendance: 'Asistencia',
          gym_setup: 'Configurar',
          team_manage: 'Equipo',
        } as Record<string, string>,
        help: {
          money_read: 'Pagos, el Libro, los montos y la exportación.',
          money_write: 'Registra y valida pagos, corrige cobros y cambia planes. Incluye ver ingresos.',
          expenses_read: 'Gastos y Finanzas. Incluye sueldos y honorarios.',
          expenses_write: 'Registra, corrige y anula gastos. Incluye ver gastos.',
          get members_manage() {
            return `Grupos, el link de inscripción, dar de baja. Incluye agregar ${w.members}.`
          },
          get members_add() {
            return `Agrega ${w.members} sin plan y lleva su ficha.`
          },
          attendance: 'Toma asistencia en las clases que dirige.',
          get gym_setup() {
            return 'Planes y precios, programas, horario, ajustes y datos bancarios.'
          },
          team_manage: 'Invita, nombra y termina cargos; crea y edita cargos.',
        } as Record<string, string>,
        people: {
          title: 'Personas',
          titular: 'Titular de la cuenta',
          noRole: 'Sin cargo',
          until: (month: string) => `hasta ${month}`,
          from: (day: string) => `desde ${day}`,
          name: 'Nombre',
          roles: 'Cargos',
          term: 'Período',
          can: 'Puede',
          all: 'Todo',
          count: (n: number, of: number) => `${n} de ${of}`,
          open: '…',
        },
        panel: {
          close: 'Cerrar',
          from: 'Desde',
          until: 'Hasta (opcional)',
          untilHint: 'El primer día sin el cargo.',
          saveDates: 'Guardar fechas',
          datesSaved: (role: string) => `Fechas de ${role} corregidas.`,
          end: 'Terminar cargo',
          confirmEnd: (role: string, name: string) => `¿Terminar hoy el cargo de ${role} de ${name}?`,
          confirm: 'Sí, terminar',
          ended: (role: string, name: string) => `${name} ya no es ${role}.`,
          add: 'Agregar cargo',
          role: 'Cargo',
          appoint: 'Agregar',
          appointed: (role: string, name: string) => `${name} ahora es ${role}.`,
          can: 'Puede:',
          nothing: 'Nada por ahora: aparece en el equipo.',
          canAll: 'Todo, como titular de la cuenta.',
          overlaps: 'Ya tiene ese cargo en esas fechas.',
          badTerm: '“Hasta” va después de “Desde”.',
          noneToGive: 'No hay cargos que puedas darle.',
        },
        titles: {
          title: 'Cargos',
          empty: 'Todavía no hay cargos. Crea uno o agrega una plantilla.',
          none: 'Sin permisos',
          add: 'Nuevo cargo',
          addPreset: 'Agregar plantilla',
          presetAdded: (n: number) =>
            n === 0 ? 'Ya tenías todos los cargos de esa plantilla.' : n === 1 ? 'Agregamos 1 cargo.' : `Agregamos ${n} cargos.`,
          fromPreset: (preset: string) => `de la plantilla ${preset}`,
          holders: (n: number) => (n === 1 ? '1 persona' : `${n} personas`),
          form: {
            title: 'Nuevo cargo',
            name: 'Nombre',
            nameHint: 'Como lo llaman en el club: Tesorera, Encargado de cobranza.',
            get public() {
              return `Visible para ${w.theMembers}`
            },
            get publicHint() {
              return `Aparece en la página de ${w.theMembers}, con su nombre.`
            },
            permissions: 'Permisos',
            notYours: 'Solo das permisos que tú tienes, y no todos los tuyos.',
            implied: (what: string) => `Viene con ${what}.`,
          },
          save: 'Guardar',
          saved: (name: string) => `Cargo ${name} guardado.`,
          created: (name: string) => `Creamos el cargo ${name}.`,
          widens: (holders: string, what: string) => `${holders} podrán ${what}.`,
          widensConfirm: 'Guardar igual',
          archive: 'Archivar',
          confirmArchive: (name: string) => `¿Archivar ${name}? Sale de los cargos, y el historial lo mantiene.`,
          confirm: 'Sí, archivar',
          archived: (name: string) => `Archivamos ${name}.`,
          held: 'Alguien tiene este cargo: termina sus cargos antes de archivarlo.',
          nameTaken: 'Ya hay un cargo con ese nombre.',
          notAllowed: 'Ese cargo tiene permisos que no puedes dar.',
        },
        // Rakin's names for its presets (backend `app.permissions.PRESETS`), whatever the
        // gym calls itself.
        presets: {
          academia: 'Academia',
          club_federado: 'Club federado',
        } as Record<string, string>,
        presetRoles: {
          academia: 'Administrador y Coach.',
          club_federado: 'Presidente, Tesorero, Secretario, Director, Delegado y Coach.',
        } as Record<string, string>,
        setup: {
          title: '¿Cómo se organiza tu equipo?',
          intro: 'Elige una plantilla de cargos para empezar. Después cambias, agregas o archivas los que quieras.',
          none: 'Sin plantilla',
          noneHint: 'Creo los cargos yo.',
          choose: (preset: string) => `Usar ${preset}`,
          chosen: 'Listo. Ahora invita a tu equipo.',
        },
        history: {
          title: 'Historial',
          empty: 'Todavía no hay cargos en el historial.',
          term: (from: string, until: string | null) => (until ? `${from} – ${until}` : `desde ${from}`),
          never: 'no llegó a empezar',
        },
        form: {
          title: 'Invitar al equipo',
          name: 'Nombre',
          rut: 'RUT (opcional)',
          rutHint: 'Si no tiene RUT, el correo lo identifica.',
          phone: 'Teléfono (opcional)',
          email: 'Correo',
          emailHint: 'Le enviamos un link para entrar. Siempre entra con este correo, sin contraseña.',
          roles: 'Cargos',
          rolesHint: 'Uno o más. Solo los que puedes dar.',
          rolesNeeded: 'Elige al menos un cargo.',
          from: 'Desde',
          until: 'Hasta (opcional)',
        },
        cancel: 'Cancelar',
        submit: 'Enviar invitación',
        working: 'Guardando…',
        invalid: 'Revisa los campos marcados.',
        failed: 'No pudimos enviar la invitación. Inténtalo de nuevo.',
        alreadyStaff: 'Esa persona ya está en el equipo.',
        get emailTaken() {
          return `Ese correo ya es de otra persona ${w.ofThePlace}.`
        },
        range: {} as Record<string, string>,
        value: {
          phone: 'Escribe un teléfono válido, como +56 9 1234 5678.',
          rut: 'RUT no válido: revisa el dígito verificador.',
          email: 'Correo no válido.',
        } as Record<string, string>,
        invited: (name: string, email: string) => `Invitamos a ${name}. Le llegará un link a ${email}.`,
        actionFailed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
      },
      joinLink: {
        title: 'Link de inscripción',
        error: 'No pudimos cargar el link de inscripción.',
        get intro() {
          return `Un link para compartir por WhatsApp o donde quieras: cada persona llena sus datos y la solicitud te espera en Hoy y en ${w.Members} para aprobarla.`
        },
        none: 'Todavía no tienes un link.',
        needsPrivacy: 'Completa los datos de privacidad en Ajustes antes de activar el link.',
        needsPrivacyLink: 'Ir a Datos de privacidad',
        program: 'Programa',
        programHint: 'Opcional: el programa al que se inscriben con este link.',
        anyProgram: 'Ninguno en particular',
        expiresOn: 'Válido hasta',
        expiresOnHint: 'Opcional: el último día en que el link funciona.',
        generate: 'Generar link',
        working: 'Guardando…',
        save: 'Guardar cambios',
        saved: 'Cambios guardados.',
        linkLabel: 'Link',
        copy: 'Copiar',
        copied: 'Link copiado.',
        share: 'Compartir por WhatsApp',
        shareText: (gym: string, url: string) => `Inscríbete en ${gym} llenando tus datos aquí: ${url}`,
        expired: (day: string) => `Venció el ${day}: quien lo abra verá que ya no es válido.`,
        validUntil: (day: string) => `Válido hasta el ${day}.`,
        regenerate: 'Generar otro link',
        confirmRegenerate: 'El link actual dejará de funcionar. ¿Generar otro?',
        regenerated: 'Listo: el link anterior ya no funciona.',
        revoke: 'Desactivar link',
        confirmRevoke: 'El link dejará de funcionar. Las solicitudes ya enviadas se mantienen. ¿Desactivarlo?',
        revoked: 'Link desactivado.',
        confirm: 'Sí',
        cancel: 'Cancelar',
        failed: 'No pudimos hacer el cambio. Inténtalo de nuevo.',
        invalid: 'Revisa los campos marcados.',
        range: {} as Record<string, string>,
        value: { unknown_program: 'Ese programa ya no existe.' } as Record<string, string>,
      },
      grading: {
        title: 'Graduación',
        error: 'No pudimos cargar el esquema de graduación.',
        // With no activity that grades (#245): the screen says where to turn it on.
        get off() {
          return `Ninguna actividad de tu ${w.place} usa grados, así que los cinturones y niveles no aparecen en la app.`
        },
        turnOn: 'Activa «Usa grados» en una actividad',
        get activitiesError() {
          return `No pudimos revisar las actividades de tu ${w.place}.`
        },
        // One scheme for every activity that grades, for now.
        shared: (names: string[]) =>
          `Este esquema es el mismo para ${names.slice(0, -1).join(', ')} y ${names.at(-1)}: cada ${w.member} tiene un solo grado.`,
        stale: 'El esquema guardado ya no es válido. Vuelve a usar una escala para repararlo y guarda.',
        presetsError: 'No pudimos cargar las escalas.',
        start: 'Punto de partida',
        preset: 'Escala',
        presetHint: 'Reemplaza lo que estás editando. Nada cambia hasta que guardes.',
        choosePreset: 'Elige una escala…',
        apply: 'Usar esta escala',
        reapply: 'Volver a usar una escala',
        applied: (preset: string) => `Escala ${preset} aplicada. Revísala y guarda.`,
        goalMetric: 'Cómo se mide el avance',
        goalMetricHint: 'Lo que cuenta el objetivo de cada grado para la siguiente graduación.',
        goalMetrics: {
          none: 'No medir',
          classes_since_promotion: 'Clases desde la última graduación',
          time_in_rank: 'Meses en el grado',
        },
        ladders: { ranks: 'Grados', kids_ladder: 'Escalera infantil' },
        laddersHint: {
          ranks: 'Del más bajo al más alto.',
          kids_ladder: 'Opcional: los grados de los niños, si tienen una escalera propia.',
        },
        emptyLadder: 'Sin grados.',
        addRank: 'Agregar grado',
        rank: (n: number) => `Grado ${n}`,
        rankLabel: 'Nombre',
        target: {
          classes_since_promotion: 'Clases para la siguiente',
          time_in_rank: 'Meses para la siguiente',
        },
        targetHint: 'Opcional. Un subgrado sin objetivo propio usa el de su grado.',
        // The same, on a sub-rank's narrow row.
        subTarget: { classes_since_promotion: 'Clases', time_in_rank: 'Meses' },
        // A closed rank's line (#177): what it takes to the next, and its sub-ranks.
        summary: {
          classes_since_promotion: (n: number) => (n === 1 ? '1 clase para la siguiente' : `${n} clases para la siguiente`),
          time_in_rank: (n: number) => (n === 1 ? '1 mes para la siguiente' : `${n} meses para la siguiente`),
        },
        refusedRank: 'Revisa este grado.',
        done: 'Listo',
        subRanks: (n: number) => (n === 0 ? 'Sin subgrados' : n === 1 ? '1 subgrado' : `${n} subgrados`),
        subRank: (n: number) => `Subgrado ${n}`,
        subRankLabel: 'Nombre del subgrado',
        addSubRank: 'Agregar subgrado',
        // A rank's belt colours (#135); without them it shows as its name.
        belt: {
          title: 'Cinturón',
          none: 'Sin color: el grado se muestra con su nombre.',
          add: 'Agregar color',
          main: 'Color',
          tone: 'Franja',
          addTone: 'Agregar franja',
          removeTone: 'Quitar franja',
          remove: 'Quitar color',
          preview: (label: string) => `Vista previa del cinturón ${label}`,
        },
        // The editor's words while no rank has colours (#353): levels, not belts, and a
        // sub-rank is no stripe. Over the ones above.
        levels: {
          goalMetricHint: 'Lo que cuenta el objetivo de cada nivel para pasar al siguiente.',
          goalMetrics: { time_in_rank: 'Meses en el nivel' },
          ladders: { ranks: 'Niveles' },
          laddersHint: { kids_ladder: 'Opcional: los niveles de los niños, si tienen una escalera propia.' },
          emptyLadder: 'Sin niveles.',
          addRank: 'Agregar nivel',
          rank: (n: number) => `Nivel ${n}`,
          target: {
            classes_since_promotion: 'Clases para el siguiente',
            time_in_rank: 'Meses para el siguiente',
          },
          targetHint: 'Opcional. Un subnivel sin objetivo propio usa el de su nivel.',
          summary: {
            classes_since_promotion: (n: number) => (n === 1 ? '1 clase para el siguiente' : `${n} clases para el siguiente`),
            time_in_rank: (n: number) => (n === 1 ? '1 mes para el siguiente' : `${n} meses para el siguiente`),
          },
          refusedRank: 'Revisa este nivel.',
          subRanks: (n: number) => (n === 0 ? 'Sin subniveles' : n === 1 ? '1 subnivel' : `${n} subniveles`),
          subRank: (n: number) => `Subnivel ${n}`,
          addSubRank: 'Agregar subnivel',
          belt: { title: 'Color', none: 'Sin color: el nivel se muestra con su nombre.' },
          unnamed: 'nivel sin nombre',
          schemeInvalid: 'El esquema no es válido: para medir el avance necesita al menos un nivel.',
        },
        moveUp: (label: string) => `Subir ${label}`,
        moveDown: (label: string) => `Bajar ${label}`,
        remove: (label: string) => `Quitar ${label}`,
        unnamed: 'grado sin nombre',
        submit: 'Guardar esquema',
        working: 'Guardando…',
        saved: 'Esquema guardado.',
        invalid: 'Revisa los campos marcados.',
        schemeInvalid: 'El esquema no es válido: para medir el avance necesita al menos un grado.',
        failed: 'No pudimos guardar el esquema. Inténtalo de nuevo.',
        range: { target: 'Entre 1 y 10.000.' } as Record<string, string>,
      },
      fields: {
        title: 'Campos personalizados',
        get intro() {
          return `Los datos que ${w.thePlace} anota de cada ${w.member}, además de los de siempre. Aparecen en la sección Datos de cada ${w.member}.`
        },
        error: 'No pudimos cargar los campos.',
        empty: 'Todavía no hay campos personalizados.',
        add: 'Nuevo campo',
        edit: 'Editar',
        // Desactivar, as in Planes and Programas (#177).
        archive: 'Desactivar',
        restore: 'Reactivar',
        archived: 'Inactivo',
        sensitive: 'Sensible',
        upMark: '↑',
        downMark: '↓',
        up: (label: string) => `Subir ${label}`,
        down: (label: string) => `Bajar ${label}`,
        row: (first: string, second: string) => `${first} · ${second}`,
        types: { text: 'Texto', number: 'Número', date: 'Fecha', enum: 'Lista de opciones' },
        visibleTo: { owner: 'Solo dueño', admin: 'Dueño y administradores', staff: 'Todo el staff' },
        created: (label: string) => `Campo ${label} creado.`,
        saved: (label: string) => `Campo ${label} guardado.`,
        archivedDone: (label: string) => `Campo ${label} desactivado. Sus datos se guardan, pero no se muestran.`,
        restored: (label: string) => `Campo ${label} reactivado.`,
        toggleFailed: 'No pudimos cambiar el campo. Inténtalo de nuevo.',
        reorderFailed: 'No pudimos cambiar el orden. Inténtalo de nuevo.',
        form: {
          create: 'Nuevo campo',
          edit: (label: string) => `Editar ${label}`,
          label: 'Nombre',
          type: 'Tipo',
          typeHint: 'El tipo no se puede cambiar después.',
          options: 'Opciones',
          optionsHint: 'Una opción por línea, en el orden en que se muestran.',
          sensitive: 'Dato sensible',
          sensitiveHint: 'Se guarda cifrado. Al marcarlo, por defecto solo lo ve el dueño.',
          // Shown once the owner marks a field sensitive (#384).
          get noHealth() {
            return `No lo uses para datos de salud (lesiones, enfermedades, tratamientos, medicamentos): la ley no permite que ${w.aPlace} los guarde, ni con el consentimiento ${w.ofTheMember}.`
          },
          visibleTo: 'Quién lo ve',
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          invalid: 'Revisa los campos marcados.',
          failed: 'No pudimos guardar el campo. Inténtalo de nuevo.',
          inUse: (options: Record<string, number>) =>
            `No puedes quitar opciones que hay ${w.members} usando: ${Object.entries(options)
              .map(([option, count]) => `${option} (${w.memberCount(count)})`)
              .join(', ')}. Cambia esos datos primero.`,
          range: {} as Record<string, string>,
          value: {
            options: 'Las opciones no se pueden repetir.',
          } as Record<string, string>,
          optionsRequired: 'Agrega al menos una opción.',
          optionsTooMany: 'Hasta 50 opciones.',
          optionTooLong: 'Cada opción tiene hasta 80 caracteres.',
        },
      },
      // "Requisitos" (#349): what the gym asks before someone trains.
      requirements: {
        title: 'Requisitos',
        get intro() {
          return `Lo que ${w.thePlace} pide antes de entrenar, como una declaración de riesgos o un certificado. La ficha de cada ${w.member} dice cuándo lo hizo y si está al día.`
        },
        error: 'No pudimos cargar los requisitos.',
        empty: 'Todavía no hay requisitos. Por ejemplo:',
        examples: ['Declaración de riesgos firmada', 'Inducción de seguridad', 'Certificado médico (12 meses)', 'Prueba de natación'],
        add: 'Nuevo requisito',
        archive: 'Desactivar',
        restore: 'Reactivar',
        archived: 'Inactivo',
        sensitive: 'Sensible',
        up: (name: string) => `Subir ${name}`,
        down: (name: string) => `Bajar ${name}`,
        row: (first: string, second: string) => `${first} · ${second}`,
        once: 'Una sola vez',
        months: (n: number) => (n === 1 ? 'Vence al mes' : `Vence a los ${n} meses`),
        visibleTo: { owner: 'Solo dueño', admin: 'Dueño y administradores', staff: 'Todo el staff' },
        created: (name: string) => `Requisito ${name} creado.`,
        saved: (name: string) => `Requisito ${name} guardado.`,
        archivedDone: (name: string) => `Requisito ${name} desactivado. Sus registros se guardan, pero no se muestran.`,
        restored: (name: string) => `Requisito ${name} reactivado.`,
        toggleFailed: 'No pudimos cambiar el requisito. Inténtalo de nuevo.',
        reorderFailed: 'No pudimos cambiar el orden. Inténtalo de nuevo.',
        form: {
          create: 'Nuevo requisito',
          edit: (name: string) => `Editar ${name}`,
          name: 'Nombre',
          validMonths: 'Vigencia en meses',
          validMonthsHint: 'En blanco si se hace una sola vez, como una declaración de riesgos.',
          sensitive: 'Dato sensible',
          sensitiveHint: 'Su nota se guarda cifrada. Al marcarlo, por defecto solo lo ve el dueño.',
          visibleTo: 'Quién lo ve',
          cancel: 'Cancelar',
          submit: 'Guardar',
          working: 'Guardando…',
          invalid: 'Revisa los campos marcados.',
          failed: 'No pudimos guardar el requisito. Inténtalo de nuevo.',
          range: { valid_months: 'Entre 1 y 120 meses.' } as Record<string, string>,
          value: {} as Record<string, string>,
        },
      },
    },
    session: {
      back: 'Volver a Clases',
      loading: 'Cargando clase…',
      error: 'No pudimos cargar la clase.',
      notFound: 'No encontramos esta clase.',
      retry: 'Reintentar',
      eyebrow: (program: string, time: string) => `${program} · ${time}`,
      coach: (name: string) => `Coach: ${name}`,
      form: {
        label: 'Tema y notas',
        topic: 'Tema de la clase',
        // Seen by every activity, so it names no sport's technique (#419).
        topicPlaceholder: 'Ej.: repaso de la técnica de la semana',
        tags: 'Etiquetas',
        // Where the gym's tags are made, for a class that has none to pick yet.
        get noTags() {
          return `${w.ThePlace} todavía no tiene etiquetas. El dueño o un admin las crea en Ajustes, Etiquetas.`
        },
        notes: 'Notas',
        get notesHint() {
          return `Solo las ve el equipo, nunca ${w.theMember}. ${NO_HEALTH}`
        },
        notesPlaceholder: 'Lo que conviene recordar de esta clase.',
        submit: 'Guardar',
        working: 'Guardando…',
        saved: 'Guardado.',
        failed: 'No pudimos guardar. Inténtalo de nuevo.',
        // What was typed when the session expired, back after signing in again (#212).
        restored: 'Recuperamos lo que habías escrito antes de que venciera tu sesión. Guárdalo para no perderlo.',
      },
      attendance: {
        title: 'Asistencia',
        // Of the regulars: who came to this class type in the last 30 days.
        count: (present: number, total: number) => `${present} de ${total}`,
        get search() {
          return `Buscar ${w.member}`
        },
        searchPlaceholder: 'Nombre o RUT',
        noMatches: 'Nadie con ese nombre o RUT.',
        others: (n: number, present: number) =>
          present > 0 ? `${w.memberIs('Otros', 'Otras')} ${w.members} (${n}) · ${present} presentes` : `${w.memberIs('Otros', 'Otras')} ${w.members} (${n})`,
        get othersLabel() {
          return `${w.memberIs('Otros', 'Otras')} ${w.members}`
        },
        hint: 'Toca un nombre para marcar presente. «Debe» es un pago vencido y «Requisito», uno pendiente o vencido, detallado bajo el nombre: puede entrenar igual, pero conviene avisar.',
        requirement: requirementFlag,
        get loading() {
          return `Cargando ${w.members}…`
        },
        get error() {
          return `No pudimos cargar ${w.theMembers}.`
        },
        empty: 'Nadie tiene un plan para esta clase todavía.',
        // The two marks on a row (#416): a word to see, a name to hear.
        owes: 'Debe',
        overdue: 'Pago vencido',
        requirementMark: 'Requisito',
        requirementName: 'Requisito pendiente o vencido',
        left: (n: number) => (n === 1 ? 'queda 1' : `quedan ${n}`),
        absent: (days: number) => `${days} d sin venir`,
        save: (n: number) => `Guardar asistencia (${n})`,
        // Nothing left to save: what is marked is what is saved, a trial guest included (#213).
        upToDate: (n: number) => (n === 1 ? '1 presente · guardado' : `${n} presentes · guardados`),
        working: 'Guardando…',
        done: 'Guardado ✓',
        saved: 'Asistencia guardada.',
        back: 'Volver a clases',
        queued: 'Sin conexión: quedó en este teléfono. Se guardará cuando vuelva la señal.',
        failed: 'No pudimos guardar la asistencia. Inténtalo de nuevo.',
        dropped: 'La asistencia que quedó pendiente no se pudo guardar. Revisa la lista y vuelve a marcar.',
        // Taps left unsaved when the roster was last open, given back (#416).
        kept: (n: number) => (n === 1 ? 'Tienes 1 marca sin guardar.' : `Tienes ${n} marcas sin guardar.`),
        discard: 'Descartar',
        // Unmarking a drop-in visit gives its charge back only while nothing was paid, the day it was added (#130).
        visitKept: {
          paid: 'La clase suelta ya está pagada: sigue presente. El dueño o un admin la devuelve en Pagos.',
          pending: 'Hay un comprobante esperando por esa clase suelta: sigue presente. Se revisa en Pagos.',
          past: 'Esa clase suelta se agregó otro día: sigue presente. El dueño o un admin la anula en Pagos.',
        },
        guest: {
          get open() {
            return `+ Agregar ${w.member} de prueba`
          },
          get label() {
            return `${w.Member} de prueba`
          },
          name: 'Nombre',
          who: 'RUT o correo',
          whoPlaceholder: '12.345.678-5',
          phone: 'Celular (WhatsApp)',
          phonePlaceholder: '9 1234 5678',
          plan: 'Plan de prueba',
          submit: 'Agregar y marcar presente',
          working: 'Agregando…',
          cancel: 'Cancelar',
          get noPlans() {
            return `Para agregar ${w.members} de prueba, el dueño o un admin crea un plan de prueba.`
          },
          done: (name: string) => `${name} quedó presente.`,
          member: (name: string) => `${name} ya es ${w.member}: lo marcamos presente.`,
          invalid: 'Revisa el RUT o el correo, y el celular: 9 dígitos, empezando por 9.',
          offline: 'Sin conexión: agrégalo cuando vuelva la señal.',
          hasLeft: 'Fue dado de baja: el dueño o un admin puede reactivarlo desde su ficha.',
          failed: 'No pudimos agregarlo. Inténtalo de nuevo.',
        },
        // "Clase suelta": someone paying for this one class (#130).
        visitor: {
          open: '+ Agregar visitante',
          label: 'Visitante',
          name: 'Nombre',
          phone: 'Celular (WhatsApp)',
          phonePlaceholder: '9 1234 5678',
          plan: 'Clase suelta',
          paid: 'Pago',
          unpaid: 'Pendiente',
          cash: 'Pagó en efectivo',
          transfer: 'Pagó por transferencia',
          submit: 'Agregar y marcar presente',
          working: 'Agregando…',
          cancel: 'Cancelar',
          noPlans: 'Para agregar visitantes, el dueño o un admin crea un plan de clase suelta.',
          done: (name: string) => `${name} quedó presente. La clase suelta queda en Pagos.`,
          paidDone: (name: string) => `${name} quedó presente, con la clase suelta pagada.`,
          member: (name: string) => `${name} ya está en la lista: lo marcamos presente.`,
          invalid: 'Revisa el nombre y el celular: 9 dígitos, empezando por 9.',
          offline: 'Sin conexión: agrégalo cuando vuelva la señal.',
          hasLeft: 'Fue dado de baja: el dueño o un admin puede reactivarlo desde su ficha.',
          failed: 'No pudimos agregarlo. Inténtalo de nuevo.',
        },
      },
      timer: {
        open: 'Abrir timer',
        resume: 'Volver al timer',
      },
      cancelled: {
        badge: 'Cancelada',
        note: 'Esta clase está cancelada: no se toma asistencia ni cuenta para nadie.',
      },
      edit: {
        open: 'Editar clase',
        label: 'Editar clase',
        day: 'Fecha',
        time: 'Hora',
        duration: 'Duración (min)',
        badDuration: 'La duración va de 1 a 1440 minutos.',
        scope: {
          label: '¿Qué cambias?',
          one: 'Solo esta clase',
          series: 'Esta y las siguientes',
          seriesHint:
            'Cambia el horario desde esta fecha. Las clases ya hechas o con asistencia no cambian, y las canceladas siguen canceladas.',
        },
        classType: 'Tipo de clase',
        coach: 'Coach',
        inactive: (name: string) => `${name} (desactivado)`,
        hint: 'La asistencia que ya se tomó se mantiene.',
        submit: 'Guardar cambios',
        working: 'Guardando…',
        close: 'Volver',
        saved: 'Clase actualizada.',
        failed: 'No pudimos guardar los cambios. Inténtalo de nuevo.',
        get openMatPlan() {
          return `Una clase de tipo ${w.OpenMat} es un solo bloque de ${w.practice}. Corrige el registro del timer antes de cambiarle el tipo.`
        },
      },
      manage: {
        title: 'Opciones de la clase',
        cancel: 'Cancelar clase',
        cancelConfirm: '¿Cancelar esta clase? Queda en la lista como cancelada y puedes reactivarla.',
        cancelYes: 'Sí, cancelar',
        hasAttendance:
          'Ya se tomó asistencia en esta clase, así que no se puede cancelar. Si se creó por error, elimínala.',
        reactivate: 'Reactivar clase',
        delete: 'Eliminar clase',
        deleteConfirm: (present: number, timer: boolean) => {
          const gone = [
            present > 0 && (present === 1 ? '1 asistencia' : `${present} asistencias`),
            timer && 'el registro del timer',
          ].filter(Boolean)
          if (gone.length === 0) return '¿Eliminar esta clase? No tiene asistencia ni registro del timer.'
          const verb = gone.length > 1 || present > 1 ? 'Se borran' : 'Se borra'
          return `¿Eliminar esta clase? ${verb} ${gone.join(' y ')}. No se puede deshacer.`
        },
        credits: 'Si alguien pagó la clase con créditos, se le devuelven.',
        deleteYes: 'Sí, eliminar',
        back: 'Volver',
        working: 'Un momento…',
        failed: 'No pudimos hacerlo. Inténtalo de nuevo.',
      },
      record: {
        title: 'Registro del timer',
        empty: 'Sin registro del timer.',
        edit: 'Editar registro',
        label: 'Editar registro del timer',
        get hint() {
          return `Corrige lo que quedó registrado: el tipo de cada bloque, los minutos que duró y, en ${w.practice}, las rondas hechas.`
        },
        block: (n: number) => `Bloque ${n}`,
        kind: 'Tipo',
        minutes: 'Minutos hechos',
        rounds: 'Rondas',
        roundMinutes: 'Min por ronda',
        completed: 'Rondas hechas',
        remove: (n: number) => `Quitar bloque ${n}`,
        add: '+ Agregar bloque',
        tooMany: (max: number) => `Una clase tiene hasta ${max} bloques.`,
        noKinds: 'No hay tipos de bloque. El dueño o un admin los crea en Ajustes › Bloques.',
        running: 'La clase está corriendo en el timer de este teléfono. Termínala para corregir el registro.',
        pending: 'El timer de este teléfono tiene bloques sin enviar. Se podrá corregir cuando se guarden.',
        get invalid() {
          return `Revisa los campos marcados. En ${w.practice}, los minutos no pueden pasar de las rondas hechas.`
        },
        submit: 'Guardar registro',
        working: 'Guardando…',
        close: 'Cancelar',
        saved: 'Registro guardado.',
        failed: 'No pudimos guardar el registro. Inténtalo de nuevo.',
      },
    },
    timer: {
      // The browser tab's title (#177).
      pageTitle: (classType: string) => `Timer de ${classType}`,
      back: 'Volver a la clase',
      loading: 'Cargando el timer…',
      error: 'No pudimos cargar el timer.',
      retry: 'Reintentar',
      notAllowed: 'Solo el coach de la clase, el dueño o un admin pueden usar el timer.',
      // An iPhone mutes the timer on silent, so it can beep over the music (#258).
      silentSwitch: 'Con el iPhone en silencio, el timer no suena.',
      editor: {
        title: 'Bloques de la clase',
        hint: 'Parte de la última clase de este tipo. Cambia lo que quieras antes de empezar.',
        hintEmpty: 'Arma la clase bloque por bloque.',
        get hintOpenMat() {
          return `${w.OpenMat}: rondas de ${w.practice}.`
        },
        hintRunning: 'Cambia los bloques que faltan o agrega uno. El timer sigue corriendo.',
        label: (n: number) => `Bloque ${n}`,
        kind: 'Tipo',
        minutes: 'Minutos',
        rounds: 'Rondas',
        roundMinutes: 'Min por ronda',
        restSeconds: 'Descanso (seg)',
        up: (n: number) => `Subir bloque ${n}`,
        down: (n: number) => `Bajar bloque ${n}`,
        remove: (n: number) => `Quitar bloque ${n}`,
        add: '+ Agregar bloque',
        empty: 'Sin bloques todavía.',
        noKinds: 'No hay tipos de bloque. El dueño o un admin los crea en Ajustes › Bloques.',
        get noSparring() {
          return `No hay un tipo de bloque de ${w.practice}. El dueño o un admin lo marca en Ajustes › Bloques.`
        },
        tooMany: (max: number) => `Una clase tiene hasta ${max} bloques.`,
        invalid: 'Revisa los campos marcados.',
        total: (minutes: string) => `Total: ${minutes}`,
        start: 'Comenzar',
        save: 'Guardar cambios',
        cancel: 'Cancelar',
      },
      running: {
        position: (n: number, total: number) => `Bloque ${n} de ${total}`,
        round: (kind: string, round: number, rounds: number) => `${kind} · ronda ${round}/${rounds}`,
        rest: (round: number, rounds: number) => `Descanso · sigue la ronda ${round}/${rounds}`,
        paused: 'En pausa',
        fightMode: 'RONDA',
        restMode: 'DESCANSO',
        next: (what: string) => `Sigue: ${what}`,
        nextRound: (round: number, rounds: number) => `ronda ${round}/${rounds}`,
        nextRest: (duration: string) => `descanso de ${duration}`,
        last: 'Último bloque',
        countdown: 'Tiempo restante',
        mini: (phase: string, time: string) => `${phase} · ${time}`,
        pause: 'Pausar',
        resume: 'Reanudar',
        skip: 'Saltar',
        skipRound: 'Saltar ronda',
        skipRest: 'Saltar descanso',
        addMinute: '+1 min',
        edit: 'Editar bloques',
        end: 'Terminar clase',
        endConfirm: '¿Terminar la clase? Se guarda lo que se hizo hasta ahora.',
        endYes: 'Sí, terminar',
        endNo: 'Seguir',
        unseen: {
          title: '¿Sigue la clase?',
          detail: (time: string) => `El timer quedó sin mirar desde las ${time}. Lo pausamos ahí.`,
          resume: 'Seguir',
          end: (time: string) => `Terminar a las ${time}`,
        },
        leave: {
          title: 'La clase sigue corriendo. Puedes volver al timer desde la clase.',
          yes: 'Salir',
          no: 'Quedarme',
        },
        noWakeLock: 'Este teléfono no permite mantener la pantalla encendida: desactiva el bloqueo automático mientras corre el timer.',
        noSound: 'Sin sonido en este teléfono: solo vibra y cambia de color.',
        soundLocked: 'Sin sonido: toca la pantalla para activarlo.',
      },
      done: {
        title: 'Clase terminada',
        rounds: (done: number, planned: number, duration: string) => `${done} de ${planned} rondas · ${duration}`,
        notRun: 'No se hizo',
        back: 'Volver a la clase',
      },
      sync: {
        pending: 'Sin conexión: los bloques quedaron en este teléfono. Se guardan cuando vuelva la señal.',
        saved: 'Bloques guardados.',
      },
      blockSummary: (kind: string, duration: string) => `${kind} · ${duration}`,
      roundsSummary: (kind: string, rounds: number, round: string, rest: string | null) =>
        `${kind} · ${rounds} × ${round}` + (rest ? ` + ${rest} descanso` : ''),
      minutes: (seconds: number) => {
        const m = Math.floor(seconds / 60)
        const s = seconds % 60
        return s === 0 ? `${m} min` : m === 0 ? `${s} s` : `${m} min ${s} s`
      },
    },
    payments: {
      title: 'Pagos',
      // What the screen shows, in one sentence (#357).
      subtitle: 'Los cobros, pagos y ajustes del mes elegido.',
      coachesOnly: 'Los coaches no ven esta sección.',
      loading: 'Cargando los pagos…',
      error: 'No pudimos cargar los pagos.',
      retry: 'Reintentar',
      month: 'Período',
      // The month's ledger for the accountant (#40).
      exportCsv: 'Exportar CSV',
      exportXlsx: 'Exportar Excel',
      // The month's expenses, beside the ledger's CSV, for whoever sees expenses (#317).
      exportExpensesCsv: 'Gastos del mes (CSV)',
      // Cobros extra and the exports, out of the header's row (#357).
      moreActions: 'Más',
      kpisLabel: 'Resumen del mes',
      kpis: {
        collected: 'Cobrado',
        collectedDetail: (n: number, refunded: string | null) =>
          (n === 1 ? '1 pago validado' : `${n} pagos validados`) + (refunded ? ` · Devuelto ${refunded}` : ''),
        pending: 'Por validar',
        pendingDetail: (n: number) => (n === 1 ? '1 comprobante' : `${n} comprobantes`),
        overdue: 'Vencido',
        overdueDetail: (members: number, days: string) =>
          `${w.memberCount(members)} · ${days} días promedio`,
        expected: 'Esperado',
        expectedDetail: (active: number, frozen: number) =>
          `${active === 1 ? '1 membresía activa' : `${active} membresías activas`}` +
          (frozen ? ` · ${frozen === 1 ? '1 congelada' : `${frozen} congeladas`}` : ''),
      },
      filtersLabel: 'Filtrar movimientos',
      filters: { all: 'Todos', pending: 'Por validar', overdue: 'Vencidos', kids: 'Kids' },
      columns: {
        date: 'Fecha',
        get student() {
          return `${w.Member}`
        },
        kind: 'Tipo',
        period: 'Período',
        detail: 'Detalle',
        status: 'Estado',
        amount: 'Monto',
      },
      // An adjustment voiding a charge (#256), and one restoring it (#278).
      void: 'Anulación',
      restore: 'Restauración',
      kind: { charge: 'Cargo', payment: 'Pago', adjustment: 'Ajuste', refund: 'Devolución', freeze: 'Congelación' },
      // An adjustment on a period by which way it goes (#210), in place of `kind.adjustment`.
      adjustment: { favor: 'Descuento', owed: 'Recargo' },
      // A debt outlives its plan (#207): what became of the membership, beside the plan.
      membership: { lapsed: 'Plan caducado', cancelled: 'Dado de baja', frozen: 'Congelado' } as Statuses,
      method: { transfer: 'Transferencia', cash: 'Efectivo', other: 'Otro' },
      credit: 'A favor',
      status: {
        pending: 'Por validar',
        validated: 'Validado',
        validatedBy: (name: string) => `Validado · ${name}`,
        rejected: 'Rechazado',
        voided: 'Anulado',
        paid: 'Pagado',
        open: (day: string) => `Abierto · vence ${day}`,
        overdue: (days: number) => `Vencido ${days} d`,
        freezeStart: 'Inicio',
        freezeEnd: 'Fin',
      },
      empty: 'No hay movimientos para mostrar.',
      showing: (shown: number, total: number, month: string | null) =>
        `Mostrando ${shown} de ${total} ${total === 1 ? 'movimiento' : 'movimientos'}${month ? ` de ${month}` : ''}`,
      more: 'Cargar más',
      review: (n: number) => (n === 1 ? 'Revisar 1 comprobante' : `Revisar ${n} comprobantes`),
      searchLabel: 'Buscar en los pagos',
      searchPlaceholder: 'Nombre, teléfono o RUT',
      noMatch: (q: string) => `No hay movimientos de «${q}».`,
      record: 'Registrar pago',
      extra: 'Cobros extra',
      kpiExtra: (amount: string) => ` · ${amount} de cobros extra`,
      // The way to the month's summary, beside the KPIs (#505).
      summary: 'Ver resumen del mes',
      picker: {
        label: '¿Quién paga?',
        get results() {
          return `${w.Members} ${w.memberIs('encontrados', 'encontradas')}`
        },
        none: 'Nadie coincide con esa búsqueda.',
        get error() {
          return `No pudimos cargar ${w.theMembers}.`
        },
        loading: 'Cargando…',
        noPlan: 'No tiene plan: no hay nada que cobrarle.',
        upToDate: 'Está al día: no tiene períodos por pagar.',
        // With two plans running, a course beside a monthly plan, which one it pays (#354).
        plan: '¿Qué plan paga?',
        get change() {
          return `Cambiar ${w.member}`
        },
        cancel: 'Cancelar',
      },
    },
    // Pagos, Finanzas and Gastos, one money section (#531): the row of tabs over all three.
    money: {
      tabs: { label: 'Secciones de Pagos', payments: 'Pagos', finances: 'Finanzas', expenses: 'Gastos' },
    },
    // Finanzas (#316): the month whole, what came in, what went out and what is left,
    // and the year month by month. Entradas is Pagos' Cobrado; without «Ver ingresos» the
    // page shows Salidas only.
    finances: {
      title: 'Finanzas',
      subtitle: 'Lo que entró, lo que salió y lo que queda.',
      view: { label: 'Ver', month: 'Mes', year: 'Año' },
      loading: 'Cargando las finanzas…',
      error: 'No pudimos cargar las finanzas.',
      retry: 'Reintentar',
      month: 'Mes',
      previous: 'Mes anterior',
      next: 'Mes siguiente',
      yearNav: 'Año',
      previousYear: 'Año anterior',
      nextYear: 'Año siguiente',
      income: 'Entradas',
      expenses: 'Salidas',
      result: 'Resultado',
      plans: 'Cuotas y planes',
      extra: 'Cobros extra',
      incomeNote: 'Lo cobrado, como lo muestra Pagos: neto de devoluciones.',
      // Under Resultado (#318): both are already in Entradas and Salidas, nothing nets.
      recovered: (paid: string, collected: string) =>
        `De esto, gastos recuperados con cobros extra: ${paid} pagado, ${collected} recaudado.`,
      noExpenses: 'No hay gastos registrados en este mes.',
      noExpensesYear: 'No hay gastos registrados en este año.',
      onlyExpenses: 'Ves solo las salidas: las entradas son de quien tiene «Ver ingresos».',
      monthLabel: (month: string) => `Finanzas de ${month}`,
      yearLabel: (year: string) => `Finanzas de ${year}`,
      byCategory: 'Salidas por categoría',
      categoryMonths: (name: string) => `${name} mes a mes`,
      total: 'Total del año',
      none: '—',
      // The month's row of the year: its name, and at 1280 the bars of what came in and went out.
      columns: { month: 'Mes', income: 'Entradas', expenses: 'Salidas', result: 'Resultado' },
    },
    // Finanzas › Gastos (#314): what the gym spends, apart from billing. Nothing here
    // touches a student's balance; a voided expense stays listed, struck through.
    expenses: {
      title: 'Gastos',
      subtitle: 'Lo que el gimnasio paga: arriendo, cuentas, federación, sueldos.',
      onlyWho: 'Solo quien tiene el permiso «Ver gastos» ve esta sección.',
      loading: 'Cargando los gastos…',
      error: 'No pudimos cargar los gastos.',
      retry: 'Reintentar',
      month: 'Mes',
      previous: 'Mes anterior',
      next: 'Mes siguiente',
      category: 'Categoría',
      allCategories: 'Todas las categorías',
      archivedCategory: (name: string) => `${name} (archivada)`,
      total: 'Total del mes',
      count: (n: number) => (n === 1 ? '1 gasto' : `${n} gastos`),
      empty: 'No hay gastos registrados en este mes.',
      emptyCategory: 'No hay gastos de esta categoría en este mes.',
      record: 'Registrar gasto',
      listLabel: (month: string) => `Gastos de ${month}`,
      columns: { date: 'Fecha', category: 'Categoría', payee: 'Pagado a', method: 'Método', amount: 'Monto' },
      method: { transfer: 'Transferencia', cash: 'Efectivo', card: 'Tarjeta', other: 'Otro' } as Record<
        'transfer' | 'cash' | 'card' | 'other',
        string
      >,
      voided: 'Anulado',
      voidedBy: (name: string | null, reason: string) => (name ? `Anulado por ${name}: ${reason}` : `Anulado: ${reason}`),
      recordedBy: (name: string | null, day: string) => (name ? `Registrado por ${name} el ${day}` : `Registrado el ${day}`),
      edited: (day: string) => `Corregido el ${day}`,
      // The cobro extra that recovers it (#318); its title only to who reads cobros.
      recoveredBy: 'Lo recupera el cobro extra',
      recoveredByUnnamed: 'Lo recupera un cobro extra.',
      receipt: 'Ver comprobante',
      receiptOpening: 'Abriendo…',
      receiptFailed: 'No pudimos abrir el comprobante.',
      edit: 'Corregir',
      void: 'Anular',
      close: 'Cerrar',
      form: {
        newTitle: 'Nuevo gasto',
        editTitle: 'Corregir gasto',
        spentOn: 'Fecha de pago',
        spentOnHint: 'El día en que se pagó: decide el mes.',
        amount: 'Monto',
        category: 'Categoría',
        pickCategory: 'Elige una',
        payee: 'Pagado a',
        payeeHint: 'Opcional: «Enel», «Inmobiliaria Los Robles», el nombre del coach.',
        method: 'Método',
        noMethod: 'Sin indicar',
        note: 'Nota',
        extraCharge: 'Lo recupera un cobro extra',
        extraChargeHint: 'Opcional: si el grupo devuelve este gasto con un cobro extra, como un viaje o un seminario. El cobro no cambia.',
        noExtraCharge: 'Ninguno',
        extraChargeGone: 'Ese cobro extra no existe: elige otro.',
        receipt: 'Comprobante',
        receiptHint: 'Opcional: una foto o un PDF, hasta 10 MB.',
        chooseFile: 'Elegir archivo',
        receiptKept: 'Tiene comprobante.',
        receiptRemove: 'Quitar comprobante',
        receiptRemoved: 'Se quitará el comprobante al guardar.',
        receiptUndo: 'Mantenerlo',
        fileType: 'Ese archivo no sirve: sube una foto (JPG, PNG, HEIC) o un PDF.',
        fileSize: 'El archivo pesa más de 10 MB.',
        fileEmpty: 'El archivo está vacío.',
        amountNeeded: 'Escribe un monto mayor que cero.',
        dayNeeded: 'Elige el día en que se pagó, hasta hoy.',
        categoryNeeded: 'Elige una categoría.',
        cancel: 'Cancelar',
        save: 'Guardar gasto',
        saveChange: 'Guardar corrección',
        working: 'Guardando…',
        failed: 'No pudimos guardar el gasto. Revisa los datos e inténtalo de nuevo.',
        receiptTaken: 'Ese comprobante ya está en otro gasto.',
        categoryArchived: 'Esa categoría fue archivada: elige otra.',
        changeNote: 'La corrección queda registrada, con lo que había antes.',
        saved: (amount: string) => `Gasto de ${amount} registrado.`,
        changed: 'Gasto corregido.',
      },
      voidForm: {
        title: (what: string) => `Anular ${what}`,
        intro: 'El gasto queda en la lista, tachado, y deja de sumar. No se puede deshacer.',
        reason: 'Motivo',
        reasonNeeded: 'Escribe por qué se anula.',
        cancel: 'Cancelar',
        submit: 'Anular gasto',
        working: 'Anulando…',
        failed: 'No pudimos anular el gasto.',
        done: 'Gasto anulado.',
      },
      categories: {
        title: 'Categorías',
        intro: 'Cambia el nombre, el orden o archiva las que no uses. Una categoría archivada sigue en los gastos que ya la tienen.',
        add: 'Agregar categoría',
        addLabel: 'Nueva categoría',
        rename: 'Cambiar nombre',
        nameLabel: (name: string) => `Nombre de ${name}`,
        save: 'Guardar',
        cancel: 'Cancelar',
        up: (name: string) => `Subir ${name}`,
        down: (name: string) => `Bajar ${name}`,
        archive: 'Archivar',
        restore: 'Restaurar',
        otherKept: 'Otros no se puede archivar.',
        archivedTitle: 'Archivadas',
        uses: (n: number) => (n === 0 ? 'Sin gastos' : n === 1 ? '1 gasto' : `${n} gastos`),
        nameTaken: 'Ya hay una categoría con ese nombre.',
        failed: 'No pudimos guardar el cambio.',
      },
      // Gastos fijos (#315): rent and bills as monthly templates. Rakin never records
      // one by itself: the card lists what is missing, and a person records each.
      due: {
        title: (month: string) => `Gastos fijos por registrar · ${month}`,
        intro: 'Rakin no los registra solo: confirma cada uno cuando lo pagues.',
        day: (n: number) => `día ${n}`,
        // An estimated amount is last bill's: a hint, not the figure.
        estimate: (amount: string) => `~${amount}`,
        estimateHint: (amount: string) => `Aproximado: ${amount}. Escribe el monto de la boleta.`,
        record: 'Registrar',
        recordEstimated: 'Registrar…',
        recordWhat: (what: string) => `Registrar ${what}`,
        recordAll: (n: number) => `Registrar los ${n} fijos`,
        skip: 'No este mes',
        skipWhat: (what: string) => `No registrar ${what} este mes`,
        skippedTitle: 'No este mes',
        unskip: 'Volver a mostrar',
        unskipWhat: (what: string) => `Volver a mostrar ${what}`,
        working: 'Registrando…',
        recorded: (n: number, amount: string) =>
          n === 1 ? `Gasto de ${amount} registrado.` : `${n} gastos registrados, ${amount} en total.`,
        nothingNew: 'Ya estaba registrado.',
        failed: 'No pudimos registrarlo. Inténtalo de nuevo.',
        // A batch is all or nothing: a refusal says which one stopped it.
        noneRecorded: (why: string) => `No se registró ninguno: ${why}. La lista ya está al día.`,
        refused: {
          paused: (what: string) => `${what} fue pausado`,
          category_archived: (what: string) => `la categoría de ${what} fue archivada; regístralo con el formulario`,
          estimated: (what: string) => `${what} tiene monto estimado; regístralo con «Registrar…»`,
          no_recurring: (what: string) => `${what} ya no existe`,
        } as Record<string, ((what: string) => string) | undefined>,
        alreadyRecorded: 'Ese gasto fijo ya está registrado en este mes.',
      },
      recurring: {
        title: 'Gastos fijos',
        intro:
          'Arriendo, internet, la luz: lo que se paga cada mes. Aparecen en el mes hasta que los registres; un gasto fijo pausado no aparece.',
        empty: 'Aún no hay gastos fijos.',
        add: 'Nuevo gasto fijo',
        newTitle: 'Nuevo gasto fijo',
        editTitle: (what: string) => `Editar ${what}`,
        edit: 'Editar',
        pause: 'Pausar',
        resume: 'Reanudar',
        paused: 'Pausado',
        kind: { fixed: 'Monto fijo', estimated: 'Monto estimado' } as Record<'fixed' | 'estimated', string>,
        kindLabel: 'El monto',
        kindHint: 'Fijo se registra con un toque. Estimado (luz, agua, gas) abre el formulario para escribir el de la boleta.',
        amount: 'Monto',
        amountEstimated: 'Monto aproximado',
        dayOfMonth: 'Día del mes en que se paga',
        dayHint: 'Del 1 al 31. En un mes más corto, su último día.',
        dayNeeded: 'Escribe un día entre 1 y 31.',
        summary: (amount: string, day: number, kind: string) => `${amount} · día ${day} · ${kind}`,
        archivedCategory: 'Su categoría está archivada: elige otra al registrarlo.',
        cancel: 'Cancelar',
        save: 'Guardar gasto fijo',
        working: 'Guardando…',
        failed: 'No pudimos guardar el gasto fijo.',
        tooMany: 'Hay demasiados gastos fijos: pausa o edita uno de los que hay.',
      },
    },
    // Pagos › Resumen del mes (#505): what happened after Rakin's reminders and the
    // team's nudges, as counts. "Después de", never "gracias a" or "recuperado": some
    // would have paid, or come back, anyway. No names behind any figure.
    summary: {
      title: 'Resumen del mes',
      subtitle: 'Lo que pasó después de los recordatorios de Rakin y los mensajes del equipo.',
      loading: 'Cargando el resumen…',
      error: 'No pudimos cargar el resumen.',
      retry: 'Reintentar',
      month: 'Mes',
      // A gym's first month on Rakin is a partial one.
      since: (day: string) => `Desde el ${day}`,
      // A whole percentage, as Chile writes it.
      percent: (n: number) => `${n}\u00a0%`,
      // The headline tiles. Each label carries the honesty: "después de", never
      // "gracias a"; money as part of the month's "Cobrado", people as "N de M".
      tiles: 'Lo principal del mes',
      paidLabel: 'Pagos atrasados que llegaron después de un recordatorio',
      paidCount: (n: number) => (n === 1 ? '1 pago atrasado' : `${n} pagos atrasados`),
      // "el 18 % de $6.900.000 cobrado en noviembre", or without a share under 5 payments.
      ofIncome: (share: string | null, income: string, month: string) =>
        `${share ? `el ${share} ` : ''}de ${income} cobrado en ${MONTHS[Number(month.slice(5, 7)) - 1]}`,
      backLabel: 'Volvieron a clases después de un WhatsApp del equipo',
      backFigure: (back: number, of: number) => `${back} de ${of}`,
      // The percentage only from 5 people up.
      backDetail: (share: string | null) =>
        `${w.Members} que no venían hace 14 días o más; volvieron dentro de dos semanas${share ? ` · ${share}` : ''}`,
      remindersLabel: 'Recordatorios de pago enviados',
      remindersDetail: (emails: number, whatsapps: number) =>
        [
          emails === 0 ? null : `${emails} por correo de Rakin`,
          whatsapps === 0 ? null : `${whatsapps} por WhatsApp del equipo`,
        ]
          .filter(Boolean)
          .join(' · '),
      // The late payments, split by whether anyone on the team wrote.
      split: 'Cómo llegaron los pagos atrasados',
      emailsOnly: 'Sin mensaje del equipo',
      afterWhatsapp: 'Después de un WhatsApp del equipo',
      splitFigure: (payments: number, amount: string) => `${payments === 1 ? '1 pago' : `${payments} pagos`} · ${amount}`,
      // A month with no figure above zero (#516): never a zero, never "ningún".
      nothing: 'Todavía no hay números para este mes.',
      whatsappOff: 'Con WhatsApp activado en Ajustes › Gimnasio, el equipo puede escribir desde Hoy a quienes dejaron de venir, y aquí verás cuántos volvieron.',
      // The smaller counts, as a label and a figure.
      counts: 'Otros números del mes',
      get ownPayments() {
        return `Pagos que informaron ${w.memberIs('los mismos', 'las mismas')} ${w.members}, con su comprobante`
      },
      ofTotal: (n: number, of: number) => `${n} de ${of}`,
      proofs: 'Comprobantes revisados',
      proofsFigure: (n: number, median: string) => `${n} · la mitad en ${median} o menos`,
      // How long the median proof waited.
      duration: (minutes: number) => {
        if (minutes < 60) return minutes === 1 ? '1 minuto' : `${minutes} minutos`
        const hours = Math.round(minutes / 60)
        if (hours < 48) return hours === 1 ? '1 hora' : `${hours} horas`
        return `${Math.round(hours / 24)} días`
      },
      emailsSent: 'Avisos de cobro y recibos enviados por correo',
      reactivated: 'Planes vencidos que volvieron a activarse',
      trialsConverted: 'Clases de prueba que pasaron a un plan',
      // Only a closed month kept on the 1st has it (#506).
      overdue: 'Deuda vencida al cierre del mes',
      how: {
        title: 'Cómo contamos esto',
        paid: 'Un pago cuenta cuando llegó después de su fecha de vencimiento y después de al menos un recordatorio enviado tras esa fecha: un correo de Rakin o un WhatsApp que abrió el equipo. Se cuenta en el mes en que se validó, como en «Cobrado».',
        anyway: 'Algunos habrían pagado igual, sin recordatorio. Por eso decimos «después de» y no «gracias a».',
        get back() {
          return `«Volvieron» son ${w.theMembers} que vinieron a una clase dentro de los 14 días siguientes al WhatsApp. Algunos habrían vuelto de todos modos.`
        },
        totals: 'Son totales del mes: no se guarda ni se muestra quién está detrás de cada número.',
        overdue: 'La deuda al cierre es lo que debían los planes activos por cuotas vencidas, leída el primer día del mes siguiente.',
        // A closed month, read from what was kept of it (#506).
        kept: 'Estos números se guardaron al cerrar el mes y no se vuelven a calcular: quien volvió después del cierre no se suma a «Volvieron».',
        olderRules: 'Este mes se contó con reglas anteriores a las de hoy, y se muestra tal como se contó al cerrarlo: quien volvió después del cierre no se suma a «Volvieron».',
      },
    },
    // Cobros extra (#195): one-off charges, fixed or split across a group.
    extra: {
      title: 'Cobros extra',
      subtitle: 'Rifas, seminarios, equipamiento y gastos compartidos. No afectan el plan de nadie.',
      back: 'Volver a Pagos',
      open: 'Cobros extra',
      ficha: 'Cobros extra pendientes',
      create: 'Nuevo cobro',
      loading: 'Cargando…',
      error: 'No pudimos cargar los cobros extra.',
      retry: 'Reintentar',
      empty: 'Todavía no hay cobros extra.',
      listLabel: 'Cobros extra',
      // A title cut to two lines (#357).
      titleMore: 'Ver título completo',
      titleLess: 'Ver menos',
      category: {
        rifa: 'Rifa',
        seminario: 'Seminario',
        equipamiento: 'Equipamiento',
        gasto_compartido: 'Gasto compartido',
        otro: 'Otro',
        matricula: 'Matrícula',
      },
      due: (day: string) => `vence ${day}`,
      // A cobro in instalments (#356): "3 cuotas", "cuota 2 de 3". A line's own name,
      // "Título · cuota 2 de 3", is the backend's (`line_title`, `line_title_sql`); the
      // wizard's sample email spells it the same way from `instalmentOf`.
      instalments: (n: number) => `${n} cuotas`,
      instalmentOf: (i: number, n: number) => `Cuota ${i} de ${n}`,
      progress: (paid: number, lines: number, collected: string, due: string) =>
        `${paid} de ${lines} pagaron · ${collected} de ${due}`,
      waived: (n: number) => (n === 1 ? '1 exento' : `${n} exentos`),
      status: {
        open: 'Pendiente',
        overdue: 'Vencido',
        in_review: 'Comprobante enviado',
        paid: 'Pagado',
        waived: 'Exento',
        cancelled: 'Anulado',
      },
      groups: {
        title: 'Grupos',
        intro: 'Listas de personas para reutilizar en los cobros: un grupo es una foto, no se actualiza solo.',
        create: 'Nuevo grupo',
        empty: 'Todavía no hay grupos.',
        size: (n: number) => (n === 1 ? '1 persona' : `${n} personas`),
        option: (name: string, n: number) => `${name} (${n === 1 ? '1 persona' : `${n} personas`})`,
        edit: 'Editar',
        name: 'Nombre del grupo',
        namePlaceholder: 'p. ej. Clasificados final',
        filters: 'Agregar desde filtros',
        program: 'Programa',
        plan: 'Plan',
        rank: 'Cinturón',
        level: 'Nivel',
        any: 'Todos',
        addAll: (n: number) => (n === 1 ? 'Agregar a 1 persona' : `Agregar a las ${n} personas`),
        loadingFilter: 'Buscando…',
        search: 'Agregar a mano',
        searchPlaceholder: 'Nombre, teléfono o RUT',
        add: (name: string) => `Agregar a ${name}`,
        remove: (name: string) => `Quitar a ${name}`,
        removeShort: 'Quitar',
        members: (n: number) => (n === 1 ? '1 persona en el grupo' : `${n} personas en el grupo`),
        noMembers: 'Nadie en el grupo todavía.',
        save: 'Guardar grupo',
        saving: 'Guardando…',
        cancel: 'Cancelar',
        delete: 'Eliminar grupo',
        deleteConfirm: 'Sí, eliminar',
        deleteNote: 'Los cobros que ya lo usaron quedan como están.',
        taken: 'Ya hay un grupo con ese nombre.',
        nameNeeded: 'Ponle un nombre al grupo.',
        failed: 'No pudimos guardar el grupo. Inténtalo de nuevo.',
        saved: (name: string) => `Grupo «${name}» guardado.`,
      },
      wizard: {
        title: 'Nuevo cobro extra',
        steps: ['Detalles', 'Para quién', 'Monto', 'Mensaje', 'Confirmar'] as readonly string[],
        stepOf: (i: number, n: number, name: string) => `Paso ${i} de ${n}: ${name}`,
        next: 'Siguiente',
        previous: 'Atrás',
        cancel: 'Cancelar',
        titleLabel: 'Título',
        titlePlaceholder: 'p. ej. Bencina final de Santiago',
        titleNeeded: 'Ponle un título al cobro.',
        categoryLabel: 'Tipo',
        descriptionLabel: 'Descripción (opcional)',
        dueLabel: 'Vence el',
        dueNeeded: 'Elige hasta cuándo se puede pagar.',
        targetLabel: '¿A quién se le cobra?',
        target: {
          active: 'A todos los activos',
          program: 'A un programa',
          group: 'A un grupo',
          people: 'Elegir personas',
        },
        programLabel: 'Programa',
        groupLabel: 'Grupo',
        noGroups: 'No hay grupos: créalos en Cobros extra › Grupos, o elige personas.',
        pickNeeded: 'Elige a quién se le cobra.',
        modeLabel: '¿Cómo se cobra?',
        mode: {
          fixed: 'Monto fijo por persona',
          split: 'Total a dividir',
        },
        amountLabel: { fixed: 'Monto por persona (CLP)', split: 'Total a dividir (CLP)' },
        amountNeeded: 'Escribe el monto.',
        previewLabel: 'Cuánto paga cada uno',
        previewLoading: 'Calculando…',
        previewError: 'No pudimos calcular los montos.',
        nobody: 'Ese grupo no tiene a nadie a quién cobrarle.',
        tooSmall: 'El total no alcanza para un peso por persona.',
        // "En cuotas" (#356): each person's amount in N, monthly from the due date.
        inInstalments: 'En cuotas',
        inInstalmentsHint: 'Cada persona paga su monto en cuotas mensuales desde la fecha de vencimiento.',
        instalmentsLabel: 'Número de cuotas',
        instalmentsTooSmall: 'Cada cuota tiene que ser de al menos un peso.',
        instalmentsRemainder: 'Lo que no se divide parejo se suma a la primera cuota.',
        // The split, said once under the total, and on a person's row only where theirs differs (#417).
        splitEven: (n: number, amount: string) => `${n} cuotas de ${amount}`,
        splitFirst: (n: number, first: string, rest: string) =>
          `${n} cuotas: la primera de ${first} y ${n - 1} de ${rest}`,
        split: (share: string, n: number) => `${share} cada uno entre ${n === 1 ? '1 persona' : `${n} personas`}`,
        remainder: (n: number) =>
          n === 1 ? 'El peso que sobra lo paga la primera persona por orden alfabético.' : `Los ${n} pesos que sobran los paga un peso más cada uno de los primeros ${n} por orden alfabético.`,
        total: (amount: string, n: number) => `Total ${amount} · ${n === 1 ? '1 persona' : `${n} personas`}`,
        overrideLabel: (name: string) => `Monto de ${name}`,
        overridden: 'Ajustado a mano',
        undo: 'Deshacer',
        reset: (name: string) => `Volver al monto calculado para ${name}`,
        guardian: (name: string) => `aviso a ${name}`,
        messageLabel: 'Mensaje del correo (opcional)',
        messageHint: 'Va en el correo, sobre el monto que le toca a cada persona.',
        notify: 'Enviar un correo a cada persona con su monto',
        notifyHint: 'A los menores, el correo le llega a su apoderado.',
        // The last look (#357): what is charged, to whom, how much and when, and the email.
        each: (amount: string) => `${amount} cada uno`,
        range: (low: string, high: string) => `De ${low} a ${high} por persona`,
        confirm: {
          charge: 'Cobro',
          who: 'Para quién',
          whoIs: (n: number, rule: string) => `${n === 1 ? '1 persona' : `${n} personas`}: ${rule}`,
          rule: {
            active: 'todos los activos',
            program: (name: string) => `el programa ${name}`,
            group: (name: string) => `el grupo ${name}`,
            anyProgram: 'un programa',
            anyGroup: 'un grupo',
            people: 'elegidas a mano',
          },
          amount: 'Monto por persona',
          adjusted: (n: number) => (n === 1 ? '1 ajustado a mano' : `${n} ajustados a mano`),
          total: 'Total',
          due: 'Vence',
          instalments: 'Cuotas',
          instalmentDue: (i: number, amount: string, day: string) => `Cuota ${i}: ${amount} · ${day}`,
          // An instalment's amount when not everyone pays the same (#417).
          inAll: (amount: string) => `${amount} en total`,
          message: 'El correo',
          sampleFor: (name: string) => `Así le llega a ${name}; a cada uno, con su monto:`,
          hello: (name: string) => `Hola, ${name}:`,
          sends: (gym: string, title: string, dependent: string | null) =>
            `${gym} te envía un cobro: ${title}${dependent ? `, de ${dependent}` : ''}.`,
          owes: (dependent: string | null, amount: string, due: string) =>
            `${dependent ? `A ${dependent} le corresponde` : 'Te corresponde'} pagar ${amount}, hasta el ${due}.`,
          noNotify: 'No se envía correo: el cobro queda en la página de cada uno.',
          nobodyEmailed: 'Nadie tiene correo: no se envía ninguno.',
        },
        noEmail: (n: number) =>
          n === 1 ? '1 persona no tiene correo: avísale por WhatsApp.' : `${n} personas no tienen correo: avísales por WhatsApp.`,
        whatsapp: (name: string) => `Avisar a ${name} por WhatsApp`,
        personAmount: (name: string, amount: string) => `${name} · ${amount}`,
        noWhatsapp: 'sin WhatsApp',
        create: 'Crear cobro',
        creating: 'Creando…',
        failed: 'No pudimos crear el cobro. Inténtalo de nuevo.',
      },
      detail: {
        loading: 'Cargando el cobro…',
        error: 'No pudimos cargar el cobro.',
        notFound: 'Ese cobro no existe.',
        peopleLabel: 'Personas',
        // Paid and owed per instalment (#356).
        scheduleLabel: 'Cuotas',
        // What the gym spent that this cobro recovers (#318), beside what it collected.
        expensesLabel: 'Gastos asociados',
        collectedLabel: 'Recaudado',
        differenceLabel: 'Diferencia',
        expensesCount: (n: number) => (n === 1 ? '1 gasto' : `${n} gastos`),
        expensesNote: 'Los gastos que nombran este cobro. Finanzas cuenta ambos completos: nada se descuenta.',
        instalmentDue: (i: number, n: number, day: string) => `Cuota ${i} de ${n} · vence ${day}`,
        firstDue: (n: number, day: string) => `${n} cuotas · la primera vence ${day}`,
        // One row per person in a cobro in instalments (#417); their instalments under "Ver cuotas".
        instalmentsPaid: (paid: number, n: number) => `${paid} de ${n} cuotas pagadas`,
        nextDue: (i: number, n: number, day: string, amount: string) => `Cuota ${i} de ${n}: ${amount}, vence ${day}`,
        markPaidInstalment: (i: number) => `Marcar pagada la cuota ${i}`,
        showInstalments: 'Ver cuotas',
        showInstalmentsOf: (name: string) => `Ver cuotas de ${name}`,
        instalmentsOfPerson: (name: string) => `Cuotas de ${name}`,
        remind: 'Recordar a los pendientes',
        reminding: 'Enviando…',
        reminded: (sent: number, without: number) =>
          (sent === 1 ? 'Enviamos 1 recordatorio.' : `Enviamos ${sent} recordatorios.`) +
          (without ? ` ${without === 1 ? '1 persona no tiene' : `${without} personas no tienen`} correo.` : ''),
        guardianOf: (name: string) => `Apoderado: ${name}`,
        owes: (amount: string) => `debe ${amount}`,
        paidOf: (paid: string, due: string) => `pagó ${paid} de ${due}`,
        overridden: 'monto ajustado',
        actions: (name: string) => `Acciones para ${name}`,
        actionsOf: (name: string, i: number) => `Acciones para ${name}, cuota ${i}`,
        more: 'Más',
        moreFor: (name: string) => `Más acciones para ${name}`,
        moreForOf: (name: string, i: number) => `Más acciones para ${name}, cuota ${i}`,
        markPaid: 'Marcar pagado',
        editAmount: 'Editar monto',
        cancelLine: 'Anular',
        notify: 'Reenviar aviso',
        notified: 'Aviso reenviado.',
        noEmail: 'No tiene correo: no se envió nada.',
        whatsapp: (name: string) => `Recordar a ${name} por WhatsApp`,
        whatsappShort: 'Recordar por WhatsApp',
        review: 'Ver comprobante',
        refund: 'Devolver',
        amountLabel: 'Monto (CLP)',
        // "Editar monto" on one instalment (#356).
        amountOneInstalment: 'Cambia solo esta cuota: las demás quedan como están.',
        methodLabel: 'Cómo pagó',
        refundMethodLabel: 'Cómo se devolvió',
        method: { transfer: 'Transferencia', cash: 'Efectivo', other: 'Otro' },
        save: 'Guardar',
        saving: 'Guardando…',
        close: 'Cerrar',
        cancelChecking: 'Revisando…',
        cancelConfirm: 'Sí, anular',
        cancelReason: 'Motivo',
        cancelReasonNeeded: 'Escribe por qué se anula.',
        // A cancelled line, with why (#256).
        cancelledBecause: (reason: string) => `Anulado: ${reason}`,
        resplit: 'Volver a dividir el total entre los que quedan',
        resplitAmount: (name: string, amount: string) => `${name}: ${amount}`,
        noResplit: 'El total no se vuelve a dividir: alguien ya pagó, o no es un total a dividir.',
        noResplitInstalments: 'Un cobro en cuotas no se vuelve a dividir: se anula solo esta cuota.',
        refundOf: (amount: string, left: string) => `Pago de ${amount} · quedan ${left} por devolver`,
        failed: 'No pudimos guardarlo. Inténtalo de nuevo.',
        refused: {
          paid: 'Esa persona ya pagó todo.',
          belowPaid: 'No puede ser menos de lo que ya pagó.',
          money: 'Tiene dinero o un comprobante pendiente: devuélvelo o revísalo primero.',
          resplit: 'Ya no se puede volver a dividir el total.',
          cancelled: 'Esta línea está anulada.',
        },
      },
    },
    review: {
      title: 'Validar comprobante',
      back: 'Volver a Hoy',
      position: (i: number, n: number) => `Comprobante ${i} de ${n}`,
      previous: 'Comprobante anterior',
      next: 'Comprobante siguiente',
      loading: 'Cargando comprobantes…',
      error: 'No pudimos cargar los comprobantes.',
      retry: 'Reintentar',
      empty: 'No hay comprobantes por revisar.',
      get claimLabel() {
        return `Lo que dice ${w.theMember}`
      },
      claimed: 'Dice haber pagado',
      owes: 'Debe',
      claimedAt: (when: string, method: string) => `${when} · ${method}`,
      method: { transfer: 'transferencia', cash: 'efectivo', other: 'otro' },
      periodDue: (month: string, due: string) => `${month} · vence ${due}`,
      match: {
        matches: 'El monto coincide con lo que se debe',
        over: (amount: string) => `Paga ${amount} de más: quedarán a favor`,
        short: (amount: string) => `Faltan ${amount} para cerrar el período`,
      },
      proofLabel: (name: string) => `Comprobante de ${name}`,
      zoom: 'Toca para ampliar',
      // With a mouse or trackpad, where nothing is tapped (#362).
      zoomPointer: 'Ampliar',
      zoomLabel: 'Ampliar comprobante',
      close: 'Cerrar',
      openFile: 'Abrir comprobante',
      openPdf: 'Abrir PDF del comprobante',
      missing: 'No encontramos el archivo del comprobante.',
      get sentByStudent() {
        return `Enviada desde la página ${w.ofTheMember}`
      },
      sentBy: (name: string) => `Enviada por ${name}`,
      extra: 'Cobro extra',
      extraDue: (category: string, due: string) => `${category} · vence ${due}`,
      plan: 'Plan',
      planDay: (plan: string, day: number) => `${plan} · día ${day}`,
      priorBalance: 'Saldo antes',
      lastPayments: 'Últimos 3 pagos',
      noPayments: 'Ninguno',
      attendance: 'Asistencia 30 d',
      attendanceCount: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
      // One transfer split over several periods (#66).
      shared: {
        intro: (total: string) => `Este comprobante es una transferencia de ${total} que también paga:`,
        claim: (name: string, amount: string, status: string) => `${name}: ${amount} · ${status}`,
        status: { pending: 'por revisar', validated: 'validado', rejected: 'rechazado' },
      },
      get noteLabel() {
        return `Nota (obligatoria si rechazas; ${w.theMember} la ve)`
      },
      notePlaceholder: 'p. ej. monto no coincide, falta $5.000',
      get noteNeeded() {
        return `Escribe una nota para ${w.theMember} antes de rechazar.`
      },
      reject: 'Rechazar',
      confirm: (amount: string) => `Confirmar ${amount}`,
      working: 'Guardando…',
      validated: (name: string, amount: string) => `Validado: ${name}, ${amount}.`,
      credit: (amount: string) => ` Quedan ${amount} a favor.`,
      rejected: (name: string) => `Rechazado: le avisamos a ${name}.`,
      refused: {
        paid: 'Ese período ya está pagado. Rechaza el comprobante con una nota.',
        reviewed: 'Otra persona ya revisó este comprobante.',
        failed: 'No pudimos guardar la revisión. Inténtalo de nuevo.',
      },
    },
  },
  // "Tiempo de entrenamiento" (#141, #226): the student page and the ficha read the same totals.
  matTime: {
    // Headings on /me speak as the member does, as "Mi plan" and "Mis clases" (#419).
    mine: 'Mi tiempo de entrenamiento',
    theirs: 'Tiempo de entrenamiento',
    // A dependent's, on their guardian's student page (#66).
    ofDependent: (name: string) => `Tiempo de entrenamiento de ${name}`,
    periods: 'Periodo',
    month: 'Este mes',
    allTime: 'Siempre',
    classes: 'Clases',
    // The practice's kinds and the open mats together, so not the breakdown's own line.
    get sparring() {
      return `${w.Practice} en total`
    },
    byKind: 'Tiempo por bloque',
    openMat: (n: number, time: string) => `${w.OpenMat}: ${n} · ${time}`,
    // Only where the open mat has a name of its own, as "Open mat" in BJJ (`MatTime`).
    get openMatNoteMine() {
      return `Tu tiempo de ${w.openMat} cuenta como ${w.practice}.`
    },
    get openMatNoteTheirs() {
      return `Su tiempo de ${w.openMat} cuenta como ${w.practice}.`
    },
    // Seconds as `4 h 30 min`, `2 h` or `45 min`; under half a minute, but some, `< 1 min`.
    duration: (seconds: number) => {
      const minutes = Math.round(seconds / 60)
      if (minutes === 0) return seconds > 0 ? '< 1 min' : '0 min'
      const hours = Math.floor(minutes / 60)
      const rest = minutes % 60
      if (hours === 0) return `${rest} min`
      const h = `${hours.toLocaleString('es-CL')} h`
      return rest === 0 ? h : `${h} ${rest} min`
    },
    get emptyMine() {
      return `Todavía no hay clases con tiempo registrado. Aparecerá aquí cuando tu ${w.coach} use el cronómetro.`
    },
    emptyTheirs: 'Todavía no hay clases con tiempo registrado.',
    emptyMonth: 'Este mes todavía no hay tiempo registrado.',
    loading: 'Cargando el tiempo de entrenamiento…',
    error: 'No pudimos cargar el tiempo de entrenamiento.',
  },
  // Hours per tag (#243): on the student page, the ficha and Clases.
  tagHours: {
    mine: 'Mis horas por etiqueta',
    theirs: 'Horas por etiqueta',
    gym: 'Horas por etiqueta',
    gymNote: 'De las clases hechas, sin las canceladas.',
    periods: 'Periodo',
    month: 'Mes',
    year: 'Año',
    thisMonth: 'Este mes',
    thisYear: 'Este año',
    previous: (what: string) => `${what} anterior`,
    next: (what: string) => `${what} siguiente`,
    // `2026` or `noviembre 2026`.
    stretch: (year: number, month: number | null) =>
      month === null
        ? String(year)
        : `${new Intl.DateTimeFormat('es-CL', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, 1)))} ${year}`,
    // Minutes as `12,5 h`, `1 h` or `45 min`.
    hours: (minutes: number) =>
      minutes < 60
        ? `${minutes} min`
        : `${(Math.round((minutes / 60) * 10) / 10).toLocaleString('es-CL')} h`,
    classes: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
    // `4,5 h · 3 clases`, built from the two above.
    figure: (minutes: number, classes: number): string =>
      `${es.tagHours.hours(minutes)} · ${es.tagHours.classes(classes)}`,
    archived: 'archivada',
    archivedSuffix: ' · archivada',
    untagged: (hours: string) => `Sin etiqueta: ${hours}`,
    // Classes counted with no duration set add no minutes anywhere (#257).
    noDuration: (n: number) =>
      n === 1 ? '1 clase sin duración, no suma horas' : `${n} clases sin duración, no suman horas`,
    noDurationLink: (day: string, classType: string) => `${day} · ${classType}`,
    empty: 'No hay clases con etiqueta en este periodo.',
    loading: 'Cargando las horas…',
    error: 'No pudimos cargar las horas por etiqueta.',
  },
  me: {
    // "Autorización" (#370): a guardian's consent to the processing of each minor's data,
    // apart from the inscription.
    consent: {
      title: 'Autorización de datos',
      // Around the link to the gym's privacy notice.
      get introBefore() {
        return `${w.ThePlace} te pide tu consentimiento para tratar los datos de cada menor a tu cargo, según su `
      },
      link: 'política de privacidad',
      introAfter:
        '. Es aparte de la inscripción: puedes no darlo, o retirarlo cuando quieras, y la inscripción sigue igual.',
      given: (day: string) => `Diste tu consentimiento el ${day}.`,
      withdrawn: (day: string) => `Retiraste tu consentimiento el ${day}.`,
      missing: 'Falta tu consentimiento.',
      give: 'Dar mi consentimiento',
      withdraw: 'Retirar mi consentimiento',
      working: 'Guardando…',
      // The notice changed since the page was loaded: it is loaded again.
      get stale() {
        return `${w.ThePlace} actualizó su política de privacidad. Revísala y vuelve a intentarlo.`
      },
      failed: 'No pudimos guardar tu respuesta. Inténtalo de nuevo.',
    },
    // From the student page back to the admin screens, for staff who also train (#214).
    get toAdmin() {
      return `Ir al panel ${w.ofThePlace}`
    },
    // "Requisitos" (#349): what the gym asks before training, and where each stands.
    requirements: {
      title: 'Mis requisitos',
      theirs: (name: string) => `Requisitos de ${name}`,
      state: REQUIREMENT_STATES,
      done: (day: string) => `Hecho el ${day}`,
      until: (day: string) => `vence el ${day}`,
      expiredOn: (day: string) => `venció el ${day}`,
    },
    // "Pedir congelamiento" (#270): a running plan, and a freeze asked for it.
    plans: {
      title: 'Mi plan',
      theirs: (name: string) => `Plan de ${name}`,
      status: { active: 'Activo', frozen: 'Congelado' },
      frozen: (day: string) => `Congelado. Vuelve el ${day}.`,
      booked: (from: string, to: string) => `Congelación programada del ${from} al ${to}.`,
      ask: 'Pedir congelamiento',
      askLabel: (plan: string) => `Pedir congelamiento de ${plan}`,
      formTitle: 'Pedir congelamiento',
      get intro() {
        return `${w.ThePlace} revisa tu solicitud. Mientras está congelado no se cobra: tu próximo pago se corre esos días.`
      },
      from: 'Desde',
      until: 'Vuelvo el',
      reason: 'Motivo',
      reasonPick: 'Elige un motivo',
      reasons: { viaje: 'Viaje', personal: 'Motivo personal', otro: 'Otro' },
      note: 'Detalle (opcional)',
      noteHint: NO_HEALTH,
      noteOther: 'Cuéntanos el motivo',
      fromNeeded: 'Elige hoy o un día después.',
      untilNeeded: 'Elige el día en que vuelves (después de “Desde”).',
      reasonNeeded: 'Elige un motivo.',
      noteNeeded: 'Escribe el motivo.',
      submit: 'Enviar solicitud',
      cancel: 'Cancelar',
      working: 'Enviando…',
      pending: 'Solicitud enviada · pendiente',
      pendingDates: (from: string, to: string) => `Del ${from}, vuelves el ${to}.`,
      withdraw: 'Retirar',
      withdrawLabel: 'Retirar la solicitud de congelamiento',
      withdrawing: 'Retirando…',
      approved: 'Tu solicitud de congelamiento fue aprobada.',
      rejected: (from: string, to: string) => `Tu solicitud del ${from} al ${to} no fue aprobada.`,
      rejectedNote: (note: string) => `Nota ${w.ofThePlace}: ${note}`,
      refused: {
        not_active: 'Solo un plan activo se puede congelar.',
        has_freeze: 'Este plan ya tiene una congelación en curso o programada.',
        has_pending: 'Ya hay una solicitud pendiente para este plan.',
        failed: 'No pudimos enviar la solicitud. Inténtalo de nuevo.',
      },
      withdrawFailed: 'No pudimos retirar la solicitud. Inténtalo de nuevo.',
    },
    home: {
      title: 'Mi página',
      hello: (firstName: string) => `Hola, ${firstName}`,
      loading: 'Cargando tu página…',
      error: 'No pudimos cargar tu página.',
      retry: 'Reintentar',
      signedIn: 'Entraste con un link de tu correo. No necesitas clave.',
    },
    next: {
      title: 'Próximo pago',
      status: {
        in_review: 'Comprobante en revisión',
        overdue: 'Vencido',
        due: 'Por pagar',
        paid: 'Al día',
      },
      get inReview() {
        return `Recibimos tu comprobante. ${w.ThePlace} lo está revisando.`
      },
      // `whose`: the dependent it is for, when it is not the student's own.
      due: (day: string, whose: string | null) => (whose ? `vence el ${day} · de ${whose}` : `vence el ${day}`),
      // On two plans, a course beside a monthly one: the plan it bills (#354).
      ofPlan: (due: string, plan: string) => `${due} · ${plan}`,
      paidUp: 'No tienes pagos pendientes.',
      paidThrough: (day: string) => `No tienes pagos pendientes. Pagado hasta el ${day}.`,
      bankLabel: 'Datos para transferir',
      bank: 'Banco',
      holder: 'Titular',
      rut: 'RUT',
      number: 'N.º cuenta',
      // `Cuenta Vista` → `Cta. Vista`, as the card writes it.
      bankName: (bank: string, accountType: string) => `${bank} · ${accountType.replace(/^Cuenta\b/, 'Cta.')}`,
      get noBank() {
        return `${w.ThePlace} todavía no publica sus datos para transferir.`
      },
      copy: 'Copiar datos',
      copied: 'Datos copiados',
      copyFailed: 'No pudimos copiar. Mantén presionado para copiar a mano.',
      // What "Copiar datos" puts on the clipboard, in full: the card masks the RUT
      // and account number, the transfer form needs them whole.
      copyText: (a: { bank: string; account_type: string; holder: string; rut: string; number: string; email: string | null }) =>
        [a.holder, `RUT ${a.rut}`, a.bank, a.account_type, `N.º ${a.number}`, a.email]
          .filter(Boolean)
          .join('\n'),
      upload: 'Subir comprobante',
      // With a proof already in review (#362).
      uploadAnother: 'Enviar otro comprobante',
    },
    // A guardian's periods and their dependents', paid in one transfer (#66).
    together: {
      title: 'Pagar todo junto',
      who: (names: string) => `De ${names}, en una sola transferencia.`,
      upload: 'Subir un comprobante por todo',
    },
    extra: {
      title: 'Cobros extra',
      due: (day: string, whose: string | null) => (whose ? `vence el ${day} · de ${whose}` : `vence el ${day}`),
      status: { open: 'Por pagar', overdue: 'Vencido', in_review: 'Comprobante en revisión' },
      upload: (title: string) => `Subir comprobante de ${title}`,
      left: (amount: string) => `quedan ${amount}`,
    },
    training: {
      title: 'Mi entrenamiento',
      // A dependent's, on their guardian's student page (#66).
      theirs: (name: string) => `Entrenamiento de ${name}`,
      // A rank drawn as a belt is a belt; one with no colours (a level) is a grade.
      belt: 'Cinturón',
      rank: 'Grado',
      since: (day: string) => `desde ${day}`,
      month: 'Este mes',
      classes: (n: number) => (n === 1 ? '1 clase' : `${n} clases`),
      total: (n: number) => `${n} en total`,
      memberSince: (month: string) => `${w.Member} desde ${month}`,
    },
    // What each class attended was about (#243); never the coach's notes.
    classes: {
      title: 'Mis clases',
      // A dependent's, on a guardian's page.
      theirs: (name: string) => `Clases de ${name}`,
      empty: 'Todavía no hay clases con asistencia.',
      when: (day: string, topic: string | null) => (topic ? `${day} · ${topic}` : day),
      tags: 'Etiquetas',
      more: (n: number) => `Ver ${n} más`,
      hours: 'Mis horas por etiqueta',
      // A dependent's.
      theirHours: (name: string) => `Horas por etiqueta de ${name}`,
      error: 'No pudimos cargar tus clases.',
      loading: 'Cargando tus clases…',
    },
    history: {
      title: 'Mis pagos',
      empty: 'Todavía no hay pagos.',
      payment: 'Pago',
      month: (month: string, whose: string | null) => (whose ? `${month} · ${whose}` : month),
      // On two plans, a course beside a monthly one: the plan it paid (#354).
      ofPlan: (title: string, plan: string) => `${title} · ${plan}`,
      sent: (when: string) => `comprobante enviado ${when}`,
      validated: (when: string) => `validado ${when}`,
      rejected: (when: string, note: string | null) => (note ? `rechazado ${when}: ${note}` : `rechazado ${when}`),
      status: { pending: 'En revisión', rejected: 'Rechazado' },
      today: (time: string) => `hoy ${time}`,
      // The rest of what settles a period (#210), so the list adds up to "Próximo pago".
      refund: 'Devolución',
      refunded: (when: string) => `te devolvieron ${when}`,
      discount: 'Descuento',
      discounted: (when: string) => `se descuenta de lo que debes · ${when}`,
      surcharge: 'Recargo',
      surcharged: (when: string) => `se suma a lo que debes · ${when}`,
      credit: 'Saldo a favor',
    },
    proof: {
      title: 'Subir comprobante',
      loading: 'Cargando tus pagos…',
      error: 'No pudimos cargar tus pagos.',
      none: 'No tienes pagos pendientes.',
      periodLabel: 'Qué estás pagando',
      period: (name: string, plan: string, due: string) => `${name} · ${plan} · vence el ${due}`,
      line: (name: string, title: string, due: string) => `${name} · ${title} · vence el ${due}`,
      outstanding: (amount: string) => `Por pagar: ${amount}`,
      inReview: (amount: string) => `Comprobante en revisión: ${amount}`,
      amountLabel: 'Monto transferido (CLP)',
      fileLabel: 'Comprobante',
      camera: 'Tomar foto',
      choose: 'Elegir archivo',
      chosen: (name: string) => `Archivo: ${name}`,
      fileHint: 'Foto o captura de la transferencia (JPG, PNG, HEIC) o PDF, hasta 10 MB.',
      submit: 'Enviar comprobante',
      sending: 'Enviando…',
      sent: 'Recibimos tu comprobante. Te avisaremos por correo cuando lo revisemos.',
      another: 'Subir otro',
      problem: {
        type: 'Ese archivo no sirve: sube una foto (JPG, PNG, HEIC) o un PDF.',
        size: 'El archivo pesa más de 10 MB. Prueba con una captura de pantalla.',
        empty: 'El archivo está vacío.',
        amount: 'Escribe el monto que transferiste.',
      },
      refused: {
        paid: 'Ese período ya está pagado.',
        upload: 'No pudimos subir el archivo. Revisa tu conexión e inténtalo de nuevo.',
        failed: 'No pudimos enviar el comprobante. Inténtalo de nuevo.',
      },
      // One transfer for several periods, a guardian's and their dependents' (#66).
      together: {
        periodsLabel: 'Qué paga esta transferencia',
        total: 'Total a transferir',
        pickTwo: 'Marca al menos dos para pagarlos en una transferencia.',
        submit: (amount: string) => `Enviar comprobante por ${amount}`,
      },
    },
  },
  join: {
    loading: 'Cargando…',
    get invalid() {
      return `Este link ya no es válido. Pídele uno nuevo ${w.toThePlace}.`
    },
    error: 'No pudimos cargar el formulario. Inténtalo de nuevo.',
    retry: 'Reintentar',
    eyebrow: 'Inscripción',
    title: (gym: string) => `Inscríbete en ${gym}`,
    program: (name: string) => `Programa: ${name}`,
    get intro() {
      return `Llena tus datos y ${w.thePlace} confirmará tu inscripción.`
    },
    firstName: 'Nombre',
    lastName: 'Apellido',
    rut: 'RUT',
    rutHint: 'Con su dígito verificador, como 12.345.678-5. Si no tienes RUT, déjalo en blanco.',
    phone: 'Teléfono (WhatsApp)',
    get phoneHint() {
      return `Un celular, como +56 9 1234 5678. ${w.ThePlace} te avisa por WhatsApp de clases y pagos.`
    },
    minorPhoneHint: 'Opcional, si tiene celular propio.',
    noWhatsapp: 'No tengo WhatsApp',
    email: 'Correo',
    minorEmailHint: 'Opcional.',
    dob: 'Fecha de nacimiento',
    guardianTitle: 'Apoderado',
    guardianIntro: 'Como es menor de edad, necesitamos los datos de su apoderado.',
    guardianName: 'Nombre del apoderado',
    guardianPhone: 'Teléfono del apoderado (WhatsApp)',
    get guardianPhoneHint() {
      return `${w.ThePlace} le avisa por WhatsApp de clases y pagos.`
    },
    guardianNoWhatsapp: 'El apoderado no tiene WhatsApp',
    guardianEmail: 'Correo del apoderado',
    // The checkbox's text, around the link to the gym's privacy notice.
    get consentBefore() {
      return `Acepto que ${w.thePlace} trate estos datos para gestionar mi inscripción, según su `
    },
    consentLink: 'política de privacidad',
    consentAfter: '.',
    // A minor's guardian's own box, around the same link (#370).
    get guardianConsentBefore() {
      return `Como apoderado, autorizo que ${w.thePlace} trate los datos del menor según su `
    },
    guardianConsentAfter:
      '. Es aparte de la inscripción: puedes no marcarla y darla después desde tu página, o retirarla cuando quieras.',
    honeypot: 'No llenes este campo',
    submit: 'Enviar inscripción',
    working: 'Enviando…',
    get done() {
      return `Listo, ${w.thePlace} confirmará tu inscripción.`
    },
    invalidFields: 'Revisa los campos marcados.',
    failed: 'No pudimos enviar tus datos. Inténtalo de nuevo.',
    humanCheck: 'No pudimos comprobar que no eres un robot. Inténtalo de nuevo.',
    tooMany: 'Hubo demasiados envíos desde aquí. Espera un rato e inténtalo de nuevo.',
    get staleNotice() {
      return `${w.ThePlace} actualizó su política de privacidad. Revísala y vuelve a enviar.`
    },
    // A required field left empty: what to write in it. No `rut`: it is optional (#165).
    required: {
      first_name: 'Escribe tu nombre.',
      last_name: 'Escribe tu apellido.',
      dob: 'Escribe tu fecha de nacimiento.',
      phone: 'Escribe tu teléfono.',
      email: 'Escribe tu correo.',
      guardian_name: 'Escribe el nombre del apoderado.',
      guardian_phone: 'Escribe el teléfono del apoderado.',
      guardian_email: 'Escribe el correo del apoderado.',
    } as Record<string, string>,
    refused: {
      missing: 'Obligatorio.',
      string_too_short: 'Obligatorio.',
      string_too_long: 'Demasiado largo.',
      rut: 'RUT no válido: revisa el dígito verificador.',
      phone: 'Escribe un celular, como +56 9 1234 5678.',
      guardian_phone: 'Escribe un celular, como +56 9 1234 5678.',
      email: 'Correo no válido.',
      guardian_email: 'Correo no válido.',
      dob: 'Escribe una fecha pasada.',
      consent: 'Necesitamos tu autorización para guardar tus datos.',
      failed: 'Revisa este campo.',
    } as Record<string, string>,
  },
  // A gym's privacy notice (#168): this template, filled in with what the gym set in
  // Ajustes. A change to the text moves `TEMPLATE_UPDATED_ON` in `api/privacy.ts`.
  privacy: {
    link: 'Privacidad',
    eyebrow: 'Privacidad',
    title: (gym: string) => `Política de privacidad de ${gym}`,
    // With no gym named yet, and on Rakin's own host with none at all (#362).
    heading: 'Política de privacidad',
    loading: 'Cargando…',
    get missing() {
      return `${w.placeIs('Este', 'Esta')} ${w.place} todavía no publica su política de privacidad.`
    },
    get noGym() {
      return `Cada ${w.place} publica su propia política de privacidad. Ábrela desde el link de tu ${w.place}: el formulario de inscripción o tu página.`
    },
    error: 'No pudimos cargar la política de privacidad. Inténtalo de nuevo.',
    retry: 'Reintentar',
    updated: (day: string) => `Última actualización: ${day}.`,
    controllerTitle: '¿Quién es responsable de tus datos?',
    controller: (legalName: string, rut: string, gym: string) =>
      `${legalName}, RUT ${rut}, que opera ${gym}, es responsable de tus datos personales.`,
    address: (address: string) => `Su domicilio es ${address}.`,
    // Around the gym's email, a link.
    contactBefore: 'Para cualquier consulta o solicitud sobre tus datos, escribe a ',
    contactAfter: '.',
    dataTitle: '¿Qué datos guardamos?',
    get data() {
      return [
        'Identificación: nombre, RUT y fecha de nacimiento.',
        'Contacto: teléfono y correo.',
        'Si eres menor de edad, los datos que entrega tu apoderado, y los suyos.',
        `Tu actividad en ${w.thePlace}: asistencia a clases, grado o cinturón si ${w.thePlace} los usa, y tiempo de entrenamiento.`,
        'Pagos: tu plan, tus cobros y pagos, y los comprobantes de transferencia que subas.',
        `Los campos adicionales que pida ${w.thePlace}, como un contacto de emergencia.`,
      ]
    },
    purposeTitle: '¿Para qué los usamos?',
    purpose: [
      'Administrar tu membresía y tus clases.',
      'Cobrar y registrar tus pagos.',
      'Contactarte por WhatsApp y correo: avisos, recordatorios de pago y links de acceso.',
      'Tu seguridad mientras entrenas.',
    ],
    purposeAfter: 'No vendemos tus datos ni los usamos para publicidad.',
    basisTitle: '¿Con qué base legal?',
    get basis() {
      return `Los tratamos porque los necesitamos para cumplir el contrato de membresía que tienes con ${w.thePlace}. Los datos de un menor de edad los tratamos con el consentimiento de su apoderado.`
    },
    processorsTitle: '¿Quién más los trata?',
    get processors() {
      return `${w.ThePlace} usa Rakin, un sistema de gestión para ${w.places}, que trata tus datos por encargo ${w.ofThePlace} y solo para prestarle ese servicio. Rakin, a su vez, se apoya en estos proveedores:`
    },
    // Every subprocessor, named by what it does: changing a provider is an edit here.
    subprocessors: [
      'Alojamiento: los servidores y la base de datos.',
      'Envío de correos.',
      'Almacenamiento de archivos, como los comprobantes de pago.',
      'Registro de errores, para corregir fallas del sistema.',
    ],
    // Listed only where the instance checks the join form for humans (`HUMAN_CHECK`).
    humanCheckProcessor: 'Verificación de que no eres un robot, solo en el formulario de inscripción.',
    processorsAfter:
      'Algunos de estos proveedores pueden guardar los datos fuera de Chile, con medidas de seguridad adecuadas.',
    retentionTitle: '¿Cuánto tiempo los guardamos?',
    retention:
      'Los registros contables, como tus pagos, se guardan por el plazo que exige la ley. Si dejas de entrenar, guardamos tu historial (inicio, pagos y grados) hasta que pidas que lo borremos. El resto de tus datos se elimina cuando lo pides.',
    rightsTitle: 'Tus derechos',
    rights:
      'Puedes pedir acceso a tus datos, rectificarlos, eliminarlos, oponerte a su tratamiento o recibirlos en un formato que puedas llevar a otro servicio (portabilidad).',
    // Around the gym's email, a link.
    rightsHowBefore: 'Para hacerlo, escribe a ',
    rightsHowAfter: '.',
    complaint:
      'Si no quedas conforme con la respuesta, puedes reclamar ante la Agencia de Protección de Datos Personales.',
    disclaimer: 'Este aviso se basa en una plantilla de Rakin y no constituye asesoría legal.',
  },
  common: {
    loading: 'Cargando…',
    // A back link that returns to where you came from (#250): named by the page when it
    // is one of these, else just "Volver".
    back: 'Volver',
    backTo: (place: string) => `Volver a ${place}`,
    places: {
      today: 'Hoy',
      get students() {
        return `${w.Members}`
      },
      member: 'la ficha',
      classes: 'Clases',
      session: 'la clase',
      payments: 'Pagos',
      proofs: 'los comprobantes',
      extra: 'Cobros extra',
      summary: 'el resumen del mes',
      expenses: 'Gastos',
      finances: 'Finanzas',
      charge: 'el cobro',
      settings: 'Ajustes',
      me: 'Mi página',
    },
    comingSoon: 'Esta sección todavía no está lista.',
    clp: (amount: number) => `$${amount.toLocaleString('es-CL')}`,
    // An amount that says which way it goes: `+$5.000` or `−$5.000`.
    signedClp: (amount: number) => `${amount < 0 ? '−' : '+'}$${Math.abs(amount).toLocaleString('es-CL')}`,
    // An adjustment by what it does to what is owed (#210): a discount, positive in the
    // member's favour, takes from it, `−$5.000`; a surcharge adds to it, `+$5.000`.
    adjustmentClp: (amount: number) => `${amount > 0 ? '−' : '+'}$${Math.abs(amount).toLocaleString('es-CL')}`,
    // Where an amount would go on a line that moves no money.
    noAmount: '—',
    span: (from: string, to: string) => `${from} – ${to}`,
    // An ISO day, `2026-12-01`, as Chile writes it: `01-12-2026`.
    day: (iso: string) => iso.split('-').reverse().join('-'),
    // An ISO day as a sentence says it: `10 de noviembre`.
    longDay: (iso: string) => `${Number(iso.slice(8, 10))} de ${MONTHS[Number(iso.slice(5, 7)) - 1]}`,
    // An ISO day as a list row says it: `8 oct`.
    shortDay: (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]!.slice(0, 3)}`,
    // An ISO day as a sentence says it, with its year: `10 de noviembre de 2026`.
    longDayYear: (iso: string) =>
      `${Number(iso.slice(8, 10))} de ${MONTHS[Number(iso.slice(5, 7)) - 1]} de ${iso.slice(0, 4)}`,
    // An ISO day with its year: `14 jun 2025`.
    dayYear: (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]!.slice(0, 3)} ${iso.slice(0, 4)}`,
    // The month an ISO day falls in, as a heading: `Noviembre`, or `Noviembre 2025` outside `year`.
    month: (iso: string, year: string) => {
      const name = MONTHS[Number(iso.slice(5, 7)) - 1]!
      const label = name[0]!.toUpperCase() + name.slice(1)
      return iso.slice(0, 4) === year ? label : `${label} ${iso.slice(0, 4)}`
    },
    // A normalised RUT, `76432109-K`, as Chile writes it: `76.432.109-K`.
    rut: (rut: string) => {
      const [body = '', digit = ''] = rut.split('-')
      return `${Number(body).toLocaleString('es-CL')}-${digit}`
    },
    today: 'hoy',
  },
  // Any form, offline (#231): one that waits for the signal, and one that does not.
  offline: {
    waiting: 'Sin conexión: se guardará cuando vuelva la señal.',
    refused: 'Sin conexión: no se guardó. Inténtalo de nuevo cuando vuelva la señal.',
    // A screen with nothing cached, in place of "Cargando…" (#362).
    reading: 'Sin conexión. Lo mostramos apenas vuelva la señal.',
    // A screen showing what it loaded before the signal went (#362).
    stale: 'Sin conexión: lo que ves puede no estar al día.',
  },
  // iOS Safari, outside the installed app (#68): Compartir, then "Agregar a inicio".
  installHint: {
    label: 'Agregar a inicio',
    title: 'Agrega Rakin a tu pantalla de inicio',
    before: 'Toca Compartir ',
    after: ' y luego «Agregar a inicio». Se abre como una app.',
    close: 'Cerrar',
  },
  // The platform's panel (#436), at /plataforma on the base host: who runs the gyms
  // Rakin hosts, apart from any gym's screens.
  // What a suspended gym's address shows on every path (#439).
  // The terms a gym accepts in the app (#499): its titular's page, and what the rest of
  // its team sees until it does.
  terms: {
    tab: 'Términos',
    title: 'Antes de empezar',
    lead: () =>
      `Lee los términos y completa los datos de ${w.thePlace}. Nada entra a Rakin hasta que los aceptes.`,
    leadOutdated: (gym: string) =>
      `Los términos cambiaron. Revisa los cambios y acéptalos para seguir administrando ${gym}.`,
    loading: 'Cargando los términos…',
    failed: 'No pudimos cargar los términos.',
    changes: 'Qué cambió',
    changesOf: (title: string, version: string) => `${title}, versión ${version}`,
    texts: 'Los términos completos',
    version: (version: string) => `Versión ${version}`,
    // Opens the texts in a page of their own, to save or print before accepting.
    print: 'Descargar o imprimir',
    printTitle: (gym: string) => `Términos de Rakin para ${gym}`,
    form: () => `Datos de ${w.thePlace}`,
    formHint: 'Aparecen en los términos tal como los escribas.',
    legalName: 'Razón social',
    legalNameHint: 'El nombre legal de la empresa, o tu nombre si la llevas como persona.',
    rut: 'RUT',
    rutHint: () => `El de ${w.thePlace}, no el tuyo, salvo que la lleves como persona.`,
    address: 'Domicilio',
    representative: 'Representante legal',
    representativeHint: () => `Quien acepta en nombre de ${w.thePlace}.`,
    contact: 'Contacto para vulneraciones de seguridad',
    contactHint: () =>
      `A quién avisamos, por correo y por teléfono, si hay una vulneración de seguridad con los datos de ${w.thePlace}.`,
    contactName: 'Nombre y cargo',
    contactEmail: 'Correo',
    contactPhone: 'Teléfono',
    otherContact: 'Otro contacto, con otro correo',
    addOther: 'Agregar otro contacto',
    removeOther: 'Quitar este contacto',
    accept: 'Aceptar y empezar',
    accepting: 'Aceptando…',
    // The button stays off until both boxes are ticked and the form is complete.
    needsBoth: 'Marca las dos casillas para aceptar.',
    invalid: 'Revisa los campos marcados.',
    acceptFailed: 'No pudimos guardar tu aceptación. Revisa tu conexión e inténtalo de nuevo.',
    changed: 'Los términos cambiaron mientras los leías. Revisa la versión nueva antes de aceptar.',
    required: 'Obligatorio.',
    refusals: {
      rut: 'Revisa el RUT.',
      email: 'Revisa el correo: no parece una dirección válida.',
      phone: 'Revisa el teléfono.',
      same_contact_email: 'El otro contacto necesita un correo distinto.',
    },
    // What the rest of the team sees while the gym has never accepted any (#499).
    pendingTitle: (gym: string) => `${gym} todavía no empieza en Rakin`,
    pending: (titular: string | null) =>
      `Falta que ${titular ?? 'el titular'} acepte los términos. Cuando lo haga, podrás usar Rakin.`,
    // Ajustes: every acceptance, and a copy of each one made in the app.
    records: 'Términos aceptados',
    recordsHint: 'Cada vez que se aceptaron los términos, y una copia de lo aceptado.',
    recordsLoading: 'Cargando…',
    recordsFailed: 'No pudimos cargar las aceptaciones.',
    noRecords: 'Todavía no hay aceptaciones.',
    inApp: (name: string | null, date: string) => `${date}, en la app${name ? `, por ${name}` : ''}`,
    outside: (date: string | null) => (date ? `Firmados fuera de la app el ${date}` : 'Firmados fuera de la app'),
    versions: (service: string | null, processor: string) =>
      service ? `Servicio ${service} · Encargo ${processor}` : `Encargo ${processor}`,
    download: 'Descargar copia',
  },
  suspended: {
    tab: 'Suspendido',
    notice: 'Este gimnasio está suspendido por ahora. Si eres parte del equipo, escribe a soporte.',
  },
  platform: {
    brand: 'Rakin · Plataforma',
    // The browser tab: `Gimnasios · Plataforma`.
    tab: 'Plataforma',
    signIn: {
      tab: 'Entrar',
      title: 'Entrar a la plataforma',
      intro: 'Escribe tu correo de operador y te enviamos un link y un código para entrar.',
      emailLabel: 'Correo',
      submit: 'Enviarme el link',
      sending: 'Enviando…',
      // The same whatever the address: it never says who is an operator.
      sent: (email: string) =>
        `Si ${email} es de un operador, te llegará un link y un código. Vencen en 15 minutos y sirven una sola vez.`,
      sentTitle: 'Revisa tu correo',
      codeLabel: 'Código del correo',
      codeHint: 'Escríbelo aquí para entrar en esta ventana, o toca el link del correo.',
      codeSubmit: 'Entrar',
      codeChecking: 'Entrando…',
      codeInvalid: 'Ese código no sirve: no es el del correo, venció o ya se usó. Pide otro si hace falta.',
      codeFailed: 'No pudimos entrar. Revisa tu conexión e inténtalo de nuevo.',
      another: 'Usar otro correo',
      tooMany: (minutes: number | null) =>
        minutes === null
          ? 'Demasiados intentos. Inténtalo de nuevo en unos minutos.'
          : `Demasiados intentos. Inténtalo de nuevo en ${minutes === 1 ? '1 minuto' : `${minutes} minutos`}.`,
      invalid: 'Revisa el correo: no parece una dirección válida.',
      failed: 'No pudimos enviar el link. Revisa tu conexión e inténtalo de nuevo.',
    },
    signOut: 'Cerrar sesión',
    signingOut: 'Cerrando sesión…',
    signOutFailed: 'No pudimos cerrar la sesión. Inténtalo de nuevo.',
    gyms: {
      title: 'Gimnasios',
      tab: 'Gimnasios',
      loading: 'Cargando gimnasios…',
      failed: 'No pudimos cargar los gimnasios.',
      empty: 'Todavía no hay gimnasios.',
      count: (n: number) => (n === 1 ? '1 gimnasio' : `${n} gimnasios`),
      columns: {
        name: 'Nombre',
        address: 'Dirección',
        titular: 'Titular',
        created: 'Creado',
        terms: 'Términos',
        members: 'Miembros',
        staff: 'Equipo',
        lastActivity: 'Última actividad',
        status: 'Estado',
      },
      noTitular: 'Sin titular',
      // Whether the gym accepted the current terms (#499).
      terms: { current: 'Vigentes', outdated: 'Términos desactualizados', pending: 'Términos pendientes' },
      // The latest accepted: `2026-11-20, aceptados el 20 nov 2026`.
      accepted: (version: string, date: string) => `${version}, aceptados el ${date}`,
      withoutCurrentTerms: 'Sin los términos vigentes',
      allCurrent: 'Todos los gimnasios aceptaron los términos vigentes.',
      noActivity: 'Sin actividad',
      status: { active: 'Activo', suspended: 'Suspendido' },
      suspendedSince: (date: string) => `desde el ${date}`,
      add: 'Nuevo gimnasio',
      // The titular's sign-in link, when the latest one did not go (#437).
      linkFailed: 'Enlace no enviado',
      resend: 'Reenviar enlace',
      resendInvite: 'Reenviar invitación',
      resending: 'Enviando…',
      resendFailed: 'No pudimos enviarlo. Inténtalo de nuevo.',
    },
    newGym: {
      title: 'Nuevo gimnasio',
      tab: 'Nuevo gimnasio',
      back: 'Gimnasios',
      loading: 'Cargando…',
      failedChoices: 'No pudimos cargar el formulario.',
      gym: 'Gimnasio',
      name: 'Nombre del gimnasio',
      slug: 'Dirección',
      slugHint: 'Minúsculas, números y guiones. Es parte de la dirección del gimnasio.',
      checking: 'Revisando…',
      // The address the slug makes, as it is typed.
      willBe: (address: string) => `Quedará en ${address}`,
      timezone: 'Zona horaria',
      grading: 'Grados',
      gradingHint: 'Con un sistema de grados, el gimnasio parte con esa actividad y sus palabras.',
      owner: 'Titular',
      ownerEmail: 'Correo del titular',
      ownerEmailHint: 'Le enviamos aquí la invitación para aceptar los términos.',
      ownerName: 'Nombre del titular',
      ownerRut: 'RUT (opcional)',
      ownerPhone: 'Teléfono (opcional)',
      // The terms are accepted in the app by the titular (#499), not given here.
      termsNote:
        'El titular acepta los Términos de servicio y de encargo en la app, la primera vez que entra. Hasta entonces el gimnasio no recibe datos.',
      submit: 'Crear gimnasio',
      working: 'Creando…',
      invalid: 'Revisa los campos marcados.',
      failed: 'No pudimos crear el gimnasio. Revisa tu conexión e inténtalo de nuevo.',
      // Why a slug cannot be the gym's, as typed or as the API refused it.
      problems: {
        format: 'Solo minúsculas, números y guiones, hasta 63, sin guion al inicio ni al final.',
        reserved: 'Esa dirección está reservada para Rakin.',
        taken: 'Otro gimnasio ya tiene esa dirección.',
      },
      refusals: {
        slug_format: 'Solo minúsculas, números y guiones, hasta 63, sin guion al inicio ni al final.',
        slug_reserved: 'Esa dirección está reservada para Rakin.',
        slug_taken: 'Otro gimnasio ya tiene esa dirección.',
        unknown_preset: 'Elige una opción.',
        timezone: 'Elige una zona horaria.',
        owner_email: 'Revisa el correo: no parece una dirección válida.',
        owner_rut: 'Revisa el RUT.',
        owner_phone: 'Revisa el teléfono.',
      },
      created: 'Gimnasio creado',
      createdIntro: (name: string) => `${name} ya está en su dirección:`,
      copy: 'Copiar dirección',
      copied: 'Dirección copiada.',
      // Said once the gym is made: its owner has the invitation, with its link to sign in.
      linkSent: (email: string) =>
        `Le enviamos a ${email} la invitación para aceptar los términos; su enlace dura 7 días. Si vence, puedes reenviarla desde la ficha del gimnasio.`,
      another: 'Crear otro',
      toList: 'Volver a gimnasios',
    },
    // A gym's edit screen (#438): its name and contact, the terms, its address.
    gym: {
      tab: 'Editar gimnasio',
      back: 'Gimnasios',
      loading: 'Cargando el gimnasio…',
      failed: 'No pudimos cargar el gimnasio.',
      contact: 'Nombre y contacto',
      name: 'Nombre del gimnasio',
      ownerName: 'Nombre del titular',
      ownerPhone: 'Teléfono del titular',
      ownerEmail: 'Correo del titular',
      ownerEmailHint: 'Puedes corregirlo mientras el titular no haya entrado al gimnasio.',
      ownerEmailLocked: 'El titular ya entró al gimnasio: su correo solo cambia con el traspaso de la cuenta.',
      // Never offered here: a new titular goes through the handover (#321).
      titularNote: 'Para cambiar de titular se usa el traspaso de la cuenta, que todavía no está disponible.',
      save: 'Guardar cambios',
      saving: 'Guardando…',
      saved: 'Cambios guardados.',
      unchanged: 'No había nada que cambiar.',
      handover: 'No se guardó: el titular ya entró al gimnasio, y cambiar su correo es un traspaso de la cuenta.',
      invalid: 'Revisa los campos marcados.',
      saveFailed: 'No pudimos guardar. Revisa tu conexión e inténtalo de nuevo.',
      refusals: {
        name: 'Escribe un nombre.',
        owner_name: 'Escribe un nombre.',
        owner_email: 'Revisa el correo: no parece una dirección válida.',
        owner_phone: 'Revisa el teléfono.',
        signed_on_future: 'La fecha no puede ser futura.',
        signed_on_early: 'La fecha es anterior a esta versión de los términos.',
        date_type: 'Obligatorio.',
        date_from_datetime_parsing: 'Escribe una fecha.',
        slug_format: 'Solo minúsculas, números y guiones, hasta 63, sin guion al inicio ni al final.',
        slug_reserved: 'Esa dirección está reservada para Rakin.',
        slug_taken: 'Otro gimnasio ya tiene esa dirección, o redirige desde ella.',
      },
      terms: 'Términos',
      termsState: { current: 'Vigentes', outdated: 'Desactualizados', pending: 'Pendientes' },
      noTerms: 'El titular todavía no acepta los términos. Hasta entonces el gimnasio no recibe datos.',
      // One acceptance (#499): `20 nov 2026, en la app, por Ana · Servicio 2026-11-20 · Encargo 2026-11-20`.
      inApp: (date: string, name: string | null) => `${date}, en la app${name ? `, por ${name}` : ''}`,
      outside: (date: string | null) => (date ? `Fuera de la app, firmada el ${date}` : 'Fuera de la app'),
      versions: (service: string | null, processor: string) =>
        service ? `Servicio ${service} · Encargo ${processor}` : `Encargo ${processor}`,
      current: 'vigente',
      resendInvite: 'Reenviar invitación',
      resendLink: 'Reenviar enlace de ingreso',
      sending: 'Enviando…',
      sent: (email: string) => `Enviado a ${email}.`,
      sendFailed: 'No pudimos enviarlo. Inténtalo de nuevo.',
      record: 'Registrar',
      recordVersion: (service: string, processor: string) =>
        `Para unos términos firmados en papel: registra los vigentes, servicio ${service} y encargo ${processor}.`,
      signedOn: 'Registrar una aceptación fuera de la app',
      recording: 'Registrando…',
      recorded: 'Aceptación registrada.',
      alreadySigned: 'Esas versiones ya estaban registradas: se mantiene la primera fecha.',
      recordFailed: 'No pudimos registrar la aceptación. Inténtalo de nuevo.',
      address: 'Dirección',
      currentAddress: 'Dirección actual',
      // A slug the gym had, which still sends its visitors here.
      redirects: (address: string, date: string) => `${address} redirige aquí hasta el ${date}.`,
      newSlug: 'Nueva dirección',
      newSlugHint: 'Minúsculas, números y guiones.',
      checking: 'Revisando…',
      willBe: (address: string) => `Quedará en ${address}`,
      problems: {
        format: 'Solo minúsculas, números y guiones, hasta 63, sin guion al inicio ni al final.',
        reserved: 'Esa dirección está reservada para Rakin.',
        taken: 'Otro gimnasio ya tiene esa dirección, o redirige desde ella.',
      },
      rename: 'Cambiar dirección',
      confirmTitle: 'Cambiar la dirección',
      confirmMove: (from: string, to: string) => `El gimnasio pasa de ${from} a ${to}.`,
      confirmRedirect: (from: string) =>
        `Durante 90 días, ${from} redirige a la nueva dirección, y ningún otro gimnasio puede usarla.`,
      confirmSessions: 'Quienes tengan la sesión abierta en la dirección antigua tendrán que volver a entrar.',
      confirmType: 'Escribe la nueva dirección para confirmar',
      confirm: 'Cambiar dirección',
      renaming: 'Cambiando…',
      cancel: 'Cancelar',
      renamed: (address: string) => `Listo: el gimnasio está en ${address}.`,
      renameFailed: 'No pudimos cambiar la dirección. Inténtalo de nuevo.',
      // Suspending, resuming and removing (#439).
      suspension: 'Suspensión',
      active: 'El gimnasio está activo.',
      suspendedSince: (date: string) => `Suspendido desde el ${date}.`,
      suspendedReason: (reason: string) => `Motivo: ${reason}`,
      suspendEffects:
        'Mientras está suspendido, su dirección muestra solo un aviso, nadie puede entrar, las sesiones abiertas se cierran y no se envían correos automáticos. Sus datos se mantienen.',
      reason: 'Motivo',
      reasonHint: 'Queda registrado. No escribas datos de personas.',
      reasonRequired: 'Escribe el motivo.',
      suspend: 'Suspender',
      suspending: 'Suspendiendo…',
      confirmSuspendTitle: 'Suspender el gimnasio',
      confirmSuspend: (address: string) => `${address} mostrará solo un aviso, y nadie podrá entrar hasta que lo reanudes.`,
      resume: 'Reanudar',
      resuming: 'Reanudando…',
      confirmResumeTitle: 'Reanudar el gimnasio',
      confirmResume:
        'Su gente vuelve a entrar. En la próxima corrida nocturna se ponen al día los cobros, congelamientos y vencimientos de los días suspendido; los correos de esos días no se envían.',
      suspendedDone: 'Gimnasio suspendido.',
      resumedDone: 'Gimnasio reanudado.',
      alreadySo: 'Ya estaba así: no cambió nada.',
      suspendFailed: 'No pudimos suspender el gimnasio. Inténtalo de nuevo.',
      resumeFailed: 'No pudimos reanudar el gimnasio. Inténtalo de nuevo.',
      remove: 'Eliminar',
      removeHint: 'Solo un gimnasio suspendido se puede eliminar.',
      removeTitle: 'Eliminar el gimnasio',
      // The end of service of the Términos de encargo, clause 14; the numbers come from the API.
      removeIntro: 'Eliminar sigue los Términos de encargo (cláusula 14, «Al terminar»): nunca se borra de inmediato. Si empezara hoy:',
      removeExport: (days: number, date: string) =>
        `Primero, ${days} días para que el gimnasio pida una copia completa de sus datos y archivos, hasta el ${date}. Mientras no exista esa copia, se le entrega la exportación del libro de pagos.`,
      removeDelete: (days: number, date: string) =>
        `Después, sus datos y archivos se borran dentro de ${days} días, a más tardar el ${date}. Antes, solo si el gimnasio lo pide por escrito.`,
      removeBackups: (days: number, date: string) =>
        `Las copias de respaldo se renuevan dentro de ${days} días más: desde el ${date} ninguna lo contiene.`,
      removeUnavailable: 'Todavía no está disponible: falta definir cómo se borran los datos de un gimnasio.',
      close: 'Cerrar',
    },
    // Asked before an action that needs a recent proof of who is signed in (#438).
    reauth: {
      title: 'Confirma que eres tú',
      sending: 'Enviando un código a tu correo…',
      sent: (email: string) => `Te enviamos un código a ${email}. Vence en 15 minutos y sirve una sola vez.`,
      sendFailed: 'No pudimos enviar el código.',
      again: 'Enviar otro código',
      codeLabel: 'Código del correo',
      submit: 'Confirmar',
      checking: 'Confirmando…',
      invalid: 'Ese código no sirve: no es el del correo, venció o ya se usó.',
      failed: 'No pudimos confirmar. Revisa tu conexión e inténtalo de nuevo.',
      tooMany: 'Demasiados intentos. Inténtalo de nuevo en unos minutos.',
      cancel: 'Cancelar',
    },
  },
  notFound: {
    title: 'Página no encontrada',
    body: 'La dirección que abriste no existe.',
    backToAdmin: 'Volver a Hoy',
  },
} as const

export type Messages = typeof es

export const t: Messages = es
