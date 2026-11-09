/**
 * Every user-facing string in the SPA. Components read from here and never
 * inline copy (enforced by `react/jsx-no-literals` in eslint.config.js).
 * English, when it comes, is a second file with the same shape.
 */
export const es = {
  app: {
    name: 'rakin',
  },
  nav: {
    label: 'Principal',
    today: 'Hoy',
    students: 'Alumnos',
    classes: 'Clases',
    payments: 'Pagos',
    pendingBadge: (n: number) => (n === 1 ? '1 comprobante por revisar' : `${n} comprobantes por revisar`),
  },
  admin: {
    today: { title: 'Hoy' },
    students: {
      title: 'Alumnos',
      searchLabel: 'Buscar alumno',
      searchPlaceholder: 'Nombre, teléfono o RUT',
      filtersLabel: 'Filtros',
      statusLabel: 'Estado',
      planLabel: 'Plan',
      allPlans: 'Todos los planes',
      inactivePlan: (name: string) => `${name} (inactivo)`,
      clearFilters: 'Limpiar filtros',
      count: (n: number) => (n === 1 ? '1 alumno' : `${n.toLocaleString('es-CL')} alumnos`),
      noPlan: 'Sin plan',
      empty: 'Todavía no hay alumnos.',
      noMatches: 'Ningún alumno coincide con la búsqueda.',
      loading: 'Cargando alumnos…',
      error: 'No pudimos cargar los alumnos.',
      retry: 'Reintentar',
      more: 'Ver más',
      status: {
        active: 'Activo',
        trial: 'Prueba',
        frozen: 'Congelado',
        lapsed: 'Vencido',
        cancelled: 'Cancelado',
      },
      guardianOf: (name: string) => `Apoderado: ${name}`,
      dependentsCount: (n: number) => (n === 1 ? '1 a cargo' : `${n} a cargo`),
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
      addTitle: 'Agregar a alguien a cargo',
      addHint: 'Sin teléfono ni correo: todo le llega al apoderado.',
      name: 'Nombre',
      rut: 'RUT (opcional)',
      dob: 'Fecha de nacimiento (opcional)',
      add: 'Agregar',
      linkTitle: 'O vincular a un alumno que ya está',
      linkSearch: 'Buscar a quién vincular',
      link: 'Vincular',
      linkLabel: (name: string) => `Vincular a ${name}`,
      noMatches: 'Ningún alumno coincide.',
      refused: {
        has_guardian: 'Esa persona ya tiene un apoderado.',
        one_level:
          'Un apoderado no puede estar a cargo de otro, y quien está a cargo no puede ser apoderado.',
        invalid: 'Revisa los datos: el RUT o la fecha no son válidos.',
        failed: 'No pudimos guardar el cambio. Inténtalo de nuevo.',
      },
    },
    classes: { title: 'Clases' },
    payments: { title: 'Libro de pagos' },
  },
  me: {
    home: { title: 'Mi página' },
    proof: {
      title: 'Subir comprobante',
      loading: 'Cargando tus pagos…',
      error: 'No pudimos cargar tus pagos.',
      none: 'No tienes pagos pendientes.',
      periodLabel: 'Qué estás pagando',
      period: (name: string, plan: string, due: string) => `${name} · ${plan} · vence el ${due}`,
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
    },
  },
  common: {
    comingSoon: 'Esta sección todavía no está lista.',
    clp: (amount: number) => `$${amount.toLocaleString('es-CL')}`,
    // An ISO day, `2026-12-01`, as Chile writes it: `01-12-2026`.
    day: (iso: string) => iso.split('-').reverse().join('-'),
  },
  notFound: {
    title: 'Página no encontrada',
    body: 'La dirección que abriste no existe.',
    backToAdmin: 'Volver a Hoy',
  },
} as const

export type Messages = typeof es

export const t: Messages = es
