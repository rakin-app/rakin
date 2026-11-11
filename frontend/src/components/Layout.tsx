import { useCallback, useSyncExternalStore, type ComponentProps } from 'react'
import breakpoints from '../styles/media.css?raw'
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

/** A breakpoint's query as `styles/media.css` defines it, the one source the stylesheets use too. */
function customMedia(name: string): string {
  const query = new RegExp(`@custom-media\\s+--${name}\\s+([^;]+);`).exec(breakpoints)?.[1]
  if (!query) throw new Error(`styles/media.css defines no --${name}`)
  return query.trim()
}

// Where `Grid` goes to columns.
const WIDE = customMedia('wide')
// Where the shell's bottom bar becomes the sidebar.
const DESKTOP = customMedia('desktop')

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
