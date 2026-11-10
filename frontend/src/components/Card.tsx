import type { ComponentProps, ReactNode } from 'react'
import './Card.css'

const join = (...names: (string | false | undefined)[]) => names.filter(Boolean).join(' ')

/** A white panel on the page's grey. */
export function Card({ className, ...rest }: ComponentProps<'section'>) {
  return <section className={join('card', className)} {...rest} />
}

/** A section's eyebrow on the left and its count or total on the right. */
export function SectionHeader({
  title,
  trailing,
  id,
  as: Heading = 'h2',
}: {
  title: ReactNode
  trailing?: ReactNode
  id?: string
  as?: 'h2' | 'h3'
}) {
  return (
    <div className="section-header">
      <Heading id={id} className="section-header__title">
        {title}
      </Heading>
      {trailing !== undefined && <span className="section-header__trailing">{trailing}</span>}
    </div>
  )
}

/**
 * The inside of a list row: its title, the detail under it, and what sits at its end.
 * Put it in a `Link` or `button` with `listRowClass(true)` and the whole row is the target.
 */
export function ListRowContent({ title, detail, trailing }: { title: ReactNode; detail?: ReactNode; trailing?: ReactNode }) {
  return (
    <>
      <span className="list-row__text">
        <span className="list-row__title">{title}</span>
        {detail && <span className="list-row__detail">{detail}</span>}
      </span>
      {trailing && <span className="list-row__trailing">{trailing}</span>}
    </>
  )
}

/** The class of a row; `tappable` when the row itself is a link or a button. */
export function listRowClass(tappable = false, className?: string): string {
  return join('list-row', tappable && 'list-row--tappable', className)
}

/** A row that is not a target itself, though its trailing slot may hold one. */
export function ListRow({
  title,
  detail,
  trailing,
  className,
}: {
  title: ReactNode
  detail?: ReactNode
  trailing?: ReactNode
  className?: string
}) {
  return (
    <div className={listRowClass(false, className)}>
      <ListRowContent title={title} detail={detail} trailing={trailing} />
    </div>
  )
}

/** What a list says when it has nothing: one sentence, and what to do about it. */
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <p className="empty-state__text">{children}</p>
      {action}
    </div>
  )
}
