import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from './client'
import { newKey, submissionKey, useSubmit, withSubmission } from './submit'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

type Sent = { method: string; path: string; key: string | null }

/** Answers every request with `status`, once `release` is called if `held`. */
function stubFetch({ status = 200, held = false }: { status?: number; held?: boolean } = {}) {
  const sent: Sent[] = []
  let release = () => {}
  const gate = held ? new Promise<void>((resolve) => (release = resolve)) : Promise.resolve()
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      sent.push({
        method: init?.method ?? 'GET',
        path: String(input),
        key: new Headers(init?.headers).get('Idempotency-Key'),
      })
      await gate
      return new Response(JSON.stringify({ ok: status < 400 }), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return { sent, release: () => release() }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

const post = (path: string) => apiFetch(path, { method: 'POST', body: '{}' })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch and the submission key', () => {
  it('keys the mutating requests a submission makes, and only those', async () => {
    const { sent } = stubFetch()
    await withSubmission('k', () =>
      Promise.all([post('/api/a'), apiFetch('/api/b'), post('/api/c'), post('/api/auth/link')]),
    )
    await post('/api/d')

    expect(sent).toEqual([
      { method: 'POST', path: '/api/a', key: 'k' },
      { method: 'GET', path: '/api/b', key: null },
      // The second mutating request in the same tick: a key of its own, the same on a retry.
      { method: 'POST', path: '/api/c', key: 'k:2' },
      // Sign-in sets cookies, which a replayed answer would not carry.
      { method: 'POST', path: '/api/auth/link', key: null },
      // Outside a submission.
      { method: 'POST', path: '/api/d', key: null },
    ])
  })

  it('takes a step key a flow names, after an await', async () => {
    const { sent } = stubFetch()
    await withSubmission('k', async () => {
      const key = submissionKey()
      await post('/api/first')
      await apiFetch('/api/then', { method: 'PUT', idempotencyKey: `${key}:then` })
      await post('/api/unnamed')
    })
    expect(sent.map((s) => s.key)).toEqual(['k', 'k:then', null])
  })

  it('makes a v4 UUID, with or without crypto.randomUUID', () => {
    expect(newKey()).toMatch(UUID)
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })
    expect(newKey()).toMatch(UUID)
  })
})

describe('useSubmit', () => {
  it('runs a double tap once: the repeat is the same submission while it runs', async () => {
    const { sent, release } = stubFetch({ held: true })
    const { result } = renderHook(() => useSubmit({ mutationFn: () => post('/api/ledger/payments') }), {
      wrapper,
    })

    let first: Promise<unknown> | undefined
    let second: Promise<unknown> | undefined
    act(() => {
      first = result.current.mutateAsync()
      second = result.current.mutateAsync()
      result.current.mutate()
    })
    expect(second).toBe(first)
    release()
    await act(() => first)

    expect(sent).toHaveLength(1)
    expect(sent[0]!.key).toMatch(UUID)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('runs different variables side by side, each with its own key', async () => {
    const { sent } = stubFetch()
    const { result } = renderHook(
      () => useSubmit({ mutationFn: (id: string) => post(`/api/attendance/${id}`) }),
      { wrapper },
    )
    await act(() => Promise.all([result.current.mutateAsync('ana'), result.current.mutateAsync('beto')]))

    expect(sent.map((s) => s.path)).toEqual(['/api/attendance/ana', '/api/attendance/beto'])
    expect(sent[0]!.key).not.toBe(sent[1]!.key)
  })

  it('sends the key again on a retry after an error, and a new one after a success', async () => {
    const { sent } = stubFetch({ status: 503 })
    const { result } = renderHook(() => useSubmit({ mutationFn: () => post('/api/staff') }), { wrapper })

    await act(() => result.current.mutateAsync().catch(() => {}))
    await act(() => result.current.mutateAsync().catch(() => {}))
    const { sent: after } = stubFetch()
    await act(() => result.current.mutateAsync())
    await act(() => result.current.mutateAsync())

    expect(sent[0]!.key).toMatch(UUID)
    expect(sent[1]!.key).toBe(sent[0]!.key)
    // The retry that landed still had it; the next submission is a new one.
    expect(after[0]!.key).toBe(sent[0]!.key)
    expect(after[1]!.key).not.toBe(sent[0]!.key)
  })
})
