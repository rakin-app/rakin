import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Host } from '../api/host'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { storedTheme } from '../theme'

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

  it("wears the gym's theme on its own address, before anyone signs in (#199)", async () => {
    stubLink(202, {}, { slug: 'meta', name: 'Meta', theme: 'oceano', logo: null })
    renderAt('/ingresar')

    expect(await screen.findByRole('heading', { name: copy.titleAt('Meta') })).toBeInTheDocument()
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('oceano'))
    // Kept, so the next visit opens in it rather than flashing the default first.
    expect(storedTheme()).toBe('oceano')
  })

  it("names Rakin on the shared address, and the gym on the gym's own", async () => {
    stubLink(202)
    renderAt('/ingresar')
    expect(await screen.findByRole('heading', { name: copy.title })).toBeInTheDocument()
    // The tab is named as the admin screens name theirs (#213).
    expect(document.title).toBe('Entrar · Rakin')
    vi.unstubAllGlobals()
    cleanup()

    const sent = stubLink(202, {}, { slug: 'meta', name: 'Meta', theme: 'bosque', logo: null })
    renderAt('/ingresar')
    expect(await screen.findByRole('heading', { name: copy.titleAt('Meta') })).toBeInTheDocument()
    expect(document.title).toBe('Entrar · Meta')

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

type Answer = { status: number; body?: unknown; headers?: Record<string, string> }

// `/api/auth/link` answers 202, `/api/auth/code` each of `codes` in turn, and once in,
// `/api/me/role` says they are a member; everything else is unreachable.
function stubCode(...codes: Answer[]) {
  const sent: Sent[] = []
  const json = { 'Content-Type': 'application/json' }
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === '/api/host') return new Response(JSON.stringify({ gym: null }), { headers: json })
      sent.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (path === '/api/auth/link') return new Response(null, { status: 202 })
      if (path === '/api/auth/code') {
        const { status, body, headers } = codes.shift() ?? { status: 503 }
        return new Response(JSON.stringify(body ?? {}), { status, headers: { ...json, ...headers } })
      }
      if (path === '/api/me/role') {
        const me = { role: null, person_id: 'p', name: 'Ana', email: null, gym_name: 'Sur', student_page: true }
        return new Response(JSON.stringify(me), { headers: json })
      }
      return new Response('{}', { status: 503, headers: json })
    }),
  )
  return sent
}

async function typeCode(code: string) {
  const input = await screen.findByLabelText(copy.codeLabel)
  await userEvent.clear(input)
  await userEvent.type(input, code)
  await userEvent.click(screen.getByRole('button', { name: copy.codeSubmit }))
}

describe('Entrar with the code (#276)', () => {
  it('offers a one-time-code input once the link is sent', async () => {
    stubCode()
    renderAt('/ingresar')
    await ask('ana@example.cl')

    expect(await screen.findByRole('heading', { name: copy.sentTitle })).toBeInTheDocument()
    const input = screen.getByLabelText(copy.codeLabel)
    expect(input).toHaveAttribute('inputmode', 'numeric')
    expect(input).toHaveAttribute('autocomplete', 'one-time-code')
    expect(input).toHaveAccessibleDescription(copy.codeHint)
    expect(screen.getByRole('button', { name: copy.codeSubmit })).toBeDisabled()
  })

  it('signs in with the code as the email shows it, and goes where the link would have', async () => {
    const sent = stubCode({ status: 200, body: { next: '/' } })
    const router = renderAt('/ingresar')
    await ask('ana@example.cl')

    const input = await screen.findByLabelText(copy.codeLabel)
    await userEvent.click(input)
    await userEvent.paste('042 917')
    expect(input).toHaveValue('042917')
    await userEvent.click(screen.getByRole('button', { name: copy.codeSubmit }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/me'))
    expect(sent.find((s) => s.path === '/api/auth/code')).toEqual({
      path: '/api/auth/code',
      body: { email: 'ana@example.cl', code: '042917' },
    })
  })

  it('says a wrong code is wrong, and takes another', async () => {
    stubCode({ status: 400, body: { detail: 'invalid' } }, { status: 200, body: { next: '/' } })
    const router = renderAt('/ingresar')
    await ask('ana@example.cl')

    await typeCode('111111')
    expect(await screen.findByRole('alert')).toHaveTextContent(copy.codeInvalid)
    expect(screen.queryByRole('button', { name: copy.resend })).not.toBeInTheDocument()

    await typeCode('042917')
    await waitFor(() => expect(router.state.location.pathname).toBe('/me'))
  })

  it('offers another link and code when the code has expired', async () => {
    const sent = stubCode({ status: 400, body: { detail: 'expired' } })
    renderAt('/ingresar')
    await ask('ana@example.cl')

    await typeCode('042917')
    expect(await screen.findByRole('alert')).toHaveTextContent(copy.codeExpired)
    await userEvent.click(screen.getByRole('button', { name: copy.resend }))

    expect(await screen.findByText(copy.resent)).toBeInTheDocument()
    expect(screen.getByLabelText(copy.codeLabel)).toHaveValue('')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(sent.filter((s) => s.path === '/api/auth/link')).toHaveLength(2)
  })

  it('says when there were too many tries, from Retry-After', async () => {
    stubCode({ status: 429, headers: { 'Retry-After': '600' } })
    renderAt('/ingresar')
    await ask('ana@example.cl')

    await typeCode('042917')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.codeTooMany(10))
  })

  it("says so when the address has no access to this gym's site", async () => {
    stubCode({ status: 403, body: { detail: 'unreachable' } })
    renderAt('/ingresar')
    await ask('ana@example.cl')

    await typeCode('042917')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.codeUnreachable('Rakin'))
  })
})
