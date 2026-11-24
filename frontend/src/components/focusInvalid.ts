import { useEffect, useRef, useState, type RefObject } from 'react'

/**
 * After a failed submit, focus the form's first invalid control (#362), so a screen
 * reader reads its error and a phone scrolls to it. `signal` changes once per failure:
 * a count of refused attempts, or the mutation's error; a falsy one does nothing.
 */
export function useFocusFirstInvalid(form: RefObject<HTMLElement | null>, signal: unknown) {
  useEffect(() => {
    if (!signal) return
    form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, [form, signal])
}

/**
 * A form's own check, refused (#569): pass the form's ref, and call what it returns on
 * every attempt the form turns down, so each one focuses its first invalid control.
 */
export function useRefusal(form: RefObject<HTMLElement | null>): () => void {
  const [refused, setRefused] = useState(0)
  useFocusFirstInvalid(form, refused)
  return () => setRefused((count) => count + 1)
}

const FIELD = 'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])'

/**
 * A panel or inline form that has just opened (#569): focus its first field, else its
 * first button or link (a choice of fixes), else the panel itself, and bring it into
 * view (`block`: as little as it takes, by default), so a reader on a phone lands in it
 * rather than where the button was. Once, when it mounts.
 */
export function useFocusOnOpen<T extends HTMLElement = HTMLElement>(block: ScrollLogicalPosition = 'nearest') {
  const ref = useRef<T>(null)
  useEffect(() => {
    const panel = ref.current
    if (!panel) return
    const field =
      panel.querySelector<HTMLElement>(FIELD) ?? panel.querySelector<HTMLElement>('button:not([disabled]), a[href]')
    const target = field ?? panel
    if (!field && !panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1')
    target.focus({ preventScroll: true })
    panel.scrollIntoView?.({ block })
    // Once, on opening: not again as its fields change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return ref
}
