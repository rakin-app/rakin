/// <reference types="node" />
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DEFAULT_THEME, THEMES, type Theme } from '../theme'

// Vitest does not load CSS, so the tests read the files as text, from `frontend/src`.
const src = join(process.cwd(), 'src')
const read = (path: string) => readFileSync(join(src, path), 'utf8')

describe('tokens', () => {
  const css = read('styles/tokens.css')
  const token = (name: string) => new RegExp(`--${name}:\\s*([^;]+);`).exec(css)?.[1]?.trim()

  it('sizes every text field at 16px, so iOS does not zoom on focus', () => {
    expect(token('text-input')).toBe('16px')
    expect(read('components/Field.css')).toMatch(/font-size: var\(--text-input\)/)
  })

  it('keeps two control heights, 44 and 52', () => {
    expect(token('control-height')).toBe('44px')
    expect(token('control-height-lg')).toBe('52px')
    expect(token('control-height-sm')).toBeUndefined()
    expect(token('control-height-xl')).toBeUndefined()
  })

  // WCAG 2.1 relative luminance.
  const luminance = (hex: string) => {
    const lin = (i: number) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * lin(1) + 0.7152 * lin(3) + 0.0722 * lin(5)
  }
  const contrast = (a: string, b: string) => {
    const [x, y] = [luminance(a), luminance(b)]
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
  }

  /** A theme's colours (#199): `:root`'s, then the theme's own block over them. */
  const colours = (theme: Theme) => {
    const found: Record<string, string> = {}
    for (const [, selector, body] of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selectors = selector!.split(',').map((one) => one.trim())
      if (!selectors.includes(':root') && !selectors.includes(`[data-theme='${theme}']`)) continue
      for (const [, name, value] of body!.matchAll(/--color-([\w-]+):\s*([^;]+);/g)) found[name!] = value!.trim()
    }
    return found
  }

  /** The colours `--gradient-hero` runs between, in a theme. */
  const gradient = (theme: Theme) => {
    const blocks = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    const own = blocks.find(([, selector]) => selector!.split(',').some((one) => one.trim() === `[data-theme='${theme}']`))
    return [...(/--gradient-hero:([^;]+);/.exec(own![2]!)?.[1] ?? '').matchAll(/#[0-9a-f]{6}/g)].map(([hex]) => hex)
  }

  // Text at 4.5:1 (WCAG 1.4.3); a control's edge and the focus ring at 3:1 (1.4.11).
  const pairs: [string, string, number][] = [
    ['text', 'bg', 4.5],
    ['text', 'surface', 4.5],
    ['text', 'surface-sunken', 4.5],
    ['heading', 'bg', 4.5],
    ['heading', 'surface', 4.5],
    ['text-muted', 'bg', 4.5],
    ['text-muted', 'surface', 4.5],
    ['text-muted', 'surface-sunken', 4.5],
    ['text-subtle', 'bg', 4.5],
    ['text-subtle', 'surface', 4.5],
    ['accent', 'bg', 4.5],
    ['accent', 'surface', 4.5],
    ['accent', 'accent-soft', 4.5],
    ['inverse-text', 'inverse', 4.5],
    ['inverse-text', 'inverse-raised', 4.5],
    ['inverse-text-muted', 'inverse', 4.5],
    ['accent-inverse-text', 'accent-inverse', 4.5],
    ['moss-text', 'moss', 4.5],
    ['moss-text', 'moss-hover', 4.5],
    ['sidebar-text', 'sidebar', 4.5],
    ['sidebar-text', 'sidebar-raised', 4.5],
    ['sidebar-active-text', 'sidebar-active', 4.5],
    ['success', 'surface', 4.5],
    ['success-strong', 'success-soft', 4.5],
    ['success-strong', 'success-pill', 4.5],
    ['warning', 'bg', 4.5],
    ['warning', 'surface', 4.5],
    ['warning-strong', 'warning-soft', 4.5],
    ['danger', 'bg', 4.5],
    ['danger', 'surface', 4.5],
    ['danger', 'danger-soft', 4.5],
    ['timer-fight-text', 'timer-fight', 4.5],
    ['timer-rest-text', 'timer-rest', 4.5],
    ['danger-soft', 'timer-fight', 4.5],
    ['danger-soft', 'timer-rest', 4.5],
    ['border-input', 'bg', 3],
    ['border-input', 'surface', 3],
    ['border-input', 'surface-sunken', 3],
    ['focus', 'bg', 3],
    ['focus', 'surface', 3],
    ['text-subtle', 'surface-sunken', 4.5],
    // The ring on every dark surface (#361): a dark button, the sidebar and the phone's
    // bar, the hero card (its gradient's two ends, below).
    ['focus-on-inverse', 'inverse', 3],
    ['focus-on-inverse', 'inverse-raised', 3],
    ['focus-on-inverse', 'sidebar', 3],
    ['focus-on-inverse', 'sidebar-raised', 3],
  ]

  describe.each(THEMES)('in the %s theme', (theme) => {
    const color = colours(theme)

    it.each(pairs)('--color-%s on --color-%s is %s:1 or more', (fg, bg, min) => {
      expect(contrast(color[fg]!, color[bg]!)).toBeGreaterThanOrEqual(min)
    })

    it('draws the focus ring at 3:1 or more on both ends of the hero gradient', () => {
      const hero = gradient(theme)
      expect(hero).toHaveLength(2)
      hero.forEach((stop) => expect(contrast(color['focus-on-inverse']!, stop)).toBeGreaterThanOrEqual(3))
    })

    it('writes every colour the default does', () => {
      expect(Object.keys(color).sort()).toEqual(Object.keys(colours(DEFAULT_THEME)).sort())
    })
  })

  // A round reads the same in every gym (#187), and "Pagado" never looks like "Vencido".
  it.each(['timer-fight', 'timer-rest', 'success'])('keeps --color-%s in every theme', (name) => {
    expect(new Set(THEMES.map((theme) => colours(theme)[name])).size).toBe(1)
  })
})

/**
 * The design system holds (#361): a card, a section's title and a page's title are
 * drawn by their components alone, and stacking, the touch target and the round pill
 * are tokens. Each stylesheet under src is read as text, its comments dropped.
 */
describe('stylesheets', () => {
  const sheets = (readdirSync(src, { recursive: true }) as string[])
    .filter((path) => path.endsWith('.css'))
    .map((path) => ({ path, css: read(path).replace(/\/\*[\s\S]*?\*\//g, '') }))

  /** Every rule's selector and declarations, `@media` blocks' included. */
  const rules = sheets.flatMap(({ path, css }) =>
    [...css.matchAll(/([^{};]+)\{([^{}]*)\}/g)].map(([, selector, body]) => ({ path, selector: selector!.trim(), body: body! })),
  )
  const declaring = (...declarations: string[]) =>
    rules.filter(({ body }) => declarations.every((one) => body.includes(one))).map(({ path, selector }) => `${path} ${selector}`)
  // A figure set in the display face ("Clases este mes 12") is not a title.
  const titles = (found: string[]) => found.filter((rule) => /title|legend|heading/.test(rule))

  it('reads the stylesheets', () => {
    expect(sheets.length).toBeGreaterThan(30)
  })

  it('draws a card only in Card.css', () => {
    const shells = declaring('background: var(--color-surface)', 'border-radius: var(--radius-xl)')
    expect(shells).toEqual(['components/Card.css .card'])
  })

  it("draws a section's title only in Card.css", () => {
    const found = declaring('color: var(--color-heading)', 'font-family: var(--font-display)', 'font-size: var(--text-lg)')
    expect(titles(found)).toEqual(['components/Card.css .section-header__title'])
  })

  it("draws a page's title only in PageHeader.css", () => {
    const found = declaring('color: var(--color-heading)', 'font-family: var(--font-display)', 'font-size: var(--text-3xl)')
    expect(titles(found)).toEqual(['components/PageHeader.css .page-title'])
  })

  it.each([
    ['a z-index', /z-index:\s*-?\d/],
    ['a 44px', /\b44px\b/],
    ['a 999px radius', /border-radius:\s*999px/],
  ])('writes %s only in tokens.css', (_, literal) => {
    const found = sheets.filter(({ path, css }) => !path.endsWith('tokens.css') && literal.test(css)).map(({ path }) => path)
    expect(found).toEqual([])
  })
})
