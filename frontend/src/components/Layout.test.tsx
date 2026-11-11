import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDesktop, useWide } from './Layout'

afterEach(() => {
  vi.unstubAllGlobals()
})

function Probe() {
  return <p>{`${useDesktop()} ${useWide()}`}</p>
}

describe('useDesktop and useWide', () => {
  it('ask for the breakpoints styles/media.css defines, the ones the stylesheets use', () => {
    const asked: string[] = []
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => {
        asked.push(query)
        return { matches: query.includes('960'), media: query, addEventListener: () => {}, removeEventListener: () => {} }
      }),
    )
    render(<Probe />)

    expect(screen.getByText('true false')).toBeInTheDocument()
    expect(new Set(asked)).toEqual(new Set(['(min-width: 960px)', '(min-width: 1024px)']))
  })

  it('say no where the browser cannot tell', () => {
    render(<Probe />)
    expect(screen.getByText('false false')).toBeInTheDocument()
  })
})
