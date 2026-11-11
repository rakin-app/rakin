import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setTabIcon } from './tabIcon'

const icons = () =>
  [...document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]')].map((link) => ({
    href: link.getAttribute('href'),
    type: link.getAttribute('type'),
    sizes: link.getAttribute('sizes'),
  }))

describe('setTabIcon', () => {
  beforeEach(() => {
    document.head.innerHTML = `
      <link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48" />
      <link rel="icon" href="/favicon.svg" type="image/svg+xml" />`
  })
  afterEach(() => {
    document.head.innerHTML = ''
  })

  it("shows the gym's logo in the tab", () => {
    setTabIcon('https://blobs.example/logo.png')

    expect(icons()).toEqual([
      { href: 'https://blobs.example/logo.png', type: null, sizes: null },
      { href: 'https://blobs.example/logo.png', type: null, sizes: null },
    ])
  })

  it("keeps Rakin's icons without a logo, and puts them back after one", () => {
    const rakin = icons()

    setTabIcon(null)
    expect(icons()).toEqual(rakin)

    setTabIcon('https://blobs.example/logo.png')
    setTabIcon('https://blobs.example/other.png')
    setTabIcon(undefined)
    expect(icons()).toEqual(rakin)
  })
})
