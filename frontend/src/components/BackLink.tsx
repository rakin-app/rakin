import { useRouter, useRouterState } from '@tanstack/react-router'
import type { MouseEvent, ReactNode } from 'react'
import { SIGN_IN_PATH } from '../api/auth'
import { t } from '../i18n/es'
import { previousEntry, type TrailEntry } from '../trail'

const places = t.common.places

// The pages a back link can name, by path. Static paths before the `$id` ones.
const PLACES: ReadonlyArray<readonly [RegExp, string]> = [
  [/^\/admin\/?$/, places.today],
  [/^\/admin\/alumnos\/?$/, places.students],
  [/^\/admin\/alumnos\/(importar|nuevo)\/?$/, ''],
  [/^\/admin\/alumnos\/[^/]+\/?$/, places.member],
  [/^\/admin\/clases\/?$/, places.classes],
  [/^\/admin\/clases\/[^/]+\/?$/, places.session],
  [/^\/admin\/pagos\/?$/, places.payments],
  [/^\/admin\/pagos\/comprobantes\/?$/, places.proofs],
  [/^\/admin\/pagos\/cobros\/?$/, places.extra],
  [/^\/admin\/pagos\/cobros\/nuevo\/?$/, ''],
  [/^\/admin\/pagos\/cobros\/[^/]+\/?$/, places.charge],
  [/^\/admin\/ajustes\/?$/, places.settings],
  [/^\/me\/?$/, places.me],
]

/** The name of the page at `pathname`, when it is one a back link names. */
export function placeOf(pathname: string): string | undefined {
  return PLACES.find(([path]) => path.test(pathname))?.[1] || undefined
}

export type Back = {
  /** The page it returns to, when the app showed it just before this one. */
  previous?: TrailEntry
  /** Where it goes: the previous page, else the fixed parent. */
  href: string
  /** "Volver a Pagos", "Volver", or the fixed parent's own label. */
  label: string
  /** The previous page's name, when it is one we name. */
  place?: string
  go: () => void
}

/**
 * Back to where you came from, as the browser's back button does, when that was a page
 * of the app; else, after a deep link, a fresh tab or signing in, to `fallback` (#250).
 */
export function useBack(fallback: string, fallbackLabel: string): Back {
  const router = useRouter()
  const index = useRouterState({ select: (state) => state.location.state.__TSR_index })
  const entry = previousEntry(router.history, index)
  // Signing in is no page to return to.
  const previous = entry && entry.pathname !== SIGN_IN_PATH ? entry : undefined
  if (!previous) {
    return {
      href: fallback,
      label: fallbackLabel,
      go: () => void router.navigate({ href: fallback }),
    }
  }
  const place = placeOf(previous.pathname)
  return {
    previous,
    href: previous.href,
    label: place ? t.common.backTo(place) : t.common.back,
    place,
    go: () => router.history.back(),
  }
}

/**
 * The back link of a screen's header, labelled by where it goes. Its children are an
 * icon, or a function of the destination for visible text.
 */
export function BackLink({
  to,
  label,
  className,
  children,
}: {
  /** The fixed parent, for when the app did not open this page. */
  to: string
  /** The fixed parent's label, "Volver a Alumnos". */
  label: string
  className?: string
  children: ReactNode | ((back: Back) => ReactNode)
}) {
  const back = useBack(to, label)
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    // A new tab or window opens the link itself.
    if (event.defaultPrevented || event.button !== 0) return
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    back.go()
  }
  return (
    <a href={back.href} className={className} aria-label={back.label} onClick={onClick}>
      {typeof children === 'function' ? children(back) : children}
    </a>
  )
}
