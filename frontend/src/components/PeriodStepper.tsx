import type { ReactNode } from 'react'
import { Button } from './Button'
import { cx } from './classNames'
import { ChevronLeftIcon, ChevronRightIcon } from './icons'
import './PeriodStepper.css'

/**
 * ‹ Noviembre 2026 ›: the one way to walk a month, a day, a week or a year back and on
 * (#567). Pagos, Finanzas, Gastos, Resumen del mes, Clases and "Horas por etiqueta" all
 * step with it, so an owner who moves between them changes month the same way. Each arrow
 * is a 44px target named by `previous` and `next`; the period between them is a live
 * region, read out as it changes. `children` is what is shown, text or a heading. An
 * absent `onPrevious` or `onNext` disables its arrow.
 */
export function PeriodStepper({
  label,
  previous,
  next,
  onPrevious,
  onNext,
  className,
  children,
}: {
  label: string
  previous: string
  next: string
  onPrevious?: () => void
  onNext?: () => void
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cx('period-stepper', className)} role="group" aria-label={label}>
      <Button icon variant="ghost" aria-label={previous} disabled={!onPrevious} onClick={onPrevious}>
        <ChevronLeftIcon />
      </Button>
      <div className="period-stepper__shown" aria-live="polite">
        {children}
      </div>
      <Button icon variant="ghost" aria-label={next} disabled={!onNext} onClick={onNext}>
        <ChevronRightIcon />
      </Button>
    </div>
  )
}

/**
 * The months before and after `month` in `months`, newest first as the API lists them
 * (Pagos' book, Resumen del mes): `older` is the one before, `newer` the one after. Either
 * is undefined at the list's end, or while `month` is not in it.
 */
export function monthNeighbours(
  months: readonly string[],
  month: string | undefined,
): { older: string | undefined; newer: string | undefined } {
  const at = month === undefined ? -1 : months.indexOf(month)
  if (at < 0) return { older: undefined, newer: undefined }
  return { older: months[at + 1], newer: at > 0 ? months[at - 1] : undefined }
}
