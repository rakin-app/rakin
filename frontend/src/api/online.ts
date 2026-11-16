import { onlineManager } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'

const subscribe = (onChange: () => void) => onlineManager.subscribe(onChange)
const read = () => onlineManager.isOnline()

/** Whether the device has a signal, as TanStack Query sees it: a query offline pauses. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, read)
}

// How many loading lines say "Sin conexión" right now (#362): with one on screen, the
// screen has said so already, and `OfflineNotice` says nothing of out-of-date data.
let offlineLines = 0
const listeners = new Set<() => void>()

function changeOfflineLines(by: number) {
  offlineLines += by
  listeners.forEach((listener) => listener())
}

/** Counts this line among those saying "Sin conexión" while `offline`. */
export function useOfflineLine(offline: boolean) {
  useEffect(() => {
    if (!offline) return
    changeOfflineLines(1)
    return () => changeOfflineLines(-1)
  }, [offline])
}

/** Whether a loading line on screen says "Sin conexión". */
export function useOfflineLineShown(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange)
      return () => listeners.delete(onChange)
    },
    () => offlineLines > 0,
  )
}
