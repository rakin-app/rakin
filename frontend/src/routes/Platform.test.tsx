import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlatformGym } from '../api/platform'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { shortDate } from '../format'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.platform

type Answer = { status: number; body?: unknown }

// Every call answered by `answer`, by path; the calls made are returned.
function stubApi(answer: (path: string, method: string) => Answer) {
  const calls: { path: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      const method = init?.method ?? 'GET'
      calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const { status, body } = answer(path, method)
      return new Response(status === 204 ? null : JSON.stringify(body ?? {}), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

const BASE_HOST = { status: 200, body: { gym: null } }
const ME = { status: 200, body: { email: 'ops@rakin.app', name: 'Ops', fresh_until: '2026-11-18T12:10:00Z' } }

const GYMS: PlatformGym[] = [
  {
    id: 'a',
    slug: 'meta',
    name: 'Meta',
    address: 'https://meta.rakin.app',
    timezone: 'America/Santiago',
    created_at: '2026-11-10T12:00:00Z',
    titular_name: 'Titular de Meta',
    titular_email: 'titular@meta.cl',
    terms_version: '2026-11-20',
    terms_accepted_at: '2026-11-20T15:00:00Z',
    terms_state: 'current',
    members: 42,
    staff: 3,
    last_activity: '2026-11-17T20:00:00Z',
    status: 'active',
    owner_link_failed: false,
    suspended_at: null,
  },
  {
    id: 'b',
    slug: 'sur',
    name: 'Sur',
    address: 'https://sur.rakin.app',
    timezone: 'America/Santiago',
    created_at: '2026-11-11T12:00:00Z',
    titular_name: null,
    titular_email: null,
    terms_version: '2026-01-01',
    terms_accepted_at: '2026-01-05T12:00:00Z',
    terms_state: 'outdated',
    members: 0,
    staff: 1,
    last_activity: null,
    status: 'suspended',
    owner_link_failed: false,
    suspended_at: '2026-11-15T12:00:00Z',
  },
]

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('/plataforma', () => {
  it('sends a visitor with no operator session to the panel’s own sign-in', async () => {
    stubApi((path) => (path === '/api/host' ? BASE_HOST : { status: 401, body: { detail: 'not authenticated' } }))
    const router = renderAt('/plataforma')

    await screen.findByRole('heading', { name: copy.signIn.title })
    expect(router.state.location.pathname).toBe('/plataforma/ingresar')
  })

  it('is not found on a gym’s own address, and never asks who is signed in', async () => {
    const calls = stubApi((path) =>
      path === '/api/host' ? { status: 200, body: { gym: { slug: 'meta', name: 'Meta', theme: 'bosque', logo: null } } } : ME,
    )
    renderAt('/plataforma')

    await screen.findByRole('heading', { name: es.notFound.title })
    expect(calls.map((c) => c.path)).not.toContain('/api/platform/me')
  })

  it('lists every gym with its address, titular, terms, counts and status', async () => {
    stubApi((path) => {
      if (path === '/api/host') return BASE_HOST
      if (path === '/api/platform/me') return ME
      if (path === '/api/platform/gyms') return { status: 200, body: GYMS }
      return { status: 404 }
    })
    renderAt('/plataforma')

    const table = await screen.findByRole('table')
    expect(screen.getByText(copy.brand)).toBeInTheDocument()
    expect(screen.getByText('ops@rakin.app')).toBeInTheDocument()
    const [, meta, sur] = within(table).getAllByRole('row')
    expect(within(meta!).getByRole('link', { name: 'meta.rakin.app' })).toHaveAttribute('href', 'https://meta.rakin.app')
    expect(within(meta!).getByText('Titular de Meta')).toBeInTheDocument()
    expect(within(meta!).getByText(copy.gyms.terms.current)).toBeInTheDocument()
    expect(within(meta!).getByText('42')).toBeInTheDocument()
    expect(within(meta!).getByText(copy.gyms.status.active)).toBeInTheDocument()
    expect(within(sur!).getByText(copy.gyms.noTitular)).toBeInTheDocument()
    expect(within(sur!).getByText(copy.gyms.terms.outdated)).toBeInTheDocument()
    expect(within(sur!).getByText(copy.gyms.noActivity)).toBeInTheDocument()
    // Suspended (#439), and since when.
    expect(within(sur!).getByText(copy.gyms.status.suspended)).toBeInTheDocument()
    expect(within(sur!).getByText(copy.gyms.suspendedSince(shortDate('2026-11-15T12:00:00Z')))).toBeInTheDocument()
  })

  it('says when the titular’s link did not go, and sends it again', async () => {
    let failed = true
    let answers = [{ sent: false }, { sent: true }]
    const calls = stubApi((path, method) => {
      if (path === '/api/host') return BASE_HOST
      if (path === '/api/platform/me') return ME
      if (path === '/api/platform/gyms') {
        return { status: 200, body: [{ ...GYMS[0]!, owner_link_failed: failed }, GYMS[1]!] }
      }
      if (path === '/api/platform/gyms/a/owner-link' && method === 'POST') {
        const [answer, ...rest] = answers
        answers = rest
        failed = !answer!.sent
        return { status: 200, body: answer }
      }
      return { status: 404 }
    })
    renderAt('/plataforma')

    const table = await screen.findByRole('table')
    const [, meta, sur] = within(table).getAllByRole('row')
    expect(within(sur!).queryByText(copy.gyms.linkFailed)).not.toBeInTheDocument()
    expect(within(meta!).getByText(copy.gyms.linkFailed)).toBeInTheDocument()

    // It did not go again: said so, and the button stays.
    await userEvent.click(within(meta!).getByRole('button', { name: copy.gyms.resend }))
    expect(await within(meta!).findByRole('alert')).toHaveTextContent(copy.gyms.resendFailed)

    await userEvent.click(within(meta!).getByRole('button', { name: copy.gyms.resend }))
    await waitFor(() => expect(within(table).queryByText(copy.gyms.linkFailed)).not.toBeInTheDocument())
    expect(calls.filter((c) => c.path === '/api/platform/gyms/a/owner-link')).toHaveLength(2)
  })

  it('signs out into the panel’s sign-in', async () => {
    let signedIn = true
    const calls = stubApi((path, method) => {
      if (path === '/api/host') return BASE_HOST
      if (path === '/api/platform/auth/logout' && method === 'POST') {
        signedIn = false
        return { status: 204 }
      }
      if (!signedIn) return { status: 401 }
      if (path === '/api/platform/me') return ME
      if (path === '/api/platform/gyms') return { status: 200, body: [] }
      return { status: 404 }
    })
    const router = renderAt('/plataforma')

    await userEvent.click(await screen.findByRole('button', { name: copy.signOut }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/plataforma/ingresar'))
    expect(calls.some((c) => c.path === '/api/platform/auth/logout' && c.method === 'POST')).toBe(true)
  })

  it('a 401 mid-use goes back to the panel’s sign-in, not a gym’s', async () => {
    stubApi((path) => {
      if (path === '/api/host') return BASE_HOST
      if (path === '/api/platform/me') return ME
      return { status: 401 }
    })
    const router = renderAt('/plataforma')

    await waitFor(() => expect(router.state.location.pathname).toBe('/plataforma/ingresar'))
  })
})

describe('/plataforma/ingresar', () => {
  it('asks for the email, then signs in with the code into the panel', async () => {
    let signedIn = false
    const calls = stubApi((path, method) => {
      if (path === '/api/host') return BASE_HOST
      if (path === '/api/platform/auth/link') return { status: 202 }
      if (path === '/api/platform/auth/code' && method === 'POST') {
        signedIn = true
        return { status: 200, body: { next: '/plataforma' } }
      }
      if (!signedIn) return { status: 401 }
      if (path === '/api/platform/me') return ME
      if (path === '/api/platform/gyms') return { status: 200, body: GYMS }
      return { status: 404 }
    })
    const router = renderAt('/plataforma/ingresar')

    await userEvent.type(await screen.findByLabelText(copy.signIn.emailLabel), 'ops@rakin.app')
    await userEvent.click(screen.getByRole('button', { name: copy.signIn.submit }))
    await screen.findByText(copy.signIn.sentTitle)
    await userEvent.type(screen.getByLabelText(copy.signIn.codeLabel), '123 456')
    await userEvent.click(screen.getByRole('button', { name: copy.signIn.codeSubmit }))

    await screen.findByRole('table')
    expect(router.state.location.pathname).toBe('/plataforma')
    expect(calls.find((c) => c.path === '/api/platform/auth/code')?.body).toEqual({
      email: 'ops@rakin.app',
      code: '123456',
    })
  })

  it('says a wrong code is not the one', async () => {
    stubApi((path) => {
      if (path === '/api/host') return BASE_HOST
      if (path === '/api/platform/auth/link') return { status: 202 }
      if (path === '/api/platform/auth/code') return { status: 400, body: { detail: 'invalid' } }
      return { status: 401 }
    })
    renderAt('/plataforma/ingresar')

    await userEvent.type(await screen.findByLabelText(copy.signIn.emailLabel), 'ops@rakin.app')
    await userEvent.click(screen.getByRole('button', { name: copy.signIn.submit }))
    await userEvent.type(await screen.findByLabelText(copy.signIn.codeLabel), '000000')
    await userEvent.click(screen.getByRole('button', { name: copy.signIn.codeSubmit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.signIn.codeInvalid)
  })
})
