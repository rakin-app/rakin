import { useEffect, useRef, type ReactNode } from 'react'
import { buttonClass, type ButtonVariant } from './Button'
import { cx } from './classNames'
import { ChevronDownIcon } from './icons'
import './MoreMenu.css'

/**
 * "Más": the actions a screen keeps out of its main row (#357), a button that opens a
 * short list under it. A `<details>`, so it opens with no script; a tap outside it, Esc,
 * or choosing one of its actions closes it again. Its children are links and buttons,
 * each given `moreItemClass`.
 */
export function MoreMenu({
  label,
  ariaLabel,
  children,
  variant = 'ghost',
  className,
}: {
  /** The button's text, `Más`. */
  label: string
  /** Its accessible name when a screen has several, `Más acciones para Diego`. */
  ariaLabel?: string
  children: ReactNode
  variant?: ButtonVariant
  className?: string
}) {
  const ref = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const menu = ref.current
    if (!menu) return
    const close = () => {
      menu.open = false
    }
    const outside = (event: PointerEvent) => {
      if (menu.open && !menu.contains(event.target as Node)) close()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || !menu.open) return
      close()
      menu.querySelector('summary')?.focus()
    }
    document.addEventListener('pointerdown', outside)
    menu.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      menu.removeEventListener('keydown', escape)
    }
  }, [])
  return (
    <details ref={ref} className={cx('more-menu', className)}>
      <summary className={buttonClass({ variant, className: 'more-menu__button' })} aria-label={ariaLabel}>
        {label}
        <ChevronDownIcon />
      </summary>
      <div
        className="more-menu__list"
        onClick={(event) => {
          if ((event.target as Element).closest('a, button') && ref.current) ref.current.open = false
        }}
      >
        {children}
      </div>
    </details>
  )
}

/** A link or button inside a `MoreMenu`: a full-width row. */
export const moreItemClass = (danger = false) => cx('more-menu__item', danger && 'more-menu__item--danger')
