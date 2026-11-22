import { useEffect, useRef, type ReactNode } from 'react'
import { buttonClass, type ButtonVariant } from './Button'
import { cx } from './classNames'
import { ChevronDownIcon } from './icons'
import './MoreMenu.css'

/**
 * "Más": the actions a screen keeps out of its main row (#357), a button that opens a
 * short list under it. A `<details>`, so it opens with no script; a tap outside it, Esc,
 * focus leaving it, or choosing one of its actions closes it again. Its children are links and buttons,
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
    // Whether the last press landed inside the menu. WebKit (iPhone Safari, the installed app) does
    // not focus a link or button that is tapped: the summary blurs with no relatedTarget, before
    // the click. Closing then hid the list under the finger and the tap did nothing (#529).
    let pressedInside = false
    const close = () => {
      menu.open = false
      pressedInside = false
    }
    const press = (event: PointerEvent) => {
      pressedInside = menu.contains(event.target as Node)
      if (menu.open && !pressedInside) close()
    }
    const key = (event: KeyboardEvent) => {
      pressedInside = false
      if (event.key !== 'Escape' || !menu.open) return
      close()
      menu.querySelector('summary')?.focus()
    }
    // Tab out of it, and it closes behind the focus rather than over the next row. A blur that a
    // press inside it caused, with nowhere for the focus to go, is a tap on it: that one stays.
    const leave = (event: FocusEvent) => {
      const next = event.relatedTarget as Node | null
      if (!menu.open || menu.contains(next) || (next === null && pressedInside)) return
      close()
    }
    document.addEventListener('pointerdown', press)
    menu.addEventListener('keydown', key)
    menu.addEventListener('focusout', leave)
    return () => {
      document.removeEventListener('pointerdown', press)
      menu.removeEventListener('keydown', key)
      menu.removeEventListener('focusout', leave)
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
