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

/** `8 nov 14:12`, in `timeZone`. */
export function dayTime(iso: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('es-CL', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  }).formatToParts(new Date(iso))
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  return `${part('day')} ${part('month').replace('.', '')} ${part('hour')}:${part('minute')}`
}

/** `dom 8 nov`. */
export function weekdayDay(date: Date): string {
  return date.toLocaleDateString('es-CL', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '')
}

/** `19:00`, in `timeZone`. */
export function clockTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone }).format(
    new Date(iso),
  )
}
