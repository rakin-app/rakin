import type { ComponentProps } from 'react'
import { cx } from './classNames'
import './Layout.css'

/**
 * A screen's body under its `PageHeader`: as wide as the window up to `--content-wide`,
 * centred, with the side padding of the breakpoint it is on.
 */
export function PageContainer({ className, ...rest }: ComponentProps<'div'>) {
  return <div className={cx('page-container', className)} {...rest} />
}

/** One column on a phone and a tablet; from 1024px, `columns` of them (2 unless told 3). */
export function Grid({ columns = 2, className, ...rest }: { columns?: 2 | 3 } & ComponentProps<'div'>) {
  return <div className={cx('grid', `grid--${columns}`, className)} {...rest} />
}
