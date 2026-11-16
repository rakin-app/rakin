import type { HTMLAttributes, LabelHTMLAttributes, ReactNode } from 'react'
import { cx } from './classNames'
import './Card.css'

/**
 * The class of a card: a white panel on the page's grey, its edge, radius and shadow
 * in one place. `flush` drops the padding and clips the corners, for a list or a table
 * whose rows run to the edge. For a card that is a link or a form; elsewhere `Card`.
 */
export function cardClass({ flush = false }: { flush?: boolean } = {}, className?: string): string {
  return cx('card', flush && 'card--flush', className)
}

type CardTag = 'section' | 'div' | 'article' | 'ul' | 'ol' | 'dl' | 'li' | 'p'

/** A white panel on the page's grey; `as` another element when it is a list or a row. */
export function Card({
  as: Tag = 'section',
  flush = false,
  className,
  ...rest
}: HTMLAttributes<HTMLElement> & { as?: CardTag; flush?: boolean }) {
  return <Tag className={cardClass({ flush }, className)} {...rest} />
}

export type BannerTone = 'error' | 'done' | 'warning' | 'info'

/**
 * A message in a tinted box: a failure (`error`), something saved or sent (`done`),
 * something to know before going on (`warning`), or a neutral note (`info`). An error
 * is announced at once (`alert`), the others politely (`status`); `role={null}` for one
 * that is always on screen. A `div` when it holds more than a line, a paragraph or a
 * button among them.
 */
export function Banner({
  tone,
  as: Tag = 'p',
  role,
  className,
  ...rest
}: Omit<HTMLAttributes<HTMLElement>, 'role'> & {
  tone: BannerTone
  as?: 'p' | 'div'
  role?: 'alert' | 'status' | null
}) {
  const announced = role === undefined ? (tone === 'error' ? 'alert' : 'status') : (role ?? undefined)
  return (
    <Tag
      className={cx('banner', `banner--${tone}`, Tag === 'div' && 'banner--stack', className)}
      role={announced}
      {...rest}
    />
  )
}

/** A list with no bullets, indent or margin: its rows carry their own look. */
export function PlainList({ ordered = false, className, ...rest }: HTMLAttributes<HTMLElement> & { ordered?: boolean }) {
  const Tag = ordered ? 'ol' : 'ul'
  return <Tag className={cx('plain-list', className)} {...rest} />
}

/**
 * A checkbox or radio and its words, the whole row the target and 44px tall at least.
 * `start` for words that run to more than a line: the box stays by the first.
 */
export function CheckRow({
  start = false,
  className,
  ...rest
}: LabelHTMLAttributes<HTMLLabelElement> & { start?: boolean }) {
  return <label className={cx('check-row', start && 'check-row--start', className)} {...rest} />
}

/**
 * A section's title, alone: in `SectionHeader`, or where the title sits in a head of its
 * own (Hoy's sections, beside their count) or must be a fieldset's `legend`.
 */
export function SectionTitle({
  as: Tag = 'h2',
  className,
  ...rest
}: HTMLAttributes<HTMLElement> & { as?: 'h2' | 'h3' | 'legend' | 'span' | 'summary' }) {
  return <Tag className={cx('section-header__title', className)} {...rest} />
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
      <SectionTitle as={Heading} id={id}>
        {title}
      </SectionTitle>
      {trailing !== undefined && <span className="section-header__trailing">{trailing}</span>}
    </div>
  )
}

/** A section of a page: its `SectionHeader` over what it holds, the title outside the
 * card (#360). Labelled by its title. */
export function Section({
  title,
  trailing,
  id,
  className,
  children,
}: {
  title: ReactNode
  trailing?: ReactNode
  id: string
  className?: string
  children: ReactNode
}) {
  return (
    <section className={cx('section', className)} aria-labelledby={id}>
      <SectionHeader id={id} title={title} trailing={trailing} />
      {children}
    </section>
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
  return cx('list-row', tappable && 'list-row--tappable', className)
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
