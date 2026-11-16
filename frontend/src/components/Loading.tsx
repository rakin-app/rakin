import type { AriaRole, ReactNode } from 'react'
import { useOnline } from '../api/online'
import { t } from '../i18n/es'

type Props = {
  className?: string
  role?: AriaRole
  /** What the screen says while it loads, "Cargando…". */
  children: ReactNode
}

/**
 * A screen's loading line (#362). Offline a query with nothing cached pauses rather than
 * fails, so "Cargando…" would never end: it says there is no signal instead. The query
 * resumes by itself when the signal is back.
 */
export function Loading({ className, role, children }: Props) {
  const online = useOnline()
  return (
    <p className={className} role={role}>
      {online ? children : t.offline.reading}
    </p>
  )
}
