import { describe, expect, it } from 'vitest'
import { zonedInstant } from './format'

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
