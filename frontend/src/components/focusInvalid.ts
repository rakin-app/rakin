import { useEffect, type RefObject } from 'react'

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
