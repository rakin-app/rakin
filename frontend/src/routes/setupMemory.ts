import { useState } from 'react'

/** Where this browser remembers Hoy's "Configura tu academia": per host, which is per gym,
 * and per person, for a gym served on the instance's own address. */
export function setupDoneKey(personId: string): string {
  return `rakin:setup-done:${window.location.host}:${personId}`
}

/**
 * What the key holds. `done`: the gym was seen set up (its programs, plans and members),
 * so the card went by itself; a gym with no students still sees it. `hidden`: the owner
 * hid it with "Ocultar" (#573), so it is gone until asked for. `asked`: "Ver primeros
 * pasos" in Ajustes › Cuenta asked for it back, so it shows, set up or not, until hidden.
 */
export type SetupMemory = 'done' | 'hidden' | 'asked' | null

const STORED: Record<Exclude<SetupMemory, null>, string> = { done: '1', hidden: 'hidden', asked: 'asked' }

// Storage can be refused (a private window); then the checklist just asks again.
export function readSetup(key: string): SetupMemory {
  try {
    const value = window.localStorage.getItem(key)
    if (value === STORED.done) return 'done'
    if (value === STORED.hidden) return 'hidden'
    if (value === STORED.asked) return 'asked'
    return null
  } catch {
    return null
  }
}

export function writeSetup(key: string, memory: Exclude<SetupMemory, null>) {
  try {
    window.localStorage.setItem(key, STORED[memory])
  } catch {
    // Not remembered: the next visit asks the questions again.
  }
}

/** The key's memory, and a way to change it that redraws whoever reads it. With no key
 * (who is signed in is not known yet), nothing is remembered. */
export function useSetupMemory(key: string | null): [SetupMemory, (memory: Exclude<SetupMemory, null>) => void] {
  const [written, setWritten] = useState<{ key: string; memory: SetupMemory } | null>(null)
  const memory = key === null ? null : written?.key === key ? written.memory : readSetup(key)
  const write = (next: Exclude<SetupMemory, null>) => {
    if (key === null) return
    writeSetup(key, next)
    setWritten({ key, memory: next })
  }
  return [memory, write]
}
