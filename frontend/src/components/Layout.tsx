import { useCallback, useSyncExternalStore, type ComponentProps } from 'react'
import { cx } from './classNames'
import './Layout.css'

/**
 * A screen's header and body: as wide as the window up to `--content-wide`, centred,
 * with the side padding of the breakpoint it is on. A `PageHeader` inside it lines up
 * with the body.
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
// Where the shell's bottom bar becomes the sidebar: AdminLayout.css's breakpoint.
const DESKTOP = '(min-width: 960px)'

function mediaQuery(query: string): MediaQueryList | null {
  return typeof window.matchMedia === 'function' ? window.matchMedia(query) : null
}

/** Whether the window matches `query`, kept current as it is resized. False where the browser cannot say. */
function useMedia(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = mediaQuery(query)
      list?.addEventListener('change', onChange)
      return () => list?.removeEventListener('change', onChange)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => mediaQuery(query)?.matches ?? false)
}

/**
 * Whether the window is as wide as `Grid`'s columns, for what a screen shows only on a
 * desktop and should not fetch on a phone. False where the browser cannot say.
 */
export function useWide(): boolean {
  return useMedia(WIDE)
}

/** Whether the shell is the desktop one, with the sidebar (960px and up). False where the browser cannot say. */
export function useDesktop(): boolean {
  return useMedia(DESKTOP)
}
