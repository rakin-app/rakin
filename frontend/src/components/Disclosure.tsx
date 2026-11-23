import type { DetailsHTMLAttributes, ReactNode } from 'react'
import { cardClass } from './Card'
import { cx } from './classNames'
import { ChevronDownIcon } from './icons'
import './Disclosure.css'

type Props = Omit<DetailsHTMLAttributes<HTMLDetailsElement>, 'title'> & {
  /** What it holds, on the row that opens it. */
  title: ReactNode
  /** A muted line beside the title: a version, a count. */
  meta?: ReactNode
  /** A word beside the chevron while it is closed, where opening it is the point ("Leer"). */
  cue?: string
}

/**
 * A card that opens under its title (#570): a `<details>`, so it opens with no script,
 * whose whole title row is the target, with a chevron that turns as it opens. Closed, it
 * is that row and nothing else. Its children are the card's body.
 */
export function Disclosure({ title, meta, cue, className, children, ...rest }: Props) {
  return (
    <details className={cardClass({}, cx('disclosure', className))} {...rest}>
      <summary className="disclosure__summary">
        <span className="disclosure__head">
          <span className="disclosure__title">{title}</span>
          {meta && <span className="disclosure__meta">{meta}</span>}
        </span>
        {cue && <span className="disclosure__cue">{cue}</span>}
        <span className="disclosure__chevron">
          <ChevronDownIcon />
        </span>
      </summary>
      <div className="disclosure__body">{children}</div>
    </details>
  )
}
