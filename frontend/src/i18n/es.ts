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
    students: { title: 'Alumnos' },
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
