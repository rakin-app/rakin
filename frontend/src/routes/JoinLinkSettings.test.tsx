import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { JoinLink } from '../api/join'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.joinLink

const LINK: JoinLink = {
  url: 'https://rakin.cl/unirse/primero-0123456789abcdef',
  token: 'primero-0123456789abcdef',
  program_id: null,
  program_name: null,
  expires_on: null,
  expired: false,
  created_at: '2026-11-10T12:00:00Z',
}

type Call = { method: string; path: string; body: unknown }

const PRIVACY = {
  legal_name: 'Academia Sur SpA',
  rut: '76432109-K',
  email: 'privacidad@academiasur.example.com',
  address: null,
  updated_on: '2026-11-10',
}

function stubApi(initial: JoinLink | null = null, { privacy = true }: { privacy?: boolean } = {}) {
  const calls: Call[] = []
  let link = initial
  let tokens = 0
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname, body })
      let answer: { status?: number; body?: unknown } = { status: 404, body: { detail: 'Not Found' } }
      if (url.pathname === '/api/me/role') answer = { body: { role: 'owner', person_id: 'me' } }
      if (url.pathname === '/api/programs') answer = { body: [{ id: 'kids', name: 'Kids', active: true }] }
      if (url.pathname === '/api/gym/settings') {
        answer = { body: { name: 'Academia Sur', privacy: privacy ? PRIVACY : null } }
      }
      if (url.pathname === '/api/join-link') {
        if (method === 'GET') answer = link ? { body: link } : { status: 404, body: { detail: 'no join link' } }
        if (method === 'POST' && !privacy) answer = { status: 409, body: { detail: 'privacy_incomplete' } }
        else if (method === 'POST') {
          tokens += 1
          const token = `nuevo${tokens}-0123456789abcdef`
          link = { ...LINK, ...body, token, url: `https://rakin.cl/unirse/${token}` }
          answer = { status: 201, body: link }
        }
        if (method === 'PATCH') {
          link = { ...link!, ...body }
          answer = { body: link }
        }
        if (method === 'DELETE') {
          link = null
          answer = { status: 204 }
        }
      }
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

async function section() {
  return screen.findByRole('region', { name: copy.title })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Inscripción', () => {
  it('generates a link for a program', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/inscripcion')

    const here = await section()
    expect(within(here).getByText(copy.none)).toBeInTheDocument()
    await within(here).findByRole('option', { name: 'Kids' })
    await userEvent.selectOptions(within(here).getByLabelText(copy.program), 'kids')
    await userEvent.click(within(here).getByRole('button', { name: copy.generate }))

    expect(await within(here).findByLabelText(copy.linkLabel)).toHaveValue('https://rakin.cl/unirse/nuevo1-0123456789abcdef')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ program_id: 'kids', expires_on: null })
  })

  it('shares the link by WhatsApp with the gym’s name', async () => {
    stubApi(LINK)
    renderAt('/admin/ajustes/inscripcion')

    const share = await within(await section()).findByRole('link', { name: copy.share })
    await vi.waitFor(() =>
      expect(share).toHaveAttribute(
        'href',
        `https://wa.me/?text=${encodeURIComponent(copy.shareText('Academia Sur', LINK.url))}`,
      ),
    )
  })

  it('generates another link once confirmed, and the old one is gone', async () => {
    const calls = stubApi(LINK)
    renderAt('/admin/ajustes/inscripcion')

    const here = await section()
    await userEvent.click(await within(here).findByRole('button', { name: copy.regenerate }))
    expect(within(here).getByText(copy.confirmRegenerate)).toBeInTheDocument()
    await userEvent.click(within(here).getByRole('button', { name: copy.confirm }))

    expect(await within(here).findByRole('status')).toHaveTextContent(copy.regenerated)
    expect(within(here).getByLabelText(copy.linkLabel)).toHaveValue('https://rakin.cl/unirse/nuevo1-0123456789abcdef')
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('changes the last day without a new token', async () => {
    const calls = stubApi(LINK)
    renderAt('/admin/ajustes/inscripcion')

    const here = await section()
    const day = await within(here).findByLabelText(copy.expiresOn)
    await userEvent.type(day, '2026-12-31')
    await userEvent.click(within(here).getByRole('button', { name: copy.save }))

    expect(await within(here).findByRole('status')).toHaveTextContent(copy.saved)
    expect(within(here).getByText(copy.validUntil('31-12-2026'))).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ program_id: null, expires_on: '2026-12-31' })
  })

  it('turns the link off once confirmed', async () => {
    stubApi(LINK)
    renderAt('/admin/ajustes/inscripcion')

    const here = await section()
    await userEvent.click(await within(here).findByRole('button', { name: copy.revoke }))
    await userEvent.click(within(here).getByRole('button', { name: copy.confirm }))

    expect(await screen.findByText(copy.revoked)).toBeInTheDocument()
    expect(await screen.findByText(copy.none)).toBeInTheDocument()
  })

  it('cannot generate a link until the privacy details are set, and says where to set them', async () => {
    const calls = stubApi(null, { privacy: false })
    renderAt('/admin/ajustes/inscripcion')

    const here = await section()
    expect(await within(here).findByRole('alert')).toHaveTextContent(copy.needsPrivacy)
    expect(within(here).getByRole('link', { name: copy.needsPrivacyLink })).toHaveAttribute(
      'href',
      '/admin/ajustes/gimnasio#privacidad',
    )
    expect(within(here).getByRole('button', { name: copy.generate })).toBeDisabled()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('says a link made before the privacy details does not work, and a new one is refused', async () => {
    stubApi(LINK, { privacy: false })
    renderAt('/admin/ajustes/inscripcion')

    const here = await section()
    expect(await within(here).findByRole('alert')).toHaveTextContent(copy.needsPrivacy)
    await userEvent.click(within(here).getByRole('button', { name: copy.regenerate }))
    await userEvent.click(within(here).getByRole('button', { name: copy.confirm }))

    await vi.waitFor(() => expect(within(here).getByRole('button', { name: copy.confirm })).toBeEnabled())
    expect(within(here).getAllByRole('alert')).toHaveLength(1)
    expect(within(here).getByLabelText(copy.linkLabel)).toHaveValue(LINK.url)
  })
})
