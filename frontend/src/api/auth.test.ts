import { afterEach, describe, expect, it } from 'vitest'
import { landingFor, rememberReturnPath } from './auth'

afterEach(() => localStorage.clear())

describe('landingFor', () => {
  it('takes staff who are also students to /me when that is what they asked for (#214)', () => {
    rememberReturnPath('/me')
    expect(landingFor('coach')).toBe('/me')
  })

  it('keeps an admin deep link for staff', () => {
    rememberReturnPath('/admin/clases/abc')
    expect(landingFor('owner')).toBe('/admin/clases/abc')
  })

  it('never takes a member into /admin', () => {
    rememberReturnPath('/admin/pagos')
    expect(landingFor(null)).toBe('/me')
  })

  it('uses the kept path once', () => {
    rememberReturnPath('/me')
    landingFor('coach')
    expect(landingFor('coach')).toBe('/admin')
  })
})
