import { useState } from 'react'
import { Button, type ButtonVariant } from '../components/Button'

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

/**
 * A money correction's buttons, on either step (#550). First "Cancelar" and the action;
 * then "Volver", which returns to the form as it was, and "Sí, …", the only one that
 * saves. The two submits are separate buttons (`key`), so the second tap of a double tap
 * on the first lands on the one that is gone, not on "Sí, …", and on "Volver" not on
 * "Cancelar"; a double tap on "Sí, …" is sent once by `useSubmit`. A double Enter in a
 * field stops there too: `ask` takes the focus out of it.
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
  return (
    <div className="member__form-actions">
      {confirming ? (
        <Button key="back" disabled={pending} onClick={step.back}>
          {words.back}
        </Button>
      ) : (
        <Button key="cancel" disabled={pending} onClick={onCancel}>
          {words.cancel}
        </Button>
      )}
      {confirming ? (
        <Button key="confirm" type="submit" variant={variant} disabled={pending} busy={pending}>
          {pending ? words.working : confirm}
        </Button>
      ) : (
        <Button key="submit" type="submit" variant={variant} disabled={pending || disabled} busy={pending}>
          {submit}
        </Button>
      )}
    </div>
  )
}
