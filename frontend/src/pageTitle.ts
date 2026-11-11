import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { myselfQuery } from './api/me'

/** What a tab is named after where no gym is known, as `index.html` names it. */
export const RAKIN = 'Rakin'

/** A tab's title: `Alumnos · Academia Sur`, or the screen alone while the gym is not known. */
export function pageTitle(screen: string, gym: string | undefined): string {
  return gym ? `${screen} · ${gym}` : screen
}

/** The gym's name, for the sidebar, Hoy's eyebrow and the tab; `undefined` until it is known. */
export function useGymName(): string | undefined {
  return useQuery(myselfQuery()).data?.gym_name
}

/**
 * Names the browser tab after the screen and the gym (#177), so the tab, the history and a
 * screen reader can tell Alumnos from Pagos. `undefined` while the screen's own name loads.
 */
export function usePageTitle(screen: string | undefined) {
  useDocumentTitle(screen, useGymName())
}

/**
 * The same, for the screens that name the gym from what they load themselves (#213):
 * sign-in, the join form and the privacy notice, with no session to ask, and the student page.
 */
export function useDocumentTitle(screen: string | undefined, gym: string | undefined) {
  useEffect(() => {
    if (screen !== undefined) document.title = pageTitle(screen, gym)
  }, [screen, gym])
}
