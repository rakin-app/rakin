import { afterEach, expect, it, vi } from 'vitest'
import { healthQuery } from './health'
import { createQueryClient } from './queryClient'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('fetches /healthz through the query client', async () => {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({ status: 'ok' }), { headers: { 'Content-Type': 'application/json' } }),
  )
  vi.stubGlobal('fetch', fetchMock)

  await expect(createQueryClient().fetchQuery(healthQuery)).resolves.toEqual({ status: 'ok' })
  expect(fetchMock.mock.calls[0]![0]).toBe('/healthz')
})
