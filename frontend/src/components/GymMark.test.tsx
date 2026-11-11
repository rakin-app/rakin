import { describe, expect, it } from 'vitest'
import { initials } from './GymMark'

describe('initials', () => {
  it.each([
    ['Academia Sur', 'AS'],
    ['Meta', 'M'],
    ['  Ñandú   jiu jitsu club ', 'ÑJ'],
    ['"Gracie" Barra', 'GB'],
    ['10th Planet', '1P'],
  ])('reads %j as %s', (name, expected) => {
    expect(initials(name)).toBe(expected)
  })
})
