/**
 * The gym's theme (#199): the colours every screen wears, chosen per gym in Ajustes ›
 * Gimnasio. `styles/tokens.css` has a block of colours for each, keyed by `data-theme`
 * on <html>; components never know which one they are in.
 *
 * The theme comes from the gym: `/api/me/role` once someone is signed in, and
 * `/api/host` before, on the gym's own address. The last one worn is kept in storage
 * so the next visit opens in it, instead of flashing the default first.
 */

export const THEMES = ['bosque', 'oceano', 'volcan'] as const

export type Theme = (typeof THEMES)[number]

export const DEFAULT_THEME: Theme = 'bosque'

const STORAGE_KEY = 'rakin.theme'

export function isTheme(value: unknown): value is Theme {
  return typeof value === 'string' && (THEMES as readonly string[]).includes(value)
}

/** The theme the last visit wore, or the default. */
export function storedTheme(): Theme {
  try {
    const kept = localStorage.getItem(STORAGE_KEY)
    return isTheme(kept) ? kept : DEFAULT_THEME
  } catch {
    // Storage can be refused (a private window); the default it is.
    return DEFAULT_THEME
  }
}

/** Wears `theme` now, and remembers it for the next visit. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Not remembered: the next visit opens in the default until the gym answers.
  }
}
