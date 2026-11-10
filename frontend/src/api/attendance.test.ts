import { afterEach, describe, expect, it, vi } from 'vitest'
import { isOffline, isRefusal } from './attendance'
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

describe('isRefusal', () => {
  it('is an answer that resending would get again', () => {
    for (const status of [404, 409, 422]) expect(isRefusal(new ApiError(status, {}))).toBe(true)
  })

  it('is not a server error, an expired session, a rate limit or no signal', () => {
    for (const status of [500, 502, 503, 401, 429]) expect(isRefusal(new ApiError(status, {}))).toBe(false)
    expect(isRefusal(new TypeError('Failed to fetch'))).toBe(false)
  })
})
