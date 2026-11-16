import type { ReactNode } from 'react'
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
      <h1 className="page-header__title">{title}</h1>
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
