import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { applyTheme } from './theme'

describe('applyTheme', () => {
  beforeEach(() => {
    document.head.innerHTML = `
      <meta name="theme-color" content="#0f2e1b" />
      <style>
        [data-theme='bosque'] { --color-sidebar: #0f2e1b; }
        [data-theme='volcan'] { --color-sidebar: #3b1c1d; }
      </style>`
  })
  afterEach(() => {
    document.head.innerHTML = ''
    delete document.documentElement.dataset.theme
    localStorage.clear()
  })

  const themeColor = () => document.querySelector('meta[name="theme-color"]')?.getAttribute('content')

  it("gives the browser's bar the colour of the theme's top bar", () => {
    applyTheme('volcan')
    expect(document.documentElement.dataset.theme).toBe('volcan')
    expect(themeColor()).toBe('#3b1c1d')

    applyTheme('bosque')
    expect(themeColor()).toBe('#0f2e1b')
  })
})
