import type { AriaRole, ReactNode } from 'react'
import { useOfflineLine, useOnline } from '../api/online'
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
  return (
    <p className={className} role={role}>
      <LoadingText>{children}</LoadingText>
    </p>
  )
}

/** The same words, for a component that draws its own line (`EmptyState`). */
export function LoadingText({ children }: { children: ReactNode }) {
  const online = useOnline()
  useOfflineLine(!online)
  return online ? children : t.offline.reading
}
