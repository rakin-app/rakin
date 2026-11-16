import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DependentConsent } from '../api/consent'
import { TEMPLATE_UPDATED_ON, type PrivacyNotice } from '../api/privacy'
import { createQueryClient } from '../api/queryClient'
import { es } from '../i18n/es'
import { MyConsents } from './MyConsents'

const copy = es.me.consent

const NOTICE: PrivacyNotice = {
  gym: 'Academia Sur',
  gym_logo: null,
  legal_name: 'Academia Sur SpA',
  rut: '76.123.456-7',
  email: 'datos@sur.cl',
  address: null,
  updated_on: '2026-11-09',
  human_check: false,
}

type Sent = { method: string; path: string; body: unknown }

function stubApi(
  consents: DependentConsent[],
  answer: (method: string) => { status: number; body: unknown } = (method) => ({
    status: 200,
    body: { ...consents[0]!, consent: method === 'POST' ? 'given' : 'withdrawn', at: '2026-11-16T15:00:00Z' },
  }),
) {
  const sent: Sent[] = []
  let current = consents
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      const method = init?.method ?? 'GET'
      sent.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (path === '/api/privacy') return Response.json(NOTICE)
      if (path === '/api/me/consents' && method === 'GET') return Response.json(current)
      const { status, body } = answer(method)
      if (status === 200) current = [body as DependentConsent]
      return Response.json(body, { status })
    }),
  )
  return sent
}

function renderConsents() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MyConsents />
    </QueryClientProvider>,
  )
}

const MATEO: DependentConsent = { id: 'mateo', name: 'Mateo Rojas', consent: 'missing', at: null }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Autorización de datos', () => {
  it('lets a guardian consent under the notice as it is now, then withdraw it', async () => {
    const sent = stubApi([MATEO])
    renderConsents()

    const row = await screen.findByRole('listitem', { name: 'Mateo Rojas' })
    expect(within(row).getByRole('status')).toHaveTextContent(copy.missing)
    expect(screen.getByRole('link', { name: copy.link })).toHaveAttribute('href', '/privacidad')
    await userEvent.click(await within(row).findByRole('button', { name: copy.give }))

    expect(await within(row).findByText(copy.given('16-11-2026'))).toBeInTheDocument()
    expect(sent.find((s) => s.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/me/consents/mateo',
      body: { template_on: TEMPLATE_UPDATED_ON, details_on: '2026-11-09' },
    })

    await userEvent.click(within(row).getByRole('button', { name: copy.withdraw }))
    expect(await within(row).findByText(copy.withdrawn('16-11-2026'))).toBeInTheDocument()
    expect(sent.at(-2)).toMatchObject({ method: 'DELETE', path: '/api/me/consents/mateo' })
  })

  it('says when the notice changed meanwhile, and loads it again', async () => {
    const sent = stubApi([MATEO], () => ({ status: 409, body: { detail: 'stale_notice' } }))
    renderConsents()

    const row = await screen.findByRole('listitem', { name: 'Mateo Rojas' })
    await userEvent.click(await within(row).findByRole('button', { name: copy.give }))

    expect(await within(row).findByRole('alert')).toHaveTextContent(copy.stale)
    await vi.waitFor(() => expect(sent.filter((s) => s.path === '/api/privacy')).toHaveLength(2))
  })

  it('shows nothing to someone with no minor in their care', async () => {
    const sent = stubApi([])
    renderConsents()

    await vi.waitFor(() => expect(sent).toHaveLength(1))
    expect(screen.queryByText(copy.title)).not.toBeInTheDocument()
  })
})
