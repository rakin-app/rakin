import type { ReactNode } from 'react'
import './PageHeader.css'

type Props = {
  title: string
  /** Text, or the logo where a page opens with it (sign-in). */
  eyebrow?: ReactNode
}

export function PageHeader({ title, eyebrow }: Props) {
  return (
    <header className="page-header">
      {eyebrow && <span className="page-header__eyebrow">{eyebrow}</span>}
      <h1 className="page-header__title">{title}</h1>
    </header>
  )
}
