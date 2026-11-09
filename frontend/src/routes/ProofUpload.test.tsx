import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OpenPeriod } from '../api/proofs'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.me.proof

const ANA: OpenPeriod = {
  id: 'p-ana',
  membership_id: 'm-ana',
  person_id: 'ana',
  person_name: 'Ana Rojas',
  plan_name: 'Mensual',
  period_start: '2026-11-01',
  period_end: '2026-11-30',
  due_date: '2026-11-05',
  amount_due_clp: 45000,
  paid_clp: 0,
  outstanding_clp: 45000,
  pending_clp: 0,
}
const JUAN: OpenPeriod = {
  ...ANA,
  id: 'p-juan',
  person_id: 'juan',
  person_name: 'Juan Rojas',
  plan_name: 'Kids',
  outstanding_clp: 25000,
  pending_clp: 25000,
}

const UPLOAD_URL = 'http://storage.test/rakin/proofs/key?X-Amz-Signature=abc'

type Call = { method: string; url: string; body: unknown; headers: Headers }
type Answer = { status?: number; body?: unknown }

function stubApi(
  periods: OpenPeriod[],
  answers: { put?: number; claim?: Answer; pending?: Answer; role?: string | null } = {},
) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, url: url.href, body, headers: new Headers(init?.headers) })
      const answer = route(url, method)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(url: URL, method: string): Answer {
    if (url.href === UPLOAD_URL && method === 'PUT') return { status: answers.put ?? 200 }
    if (url.pathname === '/api/me/periods') return { body: periods }
    if (url.pathname === '/api/me/proofs') {
      return { status: 201, body: { key: 'proofs/g/ana/k', url: UPLOAD_URL, headers: { 'Content-Type': 'image/jpeg' }, expires_in_seconds: 900 } }
    }
    if (url.pathname === '/api/me/payments') return answers.claim ?? { status: 201, body: {} }
    if (url.pathname === '/api/ledger/pending') return answers.pending ?? { body: { count: 0 } }
    if (url.pathname === '/api/me/role') return { body: { role: answers.role === undefined ? 'owner' : answers.role } }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

const photo = () => new File([new Uint8Array(2048)], 'transferencia.jpg', { type: 'image/jpeg' })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Subir comprobante', () => {
  it('uploads the file straight to storage, then claims the period', async () => {
    const calls = stubApi([ANA])
    renderAt('/me')

    await screen.findByRole('heading', { name: copy.title })
    expect(screen.getByLabelText(copy.amountLabel)).toHaveValue('45000')
    await userEvent.upload(screen.getByLabelText(copy.choose), photo())
    expect(screen.getByText(copy.chosen('transferencia.jpg'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.sent)
    const writes = calls.filter((c) => c.method !== 'GET')
    expect(writes.map((c) => [c.method, c.url])).toEqual([
      ['POST', 'http://localhost/api/me/proofs'],
      ['PUT', UPLOAD_URL],
      ['POST', 'http://localhost/api/me/payments'],
    ])
    expect(writes[0]!.body).toEqual({ content_type: 'image/jpeg', size_bytes: 2048 })
    expect(writes[1]!.body).toBeInstanceOf(File)
    expect(writes[1]!.headers.get('Content-Type')).toBe('image/jpeg')
    expect(writes[2]!.body).toEqual({ billing_period_id: 'p-ana', amount_clp: 45000, proof_key: 'proofs/g/ana/k' })
  })

  it('offers the camera on a phone', async () => {
    stubApi([ANA])
    renderAt('/me')

    const camera = await screen.findByLabelText(copy.camera)
    expect(camera).toHaveAttribute('capture', 'environment')
    expect(camera).toHaveAttribute('accept', 'image/*')
  })

  it("pays a dependent's period, with what is already in review", async () => {
    const calls = stubApi([ANA, JUAN])
    renderAt('/me')

    const juan = await screen.findByRole('radio', { name: /Juan Rojas/ })
    expect(screen.getByText(copy.inReview('$25.000'))).toBeInTheDocument()
    await userEvent.click(juan)
    expect(screen.getByLabelText(copy.amountLabel)).toHaveValue('25000')
    await userEvent.clear(screen.getByLabelText(copy.amountLabel))
    await userEvent.type(screen.getByLabelText(copy.amountLabel), '20000')
    await userEvent.upload(screen.getByLabelText(copy.camera), photo())
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    await screen.findByRole('status')
    const claim = calls.find((c) => c.url.endsWith('/api/me/payments'))
    expect(claim?.body).toMatchObject({ billing_period_id: 'p-juan', amount_clp: 20000 })
  })

  it.each([
    ['a file of another type', new File(['<svg/>'], 'x.svg', { type: 'image/svg+xml' }), copy.problem.type],
    ['a file over 10 MB', new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.pdf', { type: 'application/pdf' }), copy.problem.size],
  ])('refuses %s before sending anything', async (_, file, message) => {
    const calls = stubApi([ANA])
    renderAt('/me')

    await userEvent.upload(await screen.findByLabelText(copy.choose), file, { applyAccept: false })

    expect(screen.getByRole('alert')).toHaveTextContent(message)
    expect(screen.getByRole('button', { name: copy.submit })).toBeDisabled()
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
  })

  it('says so when the storage refuses the upload, and claims nothing', async () => {
    const calls = stubApi([ANA], { put: 403 })
    renderAt('/me')

    await userEvent.upload(await screen.findByLabelText(copy.choose), photo())
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.refused.upload)
    expect(calls.some((c) => c.url.endsWith('/api/me/payments'))).toBe(false)
  })

  it('says so when the period was paid meanwhile', async () => {
    stubApi([ANA], { claim: { status: 409, body: { detail: 'paid' } } })
    renderAt('/me')

    await userEvent.upload(await screen.findByLabelText(copy.choose), photo())
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.refused.paid)
  })

  it('uploads a HEIC the picker gave no type as image/heic', async () => {
    const calls = stubApi([ANA])
    renderAt('/me')
    const heic = new File([new Uint8Array(512)], 'IMG_0042.HEIC', { type: '' })

    await userEvent.upload(await screen.findByLabelText(copy.choose), heic)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    await screen.findByRole('status')
    expect(calls.find((c) => c.url.endsWith('/api/me/proofs'))?.body).toEqual({
      content_type: 'image/heic',
      size_bytes: 512,
    })
  })

  it('refuses a file with no type and no known extension', async () => {
    const calls = stubApi([ANA])
    renderAt('/me')

    await userEvent.upload(await screen.findByLabelText(copy.choose), new File(['x'], 'notes', { type: '' }), {
      applyAccept: false,
    })

    expect(screen.getByRole('alert')).toHaveTextContent(copy.problem.type)
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
  })

  it('has nothing to pay', async () => {
    stubApi([])
    renderAt('/me')

    expect(await screen.findByText(copy.none)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.submit })).not.toBeInTheDocument()
  })
})

describe('pending badge', () => {
  it('shows how many proofs wait for review on Pagos', async () => {
    stubApi([], { pending: { body: { count: 3 } } })
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    const payments = within(nav).getByRole('link', { name: new RegExp(es.nav.payments) })
    expect(await within(payments).findByText(es.nav.pendingBadge(3))).toBeInTheDocument()
    expect(within(payments).getByText('3')).toBeInTheDocument()
  })

  it('shows nothing when none are pending', async () => {
    const calls = stubApi([], { pending: { body: { count: 0 } }, role: 'admin' })
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith('/api/ledger/pending'))).toBe(true))
    expect(within(nav).getByRole('link', { name: es.nav.payments })).toHaveTextContent(/^Pagos$/)
  })

  it.each([['coach'], [null]])('never asks for the count as %s, who cannot read the ledger', async (role) => {
    const calls = stubApi([], { pending: { body: { count: 3 } }, role })
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith('/api/me/role'))).toBe(true))
    // Give a mistaken request the chance to land before checking none did.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(calls.some((c) => c.url.endsWith('/api/ledger/pending'))).toBe(false)
    expect(within(nav).getByRole('link', { name: es.nav.payments })).toHaveTextContent(/^Pagos$/)
  })
})
