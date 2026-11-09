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
  },
  common: {
    comingSoon: 'Esta sección todavía no está lista.',
  },
  notFound: {
    title: 'Página no encontrada',
    body: 'La dirección que abriste no existe.',
    backToAdmin: 'Volver a Hoy',
  },
} as const

export type Messages = typeof es

export const t: Messages = es
