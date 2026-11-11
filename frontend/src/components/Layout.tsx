import { useSyncExternalStore, type ComponentProps } from 'react'
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

// Where `Grid` goes to columns: Layout.css's breakpoint.
const WIDE = '(min-width: 1024px)'

function wideQuery(): MediaQueryList | null {
  return typeof window.matchMedia === 'function' ? window.matchMedia(WIDE) : null
}

function subscribeWide(onChange: () => void): () => void {
  const query = wideQuery()
  query?.addEventListener('change', onChange)
  return () => query?.removeEventListener('change', onChange)
}

/**
 * Whether the window is as wide as `Grid`'s columns, for what a screen shows only on a
 * desktop and should not fetch on a phone. False where the browser cannot say.
 */
export function useWide(): boolean {
  return useSyncExternalStore(subscribeWide, () => wideQuery()?.matches ?? false)
}
