import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { myselfQuery } from './api/me'

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
  const gym = useGymName()
  useEffect(() => {
    if (screen !== undefined) document.title = pageTitle(screen, gym)
  }, [screen, gym])
}
