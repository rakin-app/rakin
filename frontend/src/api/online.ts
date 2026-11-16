import { onlineManager } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

const subscribe = (onChange: () => void) => onlineManager.subscribe(onChange)
const read = () => onlineManager.isOnline()

/** Whether the device has a signal, as TanStack Query sees it: a query offline pauses. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, read)
}
