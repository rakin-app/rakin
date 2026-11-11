import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Host } from '../api/host'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.signIn

type Sent = { path: string; body: unknown }

// `/api/auth/link` answers `status` with `headers`, and `/api/host` names `gym`; the
// links asked for are kept.
function stubLink(status: number, headers: Record<string, string> = {}, gym: Host['gym'] = null) {
  const sent: Sent[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === '/api/host') {
        return new Response(JSON.stringify({ gym }), { headers: { 'Content-Type': 'application/json' } })
      }
      sent.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      return new Response(status === 202 ? null : JSON.stringify({ detail: 'x' }), {
        status,
        headers: { 'Content-Type': 'application/json', ...headers },
      })
    }),
  )
  return sent
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

async function ask(email: string) {
  await userEvent.type(await screen.findByLabelText(copy.emailLabel), email)
  await userEvent.click(screen.getByRole('button', { name: copy.submit }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('Entrar', () => {
  it('asks for a link and says the same thing whoever the address is', async () => {
    const sent = stubLink(202)
    renderAt('/ingresar')

    await ask(' ana@example.cl ')

    expect(await screen.findByRole('status')).toHaveTextContent(copy.sent('ana@example.cl'))
    expect(sent).toEqual([{ path: '/api/auth/link', body: { email: 'ana@example.cl' } }])
    // The answer never depends on the address: the API gives none, and the copy has one shape.
    expect(copy.sent('nadie@example.cl')).toBe(copy.sent('ana@example.cl').replace('ana@', 'nadie@'))
  })

  it("names Rakin on the shared address, and the gym on the gym's own", async () => {
    stubLink(202)
    renderAt('/ingresar')
    expect(await screen.findByRole('heading', { name: copy.title })).toBeInTheDocument()
    vi.unstubAllGlobals()
    cleanup()

    const sent = stubLink(202, {}, { slug: 'meta', name: 'Meta', theme: 'bosque' })
    renderAt('/ingresar')
    expect(await screen.findByRole('heading', { name: copy.titleAt('Meta') })).toBeInTheDocument()

    await ask('ana@example.cl')
    expect(await screen.findByRole('status')).toHaveTextContent(copy.sent('ana@example.cl'))
    expect(sent).toEqual([{ path: '/api/auth/link', body: { email: 'ana@example.cl' } }])
  })

  it('lets them ask again with another address', async () => {
    stubLink(202)
    renderAt('/ingresar')
    await ask('ana@example.cl')

    await userEvent.click(await screen.findByRole('button', { name: copy.another }))

    expect(screen.getByLabelText(copy.emailLabel)).toBeInTheDocument()
  })

  it('says when to try again after too many requests, from Retry-After', async () => {
    stubLink(429, { 'Retry-After': '540' })
    renderAt('/ingresar')

    await ask('ana@example.cl')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.tooMany(9))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('asks them to try again in a few minutes when Retry-After is missing', async () => {
    stubLink(429)
    renderAt('/ingresar')

    await ask('ana@example.cl')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.tooMany(null))
  })

  it('says so when the request does not go through', async () => {
    stubLink(503)
    renderAt('/ingresar')

    await ask('ana@example.cl')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.failed)
  })

  it('keeps the page they had asked for, for when the link lands them', async () => {
    stubLink(202)
    renderAt('/ingresar?redirect=%2Fadmin%2Fpagos')

    await ask('ana@example.cl')

    await screen.findByRole('status')
    expect(localStorage.getItem('rakin.returnTo')).toBe('/admin/pagos')
  })

  it.each(['https://evil.example/x', '//evil.example/x', '/ingresar'])('never keeps %s', async (redirect) => {
    localStorage.setItem('rakin.returnTo', '/admin/alumnos')
    stubLink(202)
    renderAt(`/ingresar?redirect=${encodeURIComponent(redirect)}`)

    await ask('ana@example.cl')

    await screen.findByRole('status')
    expect(localStorage.getItem('rakin.returnTo')).toBeNull()
  })
})
