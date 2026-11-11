import { onlineManager, useMutationState } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { OfflineError } from '../api/submit'
import { t } from '../i18n/es'
import './OfflineNotice.css'

const copy = t.offline

function useOnline(): boolean {
  return useSyncExternalStore(
    (onChange) => onlineManager.subscribe(onChange),
    () => onlineManager.isOnline(),
  )
}

/**
 * What a form cannot say while it waits on "Guardando…" (#231), for every screen at
 * once: a submission paused offline will be saved when the signal is back, and one a
 * form refused offline (`offline: 'refuse'`) was not saved. The live region is always
 * there, empty when there is nothing to say, so a screen reader hears the message
 * appear; it is not a `status`, which is each screen's own.
 */
export function OfflineNotice() {
  const online = useOnline()
  const waiting = useMutationState({ filters: { predicate: (m) => m.state.isPaused } }).length
  const refused = useMutationState({
    filters: { status: 'error', predicate: (m) => m.state.error instanceof OfflineError },
  }).length
  const message = waiting > 0 ? copy.waiting : !online && refused > 0 ? copy.refused : null
  return (
    <div className="offline-notice" aria-live="polite">
      {message && <p className="offline-notice__message">{message}</p>}
    </div>
  )
}
