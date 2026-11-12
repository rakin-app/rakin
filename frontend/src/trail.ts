import type { RouterHistory } from '@tanstack/react-router'

/** One history entry this page load has shown. */
export type TrailEntry = { href: string; pathname: string }

/**
 * The history entries the app itself has shown since the page loaded, by their
 * history index (#250). An entry before the first one shown (a deep link, a fresh
 * tab, a reload) is unknown, so a back link there falls back to its fixed parent.
 */
const trails = new WeakMap<RouterHistory, TrailEntry[]>()

function entryOf(location: RouterHistory['location']): TrailEntry {
  return { href: location.href, pathname: location.pathname }
}

/** Starts recording `history`'s entries; call once, as the router is made. */
export function trackTrail(history: RouterHistory) {
  const entries: TrailEntry[] = []
  entries[history.location.state.__TSR_index] = entryOf(history.location)
  trails.set(history, entries)
  history.subscribe(({ location, action }) => {
    const index = location.state.__TSR_index
    // A new entry drops the ones ahead of it, as the browser does.
    if (action.type === 'PUSH') entries.length = index
    entries[index] = entryOf(location)
  })
}

/** The entry before the one at `index`, when the app showed it. */
export function previousEntry(history: RouterHistory, index: number): TrailEntry | undefined {
  return index > 0 ? trails.get(history)?.[index - 1] : undefined
}
