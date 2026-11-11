import { useRouterState } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'

/**
 * The page rising into place when the route changes (#199): the content fades in from
 * `--rise-distance` below, once, over `--duration-slow`. Under reduced motion it only
 * fades. Played on the element rather than by remounting it, so a screen whose list and
 * detail share a page (#178–#181) keeps its state across the change.
 */
export function useRise<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const first = useRef(true)

  useEffect(() => {
    // The first page arrives with the app; only a change of route rises.
    if (first.current) {
      first.current = false
      return
    }
    const element = ref.current
    if (!element || typeof element.animate !== 'function') return
    const styles = getComputedStyle(element)
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    const distance = styles.getPropertyValue('--rise-distance').trim() || '8px'
    const animation = element.animate(
      still
        ? [{ opacity: 0 }, { opacity: 1 }]
        : [
            { opacity: 0, transform: `translateY(${distance})` },
            { opacity: 1, transform: 'none' },
          ],
      {
        duration: milliseconds(styles.getPropertyValue('--duration-slow'), 500),
        easing: styles.getPropertyValue('--ease-out').trim() || 'ease-out',
      },
    )
    return () => animation.cancel()
  }, [pathname])

  return ref
}

/** A `--duration-*` token in milliseconds: `500ms` or `0.5s`, else `fallback`. */
export function milliseconds(token: string, fallback: number): number {
  const match = /^\s*([\d.]+)(ms|s)\s*$/.exec(token)
  if (!match) return fallback
  return Number(match[1]) * (match[2] === 's' ? 1000 : 1)
}
