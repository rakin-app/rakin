import { onlineManager, useMutationState, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useMemo, useSyncExternalStore } from 'react'
import { useOfflineLineShown } from '../api/online'
import { OfflineError } from '../api/submit'
import { t } from '../i18n/es'
import './OfflineNotice.css'

const copy = t.offline

// The newest mutation in the cache, by id: ids only grow.
function lastMutationId(client: QueryClient): number {
  return client
    .getMutationCache()
    .getAll()
    .reduce((last, m) => Math.max(last, m.mutationId), 0)
}

/**
 * Null while online; offline, the last mutation made before the signal went. A refusal
 * from an earlier spell stays in the cache for minutes, and must not speak for this one.
 */
function offlineSpell(client: QueryClient) {
  let since: number | null = null
  const read = () => {
    if (onlineManager.isOnline()) since = null
    else since ??= lastMutationId(client)
    return since
  }
  return {
    subscribe: (onChange: () => void) =>
      onlineManager.subscribe((online) => {
        since = online ? null : lastMutationId(client)
        onChange()
      }),
    read,
  }
}

/**
 * Whether a query on screen holds an answer, which offline may be out of date. Queries
 * marked `meta.ambient` (the host, who is signed in, a join form) are no screen's
 * content, so /ingresar and the join form have none (#362).
 */
function useDataOnScreen(): boolean {
  const cache = useQueryClient().getQueryCache()
  return useSyncExternalStore(
    (onChange) => cache.subscribe(onChange),
    () =>
      cache.findAll({ type: 'active' }).some((query) => query.state.data !== undefined && !query.meta?.ambient),
  )
}

function useOfflineSince(): number | null {
  const client = useQueryClient()
  const spell = useMemo(() => offlineSpell(client), [client])
  return useSyncExternalStore(spell.subscribe, spell.read)
}

/**
 * What a form cannot say while it waits on "Guardando…" (#231), for every screen at
 * once: a submission paused offline will be saved when the signal is back, and one a
 * form refused offline (`offline: 'refuse'`) was not saved. With neither, offline, it
 * says what is on screen may be out of date (#362), where a query keeps its last
 * answer and no loading line has said "Sin conexión" already. The live region is
 * always there, empty when there is nothing to say, so a screen reader hears the
 * message appear; it is not a `status`, which is each screen's own.
 */
export function OfflineNotice() {
  const since = useOfflineSince()
  const waiting = useMutationState({ filters: { predicate: (m) => m.state.isPaused } }).length
  const refused = useMutationState({
    filters: { status: 'error', predicate: (m) => m.state.error instanceof OfflineError },
    select: (m) => m.mutationId,
  })
  const refusedNow = since !== null && refused.some((id) => id > since)
  const dataOnScreen = useDataOnScreen()
  const saidOffline = useOfflineLineShown()
  const stale = since !== null && dataOnScreen && !saidOffline
  const message = waiting > 0 ? copy.waiting : refusedNow ? copy.refused : stale ? copy.stale : null
  return (
    <div className="offline-notice" aria-live="polite">
      {message && <p className="offline-notice__message">{message}</p>}
    </div>
  )
}
