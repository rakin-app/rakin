import type { HTMLAttributes, ReactNode, Ref } from 'react'
import { cx } from './classNames'
import './PageHeader.css'

type Props = {
  title: string
  /** Text, or the logo where a page opens with it (sign-in). */
  eyebrow?: ReactNode
  /** The gym's mark beside the eyebrow and title (`GymMark`, #223). */
  mark?: ReactNode
  /** The screen's `BackLink`, at the left of the title (#360). */
  back?: ReactNode
}

export function PageHeader({ title, eyebrow, mark, back }: Props) {
  const text = (
    <>
      {eyebrow && <span className="page-header__eyebrow">{eyebrow}</span>}
      <PageTitle>{title}</PageTitle>
    </>
  )
  const lead = back ?? mark
  return (
    <header className={lead ? 'page-header page-header--marked' : 'page-header'}>
      {lead ? (
        <>
          {back}
          {mark}
          <div className="page-header__text">{text}</div>
        </>
      ) : (
        text
      )}
    </header>
  )
}

/**
 * A screen's title at its size: in `PageHeader`, or in a header of the screen's own (a
 * ficha's, beside its back link and actions). `tight` for one that may wrap to two lines
 * beside a back link. `as="span"` for a name shown at that size that is not the page's
 * heading, as Clases shows a picked class.
 */
export function PageTitle({
  as = 'h1',
  tight = false,
  className,
  ref,
  ...rest
}: HTMLAttributes<HTMLHeadingElement> & { as?: 'h1' | 'span'; tight?: boolean; ref?: Ref<HTMLHeadingElement> }) {
  const names = cx('page-title', tight && 'page-title--tight', className)
  return as === 'span' ? <span className={names} {...rest} /> : <h1 ref={ref} className={names} {...rest} />
}
