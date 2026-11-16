// How far back a day of someone's history may go (backend `HISTORY_WINDOW_YEARS`): a
// typo guard. "Alumno desde", the day they left (#294), and a grade from before Rakin
// (#296).
export const HISTORY_WINDOW_YEARS = 60

/** The `YYYY-MM-DD` `years` before `iso`. */
export function yearsBefore(iso: string, years: number): string {
  return `${String(Number(iso.slice(0, 4)) - years).padStart(4, '0')}${iso.slice(4)}`
}
