// Dates as the admin screens show them, in Chilean Spanish.

// An ISO day (`2026-11-10`) as a local date, not UTC midnight; a timestamp as is.
export function toDate(iso: string): Date {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(iso)
}

/** `10 nov`. */
export function shortDay(iso: string): string {
  return toDate(iso).toLocaleDateString('es-CL', { day: 'numeric', month: 'short' })
}

/** `noviembre`. */
export function monthName(iso: string): string {
  return toDate(iso).toLocaleDateString('es-CL', { month: 'long' })
}

/** `mar 2024`. */
export function monthYear(iso: string): string {
  return toDate(iso).toLocaleDateString('es-CL', { month: 'short', year: 'numeric' })
}
