import './PageHeader.css'

type Props = {
  title: string
  eyebrow?: string
}

export function PageHeader({ title, eyebrow }: Props) {
  return (
    <header className="page-header">
      {eyebrow && <span className="page-header__eyebrow">{eyebrow}</span>}
      <h1 className="page-header__title">{title}</h1>
    </header>
  )
}
