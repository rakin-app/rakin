import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { createQueryClient } from './queryClient'

describe('createQueryClient', () => {
  const retry = createQueryClient().getDefaultOptions().queries?.retry as (n: number, e: unknown) => boolean

  it('does not retry client errors', () => {
    expect(retry(0, new ApiError(401, undefined))).toBe(false)
    expect(retry(0, new ApiError(404, undefined))).toBe(false)
  })

  it('retries server and network errors a bounded number of times', () => {
    expect(retry(0, new ApiError(503, undefined))).toBe(true)
    expect(retry(1, new TypeError('Failed to fetch'))).toBe(true)
    expect(retry(2, new TypeError('Failed to fetch'))).toBe(false)
  })
})
