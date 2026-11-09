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
