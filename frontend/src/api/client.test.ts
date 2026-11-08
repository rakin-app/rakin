import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch } from './client'

function mockFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('requests a relative path on the same origin with the session cookie', async () => {
    const fetchMock = mockFetch(json({ status: 'ok' }))

    await expect(apiFetch('/api/members')).resolves.toEqual({ status: 'ok' })

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/members')
    expect(init?.credentials).toBe('same-origin')
    expect(new Headers(init?.headers).get('Accept')).toBe('application/json')
  })

  it.each(['https://api.example.com/x', '//evil.example/x', 'api/members'])(
    'refuses %s, which is not a same-origin path',
    async (path) => {
      const fetchMock = mockFetch(json({}))
      await expect(apiFetch(path)).rejects.toThrow(/same-origin path/)
      expect(fetchMock).not.toHaveBeenCalled()
    },
  )

  it('sends JSON bodies with a JSON content type', async () => {
    const fetchMock = mockFetch(json({ id: 1 }, 201))

    await apiFetch('/api/members', { method: 'POST', body: JSON.stringify({ name: 'Diego' }) })

    expect(new Headers(fetchMock.mock.calls[0]![1]?.headers).get('Content-Type')).toBe('application/json')
  })

  it('throws ApiError carrying the status and parsed body', async () => {
    mockFetch(json({ detail: 'not found' }, 404))

    const error = await apiFetch('/api/members/9').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, body: { detail: 'not found' } })
  })

  it('keeps the status when an error body claims JSON but is malformed', async () => {
    mockFetch(new Response('<html>Bad Gateway</html>', { status: 502, headers: { 'Content-Type': 'application/json' } }))

    const error = await apiFetch('/api/members').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 502, body: '<html>Bad Gateway</html>' })
  })

  it('resolves undefined on 204 No Content', async () => {
    mockFetch(new Response(null, { status: 204 }))
    await expect(apiFetch('/api/members/9', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
