import { afterEach, describe, expect, it, vi } from 'vitest'
import { isOffline } from './attendance'
import { ApiError } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('isOffline', () => {
  it('is a network failure, which fetch rejects with as a TypeError', () => {
    expect(isOffline(new TypeError('Failed to fetch'))).toBe(true)
  })

  it('is not an answer from the API, nor a bug', () => {
    expect(isOffline(new ApiError(422, {}))).toBe(false)
    expect(isOffline(new ApiError(503, {}))).toBe(false)
    expect(isOffline(new SyntaxError('Unexpected token'))).toBe(false)
  })

  it('is any failure while the browser knows it is offline, but an answer', () => {
    vi.stubGlobal('navigator', { onLine: false })
    expect(isOffline(new Error('aborted'))).toBe(true)
    expect(isOffline(new ApiError(500, {}))).toBe(false)
  })
})
