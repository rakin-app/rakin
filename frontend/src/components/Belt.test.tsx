import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Rank } from '../api/grading'
import { Belt, beltLabel, isDark, RankBelt } from './Belt'

// The BJJ preset's colours (backend `app.domain.grading`).
const WHITE = '#f4f4f1'
const BLUE = '#1f4fa3'
const BROWN = '#6e4223'
const BLACK = '#1b1b1b'
const GREY = '#8b8f94'

const parts = (container: HTMLElement, part: string) => container.querySelectorAll(`[data-part="${part}"]`)
const fills = (container: HTMLElement) => [...container.querySelectorAll('rect')].map((r) => r.getAttribute('fill'))

function rank(overrides: Partial<Rank> = {}): Rank {
  return {
    rank_key: 'blue',
    rank_label: 'Azul',
    sub_rank: '3',
    sub_rank_label: '3 grados',
    awarded_on: '2026-03-01',
    belt: { colors: [BLUE], stripes: 3, max_stripes: 4 },
    ...overrides,
  }
}

describe('Belt', () => {
  it.each([0, 1, 2, 3, 4])('draws %i of 4 stripes on a black bar', (stripes) => {
    const { container } = render(<Belt colors={[WHITE]} stripes={stripes} maxStripes={4} label="Blanca" />)
    expect(parts(container, 'stripe')).toHaveLength(stripes)
    expect(parts(container, 'bar')[0]).toHaveAttribute('fill', '#141414')
  })

  it('gives a black belt a red bar, as on a real one', () => {
    const { container } = render(<Belt colors={[BLACK]} stripes={2} maxStripes={4} label="Negra" />)
    expect(parts(container, 'bar')[0]).toHaveAttribute('fill', '#c8102e')
  })

  it('draws both colours of a two-tone belt', () => {
    const { container } = render(<Belt colors={[GREY, WHITE]} stripes={0} maxStripes={4} label="Gris y blanca" />)
    expect(fills(container)).toEqual(expect.arrayContaining([GREY, WHITE]))
  })

  it('keeps the stripes on the bar, however many the scheme has', () => {
    for (const max of [1, 4, 10, 19]) {
      const { container, unmount } = render(<Belt colors={[BLUE]} stripes={max} maxStripes={max} label="x" />)
      const bar = parts(container, 'bar')[0]!
      const start = Number(bar.getAttribute('x'))
      const end = start + Number(bar.getAttribute('width'))
      for (const stripe of parts(container, 'stripe')) {
        const x = Number(stripe.getAttribute('x'))
        expect(x).toBeGreaterThan(start)
        expect(x + Number(stripe.getAttribute('width'))).toBeLessThan(end)
      }
      expect(start).toBeGreaterThan(0)
      unmount()
    }
  })

  it('has no bar for a rank with no sub-ranks to earn', () => {
    const { container } = render(<Belt colors={[BLUE]} stripes={0} maxStripes={0} label="Azul" />)
    expect(parts(container, 'bar')).toHaveLength(0)
  })

  it('is an image named in words', () => {
    render(<Belt colors={[BLUE]} stripes={3} maxStripes={4} label="Azul, 3 grados" compact />)
    const belt = screen.getByRole('img', { name: 'Azul, 3 grados' })
    expect(belt).toHaveClass('belt--compact')
    // Named once: no `title` for a screen reader to announce again.
    expect(belt).not.toHaveAttribute('title')
  })
})

describe('RankBelt', () => {
  it('draws a rank the scheme colours', () => {
    const { container } = render(<RankBelt rank={rank()} />)
    expect(screen.getByRole('img', { name: 'Azul, 3 grados' })).toBeInTheDocument()
    expect(parts(container, 'stripe')).toHaveLength(3)
  })

  it('falls back for a rank without colours', () => {
    render(<RankBelt rank={rank({ belt: null })} fallback={<span>Azul · 3 grados</span>} />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText('Azul · 3 grados')).toBeInTheDocument()
  })
})

describe('beltLabel', () => {
  it('names the rank, and its sub-rank when it puts stripes on the bar', () => {
    expect(beltLabel(rank())).toBe('Azul, 3 grados')
    const none = rank({ sub_rank: '0', sub_rank_label: 'Sin grados', belt: { colors: [BLUE], stripes: 0, max_stripes: 4 } })
    expect(beltLabel(none)).toBe('Azul')
    expect(beltLabel(rank({ rank_label: '9.º kyu', sub_rank: null, sub_rank_label: null }))).toBe('9.º kyu')
  })
})

describe('isDark', () => {
  it('takes black for dark, and not brown or the other belts', () => {
    expect(isDark(BLACK)).toBe(true)
    expect(isDark('#000000')).toBe(true)
    expect([WHITE, BLUE, BROWN, GREY].map(isDark)).toEqual([false, false, false, false])
  })
})
