import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlatformGym, PlatformGymDetail, SlugCheck } from '../api/platform'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.platform.gym
const reauthCopy = es.platform.reauth

type Answer = { status: number; body?: unknown }
type Call = { path: string; query: string; method: string; body: unknown }

// Every call answered by `answer`; the calls made are returned.
function stubApi(answer: (call: Call) => Answer | undefined) {
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
      const { status, body } = answer(call) ?? panel(call)
      if (status === 204 || status === 202) return new Response(null, { status })
      return new Response(JSON.stringify(body ?? {}), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

const GYM_ID = 'g-1'
const RENAME = `/api/platform/gyms/${GYM_ID}/slug`
const ME = { email: 'ops@rakin.app', name: 'Ops', fresh_until: '2026-11-18T12:10:00Z' }

function detail(changes: Partial<PlatformGymDetail> = {}): PlatformGymDetail {
  return {
    id: GYM_ID,
    slug: 'norte',
    name: 'Gimnasio Norte',
    address: 'https://norte.rakin.app',
    titular_name: 'Dueña',
    titular_email: 'duena@example.cl',
    titular_phone: '+56911111111',
    titular_signed_in: false,
    terms: [{ version: '2026-11-18', signed_on: '2026-11-19' }],
    terms_version: '2026-11-18',
    aliases: [],
    ...changes,
  }
}

const LISTED: PlatformGym = {
  id: GYM_ID,
  slug: 'norte',
  name: 'Gimnasio Norte',
  address: 'https://norte.rakin.app',
  timezone: 'America/Santiago',
  created_at: '2026-11-18T12:00:00Z',
  titular_name: 'Dueña',
  titular_email: 'duena@example.cl',
  terms_version: '2026-11-18',
  terms_signed_on: '2026-11-19',
  terms_current: true,
  members: 0,
  staff: 1,
  last_activity: null,
  status: 'active',
  owner_link_failed: false,
}

function slugCheck(slug: string): SlugCheck {
  const address = `https://${slug}.rakin.app`
  return { address, problem: slug === 'meta' ? 'taken' : null }
}

// What the panel answers when a test does not say otherwise.
function panel(call: Call): Answer {
  if (call.path === '/api/host') return { status: 200, body: { gym: null } }
  if (call.path === '/api/platform/me') return { status: 200, body: ME }
  if (call.path === '/api/platform/gyms') return { status: 200, body: [LISTED] }
  if (call.path === `/api/platform/gyms/${GYM_ID}` && call.method === 'GET') return { status: 200, body: detail() }
  if (call.path === '/api/platform/slug') {
    return { status: 200, body: slugCheck(new URLSearchParams(call.query).get('slug')!) }
  }
  return { status: 404 }
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

describe('/plataforma/$gymId', () => {
  it('is opened from the list of gyms', async () => {
    stubApi(() => undefined)
    const router = renderAt('/plataforma')

    await userEvent.click(await screen.findByRole('link', { name: 'Gimnasio Norte' }))

    await screen.findByRole('heading', { name: 'Gimnasio Norte' })
    expect(router.state.location.pathname).toBe(`/plataforma/${GYM_ID}`)
    expect(screen.getByText(copy.titularNote)).toBeInTheDocument()
  })

  it('sends only what changed, and says it was saved', async () => {
    const calls = stubApi((call) =>
      call.method === 'PATCH' ? { status: 200, body: { fields: ['name', 'owner_phone'] } } : undefined,
    )
    renderAt(`/plataforma/${GYM_ID}`)

    const name = await screen.findByLabelText(copy.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'Gimnasio Sur')
    const phone = screen.getByLabelText(copy.ownerPhone)
    await userEvent.clear(phone)
    await userEvent.type(phone, '+56 9 2222 2222')
    await userEvent.click(screen.getByRole('button', { name: copy.save }))

    expect(await screen.findByText(copy.saved)).toBeInTheDocument()
    const [sent] = calls.filter((c) => c.method === 'PATCH')
    expect(sent!.path).toBe(`/api/platform/gyms/${GYM_ID}`)
    expect(sent!.body).toEqual({ name: 'Gimnasio Sur', owner_phone: '+56 9 2222 2222' })
  })

  it('keeps the email once the titular signed in, and says why a change was refused', async () => {
    stubApi((call) => {
      if (call.path === `/api/platform/gyms/${GYM_ID}` && call.method === 'GET') {
        return { status: 200, body: detail({ titular_signed_in: true }) }
      }
      if (call.method === 'PATCH') return { status: 409, body: { detail: { code: 'titular_handover', issue: 321 } } }
      return undefined
    })
    renderAt(`/plataforma/${GYM_ID}`)

    const email = await screen.findByLabelText(copy.ownerEmail)
    expect(email).toHaveAttribute('readonly')
    expect(screen.getByText(copy.ownerEmailLocked)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(copy.ownerName), ' Pérez')
    await userEvent.click(screen.getByRole('button', { name: copy.save }))
    expect(await screen.findByText(copy.handover)).toBeInTheDocument()
  })

  it('records a signature of the terms, or says that version was signed', async () => {
    let recorded = true
    const calls = stubApi((call) =>
      call.path.endsWith('/terms') ? { status: 200, body: { recorded } } : undefined,
    )
    renderAt(`/plataforma/${GYM_ID}`)

    expect(await screen.findByText(/2026-11-18, firmado el/)).toBeInTheDocument()
    expect(screen.getByText(copy.recordVersion('2026-11-18'))).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(copy.signedOn), '2026-11-20')
    await userEvent.click(screen.getByRole('button', { name: copy.record }))
    expect(await screen.findByText(copy.recorded)).toBeInTheDocument()
    expect(calls.filter((c) => c.path.endsWith('/terms')).map((c) => c.body)).toEqual([{ signed_on: '2026-11-20' }])

    recorded = false
    await userEvent.click(screen.getByRole('button', { name: copy.record }))
    expect(await screen.findByText(copy.alreadySigned)).toBeInTheDocument()
  })

  it('renames only once the new address is typed again, and says what changes', async () => {
    const calls = stubApi((call) =>
      call.path === RENAME
        ? {
            status: 200,
            body: { slug: 'sur', address: 'https://sur.rakin.app', old_slug: 'norte', until: '2027-02-16T12:00:00Z' },
          }
        : undefined,
    )
    renderAt(`/plataforma/${GYM_ID}`)

    const slug = await screen.findByLabelText(copy.newSlug)
    await userEvent.type(slug, 'meta')
    expect(await screen.findByText(copy.problems.taken)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.rename })).toBeDisabled()
    // Checked for this gym: a slug it had itself is not taken.
    expect(calls.find((c) => c.path === '/api/platform/slug')!.query).toBe(`?slug=meta&gym=${GYM_ID}`)

    await userEvent.clear(slug)
    await userEvent.type(slug, 'sur')
    expect(await screen.findByText(copy.willBe('https://sur.rakin.app'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.rename }))

    const dialog = screen.getByRole('dialog', { name: copy.confirmTitle })
    expect(within(dialog).getByText(copy.confirmMove('norte.rakin.app', 'sur.rakin.app'))).toBeInTheDocument()
    expect(within(dialog).getByText(copy.confirmRedirect('norte.rakin.app'))).toBeInTheDocument()
    expect(within(dialog).getByText(copy.confirmSessions)).toBeInTheDocument()
    const confirm = within(dialog).getByRole('button', { name: copy.confirm })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(copy.confirmType), 'su')
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(copy.confirmType), 'r')
    await userEvent.click(confirm)

    expect(await screen.findByText(copy.renamed('sur.rakin.app'))).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path === RENAME).map((c) => c.body)).toEqual([{ slug: 'sur' }])
  })

  it('asks a stale session for a code, then renames, without signing out', async () => {
    let fresh = false
    const calls = stubApi((call) => {
      if (call.path === RENAME) {
        return fresh
          ? {
              status: 200,
              body: { slug: 'sur', address: 'https://sur.rakin.app', old_slug: 'norte', until: '2027-02-16T12:00:00Z' },
            }
          : { status: 401, body: { detail: { code: 'reauth' } } }
      }
      if (call.path === '/api/platform/reauth/send') return { status: 202 }
      if (call.path === '/api/platform/reauth') {
        if ((call.body as { code: string }).code !== '123456') return { status: 400, body: { detail: 'invalid code' } }
        fresh = true
        return { status: 204 }
      }
      return undefined
    })
    const router = renderAt(`/plataforma/${GYM_ID}`)

    await userEvent.type(await screen.findByLabelText(copy.newSlug), 'sur')
    await screen.findByText(copy.willBe('https://sur.rakin.app'))
    await userEvent.click(screen.getByRole('button', { name: copy.rename }))
    await userEvent.type(screen.getByLabelText(copy.confirmType), 'sur')
    await userEvent.click(screen.getByRole('button', { name: copy.confirm }))

    const prompt = await screen.findByRole('dialog', { name: reauthCopy.title })
    expect(await within(prompt).findByText(reauthCopy.sent(ME.email))).toBeInTheDocument()
    // Still on the gym: a `reauth` is no sign-out.
    expect(router.state.location.pathname).toBe(`/plataforma/${GYM_ID}`)
    expect(calls.filter((c) => c.path === '/api/platform/reauth/send')).toHaveLength(1)

    await userEvent.type(within(prompt).getByLabelText(reauthCopy.codeLabel), '000000')
    await userEvent.click(within(prompt).getByRole('button', { name: reauthCopy.submit }))
    expect(await within(prompt).findByText(reauthCopy.invalid)).toBeInTheDocument()

    await userEvent.clear(within(prompt).getByLabelText(reauthCopy.codeLabel))
    await userEvent.type(within(prompt).getByLabelText(reauthCopy.codeLabel), '123 456')
    await userEvent.click(within(prompt).getByRole('button', { name: reauthCopy.submit }))

    expect(await screen.findByText(copy.renamed('sur.rakin.app'))).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(calls.filter((c) => c.path === RENAME)).toHaveLength(2)
    expect(router.state.location.pathname).toBe(`/plataforma/${GYM_ID}`)
  })
})
