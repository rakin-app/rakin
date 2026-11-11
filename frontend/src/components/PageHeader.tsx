import type { ReactNode } from 'react'
import './PageHeader.css'

type Props = {
  title: string
  /** Text, or the logo where a page opens with it (sign-in). */
  eyebrow?: ReactNode
  /** The gym's mark beside the eyebrow and title (`GymMark`, #223). */
  mark?: ReactNode
}

export function PageHeader({ title, eyebrow, mark }: Props) {
  const text = (
    <>
      {eyebrow && <span className="page-header__eyebrow">{eyebrow}</span>}
      <h1 className="page-header__title">{title}</h1>
    </>
  )
  return (
    <header className={mark ? 'page-header page-header--marked' : 'page-header'}>
      {mark ? (
        <>
          {mark}
          <div className="page-header__text">{text}</div>
        </>
      ) : (
        text
      )}
    </header>
  )
}
