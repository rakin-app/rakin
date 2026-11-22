import { useEffect, useState } from 'react'
import { Button, type ButtonVariant } from '../components/Button'

/** How long a step's buttons wait before they take a tap (#550). A double tap is two
 * taps 100–300 ms apart, and the second lands on whatever button is under the finger by
 * then: "Sí, …" where the first step's submit was, "Cancelar" where "Volver" was. */
export const STEP_SETTLE_MS = 500

/** Whether a money correction is on its second step (#550): every one that changes what is
 * owed or paid asks "Sí, …" before it is saved. */
export type ConfirmStep = { confirming: boolean; ask: () => void; back: () => void }

export function useConfirmStep(): ConfirmStep {
  const [confirming, setConfirming] = useState(false)
  return {
    confirming,
    ask: () => {
      // A field keeps submitting its form on Enter, read-only or not: out of it, a second
      // Enter (a phone keyboard's Go pressed twice) cannot pass "Sí, …" unseen.
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
      setConfirming(true)
    },
    back: () => setConfirming(false),
  }
}

/** Whether `step` changed less than `STEP_SETTLE_MS` ago; never on the first render. */
function useSettling(step: boolean): boolean {
  const [settled, setSettled] = useState(step)
  useEffect(() => {
    if (settled === step) return
    const timer = setTimeout(() => setSettled(step), STEP_SETTLE_MS)
    return () => clearTimeout(timer)
  }, [step, settled])
  return settled !== step
}

/**
 * A money correction's buttons, on either step (#550). First "Cancelar" and the action;
 * then "Volver", which returns to the form as it was, and "Sí, …", the only one that
 * saves. Each time the step changes, both of the new step's buttons stay disabled for
 * `STEP_SETTLE_MS`, so the second tap of a double tap on the action cannot confirm it,
 * nor one on "Volver" cancel the form. A double tap on "Sí, …" itself is sent once by
 * `useSubmit`, and a double Enter in a field stops at "Sí, …": `ask` takes the focus out.
 */
export function FixActions({
  step,
  pending,
  words,
  submit,
  confirm,
  variant = 'primary',
  disabled = false,
  onCancel,
}: {
  step: ConfirmStep
  pending: boolean
  words: { cancel: string; back: string; working: string }
  // The first step's label, and the second's ("Sí, anular $30.000").
  submit: string
  confirm: string
  variant?: ButtonVariant
  // The first step's submit, held back (a quote still loading, say).
  disabled?: boolean
  onCancel: () => void
}) {
  const { confirming } = step
  const settling = useSettling(confirming)
  const held = pending || settling
  return (
    <div className="member__form-actions">
      {confirming ? (
        <Button key="back" disabled={held} onClick={step.back}>
          {words.back}
        </Button>
      ) : (
        <Button key="cancel" disabled={held} onClick={onCancel}>
          {words.cancel}
        </Button>
      )}
      {confirming ? (
        <Button key="confirm" type="submit" variant={variant} disabled={held} busy={pending}>
          {pending ? words.working : confirm}
        </Button>
      ) : (
        <Button key="submit" type="submit" variant={variant} disabled={held || disabled} busy={pending}>
          {submit}
        </Button>
      )}
    </div>
  )
}
