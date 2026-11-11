import { useEffect, useRef, useState } from 'react'

/**
 * Unsaved text a form keeps when the session ends under it (#212). A form on screen
 * says what it holds (`useKeptDraft`); when a 401 sends the person to sign in, the
 * router writes those to `localStorage` (`keepDrafts`), and the form gives them back
 * the next time it opens for the same person (`useRestoredDraft`), once. `localStorage`, not
 * `sessionStorage`: the sign-in link is often opened in another tab. A day old, or
 * after "Cerrar sesión", they are gone.
 */
const PREFIX = 'rakin.draft:'
const MAX_AGE_MS = 24 * 60 * 60 * 1000

export type Draft = Record<string, string>

type Kept = { person: string; at: number; values: Draft }

// The drafts on screen right now, each read when the session ends.
const live = new Map<string, () => Draft | null>()

/** Writes every unsaved draft on screen, as `person`'s; nothing when who it was is unknown. */
export function keepDrafts(person: string | undefined): void {
  if (!person) return
  for (const [key, read] of live) {
    const values = read()
    if (!values) continue
    const kept: Kept = { person, at: Date.now(), values }
    try {
      localStorage.setItem(PREFIX + key, JSON.stringify(kept))
    } catch {
      // Storage off or full: the text goes, as it did before.
    }
  }
}

/** The draft kept under `key` for `person`, if one is: read only, `dropDraft` removes it. */
function keptDraft(key: string, person: string | undefined): Draft | null {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (!raw || !person) return null
    const kept = JSON.parse(raw) as Partial<Kept>
    if (kept.person !== person || typeof kept.at !== 'number' || Date.now() - kept.at > MAX_AGE_MS) return null
    const values = kept.values
    if (typeof values !== 'object' || values === null) return null
    return Object.fromEntries(Object.entries(values).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))
  } catch {
    return null
  }
}

function dropDraft(key: string): void {
  try {
    localStorage.removeItem(PREFIX + key)
  } catch {
    // Nothing to drop.
  }
}

/** "Cerrar sesión": no draft outlives it. */
export function forgetDrafts(): void {
  try {
    for (const key of Object.keys(localStorage)) if (key.startsWith(PREFIX)) localStorage.removeItem(key)
  } catch {
    // Storage off: nothing was kept.
  }
}

/**
 * The draft kept under `key` for `person`, read once as the form opens, and then
 * dropped: the form holds it now, and keeps it again if the session ends again.
 */
export function useRestoredDraft(key: string, person: string | undefined): Draft | null {
  const [kept] = useState(() => keptDraft(key, person))
  useEffect(() => {
    if (kept) dropDraft(key)
  }, [kept, key])
  return kept
}

/**
 * Registers what a form holds unsaved under `key`, while it is on screen: `values`
 * when there is something to lose, `null` when there is not.
 */
export function useKeptDraft(key: string, values: Draft | null): void {
  const latest = useRef(values)
  useEffect(() => {
    latest.current = values
  })
  useEffect(() => {
    const read = () => latest.current
    live.set(key, read)
    return () => {
      if (live.get(key) === read) live.delete(key)
    }
  }, [key])
}
