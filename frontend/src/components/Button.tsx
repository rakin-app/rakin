import type { ComponentProps } from 'react'
import { cx } from './classNames'
import './Button.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export type ButtonStyle = {
  /** One `primary` per screen; `danger` for whatever deletes, removes or refuses. */
  variant?: ButtonVariant
  /** `md` is the 44px touch target; `lg` (52px) the screen's main action on a phone. */
  size?: 'md' | 'lg'
  fullWidth?: boolean
  /** A square button that holds only an icon: it needs an `aria-label`. */
  icon?: boolean
  /** On a dark surface (the timer, the student's "Próximo pago" card). */
  inverse?: boolean
  className?: string
}

/**
 * The class a control gets to look like a button: for a `Link`, an `a` or the `label`
 * of a hidden file input, which cannot be a `Button` themselves.
 */
export function buttonClass({
  variant = 'secondary',
  size = 'md',
  fullWidth,
  icon,
  inverse,
  className,
}: ButtonStyle = {}): string {
  return cx(
    'button',
    `button--${variant}`,
    size === 'lg' && 'button--lg',
    fullWidth && 'button--full',
    icon && 'button--icon',
    inverse && 'button--inverse',
    className,
  )
}

type Props = ButtonStyle &
  Omit<ComponentProps<'button'>, 'className'> & {
    /** Its request is on its way: disabled, and `aria-busy`, until it answers (#201). */
    busy?: boolean
  }

/** The one button. `type` defaults to `button`: a submit says so. */
export function Button({
  variant,
  size,
  fullWidth,
  icon,
  inverse,
  className,
  type = 'button',
  busy = false,
  disabled,
  ...rest
}: Props) {
  return (
    <button
      type={type}
      className={buttonClass({ variant, size, fullWidth, icon, inverse, className })}
      disabled={busy || disabled}
      aria-busy={busy || undefined}
      {...rest}
    />
  )
}
