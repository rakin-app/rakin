import { describe, expect, it } from 'vitest'
import { shiftDay, timeRange, zonedInstant } from './format'

describe('zonedInstant', () => {
  it("is the wall time in the gym's timezone, not the device's", () => {
    // Santiago is UTC-3 in November, UTC-4 in July.
    expect(zonedInstant('2026-11-09', '19:00', 'America/Santiago')).toBe('2026-11-09T22:00:00.000Z')
    expect(zonedInstant('2026-07-09', '19:00', 'America/Santiago')).toBe('2026-07-09T23:00:00.000Z')
    expect(zonedInstant('2026-11-09', '23:30', 'UTC')).toBe('2026-11-09T23:30:00.000Z')
  })

  it('takes the offset in force on either side of a change', () => {
    // Santiago went back an hour on 2026-04-05 at 00:00 (UTC-3 to UTC-4).
    expect(zonedInstant('2026-04-04', '20:00', 'America/Santiago')).toBe('2026-04-04T23:00:00.000Z')
    expect(zonedInstant('2026-04-05', '20:00', 'America/Santiago')).toBe('2026-04-06T00:00:00.000Z')
  })
})

describe('timeRange', () => {
  it('runs from the start for the duration, on the gym clock', () => {
    // 19:00 in Santiago, summer time.
    expect(timeRange('2026-11-10T22:00:00Z', 90, 'America/Santiago')).toBe('19:00–20:30')
  })

  it('crosses midnight', () => {
    expect(timeRange('2026-11-11T02:30:00Z', 60, 'America/Santiago')).toBe('23:30–00:30')
  })

  it('is the start alone with no duration', () => {
    expect(timeRange('2026-11-10T22:00:00Z', null, 'America/Santiago')).toBe('19:00')
  })
})

describe('shiftDay', () => {
  it('moves across months and years', () => {
    expect(shiftDay('2026-11-30', 1)).toBe('2026-12-01')
    expect(shiftDay('2027-01-01', -1)).toBe('2026-12-31')
  })

  it('is calendar days, whatever the clock change', () => {
    expect(shiftDay('2027-09-04', 1)).toBe('2027-09-05')
    expect(shiftDay('2027-04-04', -1)).toBe('2027-04-03')
  })
})
