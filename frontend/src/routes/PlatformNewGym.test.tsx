import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { NewGymChoices, SlugCheck } from '../api/platform'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.platform.newGym

type Answer = { status: number; body?: unknown }
type Call = { path: string; query: string; method: string; body: unknown }

// Every call answered by `answer`; the calls made are returned.
function stubApi(answer: (call: Call) => Answer) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const call = {
        path: url.pathname,
        query: url.search,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      const { status, body } = answer(call)
      return new Response(JSON.stringify(body ?? {}), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

const ME = { status: 200, body: { email: 'ops@rakin.app', name: 'Ops', fresh_until: '2026-11-18T12:10:00Z' } }
const CHOICES: NewGymChoices = {
  grading: [
    { key: 'bjj', label: 'Jiu-jitsu brasileño' },
    { key: 'none', label: 'Sin grados' },
  ],
  timezones: ['America/Santiago', 'Europe/Madrid'],
}

function slugCheck(slug: string): SlugCheck {
  const address = `https://${slug}.rakin.app`
  if (slug === 'admin') return { address, problem: 'reserved' }
  if (slug === 'meta') return { address, problem: 'taken' }
  return { address, problem: null }
}

function panelApi(create: (body: unknown) => Answer = () => ({ status: 500 })) {
  return stubApi((call) => {
    if (call.path === '/api/host') return { status: 200, body: { gym: null } }
    if (call.path === '/api/platform/me') return ME
    if (call.path === '/api/platform/presets') return { status: 200, body: CHOICES }
    if (call.path === '/api/platform/slug') {
      return { status: 200, body: slugCheck(new URLSearchParams(call.query).get('slug')!) }
    }
    if (call.path === '/api/platform/gyms' && call.method === 'POST') return create(call.body)
    if (call.path === '/api/platform/gyms') return { status: 200, body: [] }
    return { status: 404 }
  })
}

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

describe('/plataforma/nuevo', () => {
  it('is linked from the list of gyms', async () => {
    panelApi()
    const router = renderAt('/plataforma')

    await userEvent.click(await screen.findByRole('link', { name: es.platform.gyms.add }))

    await screen.findByRole('heading', { name: copy.title })
    expect(router.state.location.pathname).toBe('/plataforma/nuevo')
  })

  it('checks the slug as it is typed, once it rests, and says the address or what is wrong', async () => {
    const calls = panelApi()
    renderAt('/plataforma/nuevo')
    const slug = await screen.findByLabelText(copy.slug)

    await userEvent.type(slug, 'Nuevo')
    // Lower-cased as typed, and checked once, for what it settled on.
    expect(slug).toHaveValue('nuevo')
    expect(await screen.findByText(copy.willBe('https://nuevo.rakin.app'))).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/platform/slug').map((c) => c.query)).toEqual(['?slug=nuevo'])

    await userEvent.clear(slug)
    await userEvent.type(slug, 'meta')
    expect(await screen.findByText(copy.problems.taken)).toBeInTheDocument()
    expect(slug).toHaveAttribute('aria-invalid', 'true')

    await userEvent.clear(slug)
    await userEvent.type(slug, 'admin')
    expect(await screen.findByText(copy.problems.reserved)).toBeInTheDocument()
  })

  it('creates the gym pending its terms, and shows its address and the invitation sent', async () => {
    const calls = panelApi(() => ({
      status: 201,
      body: { id: 'g', slug: 'nuevo', address: 'https://nuevo.rakin.app' },
    }))
    renderAt('/plataforma/nuevo')

    await userEvent.type(await screen.findByLabelText(copy.name), 'Gimnasio Nuevo')
    await userEvent.type(screen.getByLabelText(copy.slug), 'nuevo')
    await userEvent.selectOptions(screen.getByLabelText(copy.grading), 'bjj')
    await userEvent.type(screen.getByLabelText(copy.ownerEmail), 'duena@example.cl')
    await userEvent.type(screen.getByLabelText(copy.ownerName), 'Dueña')
    // No date to give: the titular accepts the terms in the app (#499).
    expect(screen.queryByLabelText(/firma/i)).not.toBeInTheDocument()
    expect(screen.getByText(copy.termsNote)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    await screen.findByRole('heading', { name: copy.created })
    expect(screen.getByRole('link', { name: 'https://nuevo.rakin.app' })).toHaveAttribute(
      'href',
      'https://nuevo.rakin.app',
    )
    expect(screen.getByText(copy.linkSent('duena@example.cl'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: copy.toList })).toHaveAttribute('href', '/plataforma')
    const [sent] = calls.filter((c) => c.path === '/api/platform/gyms' && c.method === 'POST')
    expect(sent!.body).toEqual({
      slug: 'nuevo',
      name: 'Gimnasio Nuevo',
      timezone: 'America/Santiago',
      owner_email: 'duena@example.cl',
      owner_name: 'Dueña',
      owner_rut: null,
      owner_phone: null,
      grading: 'bjj',
    })

    const write = vi.fn<(text: string) => Promise<void>>(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    await userEvent.click(screen.getByRole('button', { name: copy.copy }))
    expect(write).toHaveBeenCalledWith('https://nuevo.rakin.app')
    expect(await screen.findByText(copy.copied)).toBeInTheDocument()
  })

  it('says why the API refused, by the field, and focuses the first', async () => {
    panelApi(() => ({
      status: 422,
      body: {
        detail: [
          { type: 'slug_taken', loc: ['body', 'slug'], msg: 'a gym has this slug' },
          { type: 'value_error', loc: ['body', 'owner_rut'], msg: 'not a RUT' },
        ],
      },
    }))
    renderAt('/plataforma/nuevo')

    await userEvent.type(await screen.findByLabelText(copy.slug), 'nuevo')
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByText(copy.refusals.owner_rut)).toBeInTheDocument()
    expect(screen.getByText(copy.refusals.slug_taken)).toBeInTheDocument()
    expect(screen.getByText(copy.invalid)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(copy.slug)).toHaveFocus())
  })
})
