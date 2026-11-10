import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PersonTime, TimeTotals } from '../api/matTime'
import { es } from '../i18n/es'
import { MatTime } from './MatTime'

const copy = es.matTime

const NONE: TimeTotals = { by_kind: [], sparring_seconds: 0, open_mat_seconds: 0, classes: 0, open_mats: 0 }

const kind = (name: string, seconds: number, is_sparring = false) => ({
  block_kind_id: `k-${name}`,
  name,
  is_sparring,
  seconds,
})

// Two classes and an open mat this month; the sparring kind holds the open mat's time.
const MONTH: TimeTotals = {
  by_kind: [kind('Técnica', 2400), kind('Sparring', 5400 + 16200, true)],
  sparring_seconds: 21600,
  open_mat_seconds: 16200,
  classes: 2,
  open_mats: 3,
}

const ALL_TIME: TimeTotals = {
  by_kind: [kind('Calentamiento', 36000), kind('Técnica', 90000), kind('Sparring', 180000, true)],
  sparring_seconds: 180000,
  open_mat_seconds: 16200,
  classes: 48,
  open_mats: 3,
}

function time(this_month: TimeTotals, all_time: TimeTotals): PersonTime {
  return { timezone: 'America/Santiago', month_start: '2026-11-01', this_month, all_time }
}

const card = (mine = true) => screen.getByRole('region', { name: mine ? copy.mine : copy.theirs })
const figure = (region: HTMLElement, term: string) =>
  within(region).getByText(term, { selector: 'dt' }).nextElementSibling?.textContent

describe('duration', () => {
  it('writes hours and minutes in Spanish', () => {
    expect(copy.duration(0)).toBe('0 min')
    expect(copy.duration(20)).toBe('< 1 min')
    expect(copy.duration(45 * 60)).toBe('45 min')
    expect(copy.duration(2 * 3600)).toBe('2 h')
    expect(copy.duration(4 * 3600 + 30 * 60)).toBe('4 h 30 min')
    // Rounded to the minute, carrying into the hour.
    expect(copy.duration(3599)).toBe('1 h')
    expect(copy.duration(1200 * 3600)).toBe('1.200 h')
  })
})

describe('MatTime', () => {
  it('says there is nothing yet when no session was timed', () => {
    render(<MatTime time={time(NONE, { ...NONE, classes: 4 })} mine />)

    expect(within(card()).getByText(copy.emptyMine)).toBeInTheDocument()
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument()
  })

  it('speaks of the member on the ficha', () => {
    render(<MatTime time={time(NONE, NONE)} mine={false} />)

    expect(within(card(false)).getByText(copy.emptyTheirs)).toBeInTheDocument()
  })

  it('shows this month first, as the API totals it', () => {
    render(<MatTime time={time(MONTH, ALL_TIME)} mine />)
    const region = card()

    expect(within(region).getByRole('button', { name: copy.month })).toHaveAttribute('aria-pressed', 'true')
    expect(figure(region, copy.classes)).toBe('2')
    expect(figure(region, copy.sparring)).toBe('6 h')
    const kinds = within(within(region).getByRole('list', { name: copy.byKind })).getAllByRole('listitem')
    expect(kinds.map((row) => row.textContent)).toEqual(['Técnica40 min', 'Sparring6 h'])
    expect(within(region).getByText(copy.openMat(3, '4 h 30 min'))).toBeInTheDocument()
  })

  it('switches to all time', async () => {
    render(<MatTime time={time(MONTH, ALL_TIME)} mine />)
    const region = card()

    await userEvent.click(within(region).getByRole('button', { name: copy.allTime }))

    expect(within(region).getByRole('button', { name: copy.allTime })).toHaveAttribute('aria-pressed', 'true')
    expect(figure(region, copy.classes)).toBe('48')
    expect(figure(region, copy.sparring)).toBe('50 h')
    const kinds = within(within(region).getByRole('list', { name: copy.byKind })).getAllByRole('listitem')
    expect(kinds.map((row) => row.textContent)).toEqual(['Calentamiento10 h', 'Técnica25 h', 'Sparring50 h'])
  })

  it('says this month has nothing yet when only earlier months were timed', async () => {
    render(<MatTime time={time({ ...NONE, classes: 1 }, ALL_TIME)} mine />)
    const region = card()

    expect(figure(region, copy.classes)).toBe('1')
    expect(within(region).getByText(copy.emptyMonth)).toBeInTheDocument()
    expect(within(region).queryByRole('list')).not.toBeInTheDocument()

    await userEvent.click(within(region).getByRole('button', { name: copy.allTime }))
    expect(within(region).queryByText(copy.emptyMonth)).not.toBeInTheDocument()
  })

  it('leaves out the open mat line without open mats', () => {
    const classesOnly = { ...MONTH, open_mats: 0, open_mat_seconds: 0 }
    render(<MatTime time={time(classesOnly, classesOnly)} mine />)

    expect(within(card()).queryByText(copy.openMatNote)).not.toBeInTheDocument()
  })

  it('keeps the bars out of the accessible text', () => {
    const { container } = render(<MatTime time={time(MONTH, ALL_TIME)} mine />)

    const bars = container.querySelectorAll('.mat-time__bar')
    expect(bars).toHaveLength(2)
    bars.forEach((bar) => expect(bar).toHaveAttribute('aria-hidden', 'true'))
  })
})
