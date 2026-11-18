import { useEffect, useRef, useState } from 'react'
import './EdgeFade.css'

/** Which ends of a sideways scroller have more past them. */
type Overflow = { start: boolean; end: boolean }

/**
 * A sideways scroller whose edges fade where more lies past them (#358), so a row never
 * seems to end at its last visible item. Spread `attrs` on the element `ref` holds, and
 * give it the `edge-fade` class.
 */
export function useEdgeFade<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [overflow, setOverflow] = useState<Overflow>({ start: false, end: false })

  useEffect(() => {
    const row = ref.current
    if (!row) return
    const measure = () => {
      // A pixel of slack: zoom and rounding leave fractions at the very end.
      const start = row.scrollLeft > 1
      const end = row.scrollLeft + row.clientWidth < row.scrollWidth - 1
      setOverflow((was) => (was.start === start && was.end === end ? was : { start, end }))
    }
    measure()
    row.addEventListener('scroll', measure, { passive: true })
    // Not in every test environment; a resize is then simply not followed.
    const resized = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    resized?.observe(row)
    return () => {
      row.removeEventListener('scroll', measure)
      resized?.disconnect()
    }
  }, [])

  const attrs = { 'data-more-start': overflow.start || undefined, 'data-more-end': overflow.end || undefined }
  return { ref, attrs }
}
