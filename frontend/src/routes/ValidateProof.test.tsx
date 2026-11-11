import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { ProofReview } from '../api/review'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.review

const DIEGO: ProofReview = {
  id: 'e-diego',
  membership_id: 'm-diego',
  person_id: 'diego',
  person_name: 'Diego Morales',
  amount_clp: 45000,
  method: 'transfer',
  claimed_at: '2026-11-08T17:12:00Z',
  claimed_by_name: 'Diego Morales',
  proof_url: '/api/blobs/proofs/g/diego/k?sig=x',
  proof_content_type: 'image/jpeg',
  plan_name: 'Mensual adultos',
  plan_kind: 'monthly',
  anchor_day: 10,
  period: {
    id: 'p-diego',
    period_start: '2026-11-10',
    period_end: '2026-12-09',
    due_date: '2026-11-10',
    amount_due_clp: 45000,
    paid_clp: 0,
    outstanding_clp: 45000,
  },
  prior_balance_clp: 0,
  last_payments: [
    { amount_clp: 45000, paid_at: '2026-10-08T15:00:00Z' },
    { amount_clp: 45000, paid_at: '2026-09-09T15:00:00Z' },
  ],
  attendance_30d: 9,
}

const JUAN: ProofReview = {
  ...DIEGO,
  id: 'e-juan',
  person_id: 'juan',
  person_name: 'Juan Rojas',
  claimed_by_name: 'Marta Rojas',
  amount_clp: 20000,
  proof_content_type: 'application/pdf',
  anchor_day: null,
  plan_name: 'Kids',
  period: { ...DIEGO.period!, id: 'p-juan', amount_due_clp: 25000, outstanding_clp: 25000 },
  last_payments: [],
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi(
  initial: ProofReview[],
  answers: { validate?: Answer; reject?: Answer; reminders?: unknown[] } = {},
) {
  let queue = [...initial]
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      calls.push({ method, path: url.pathname, body: typeof raw === 'string' ? JSON.parse(raw) : raw })
      const answer = route(url.pathname, method)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string): Answer {
    if (path === '/api/me/role') return { body: { role: 'owner' } }
    if (path === '/api/ledger/pending') return { body: { count: queue.length } }
    if (path === '/api/ledger/proofs') return { body: queue }
    if (path === '/api/reminders') return { body: answers.reminders ?? [] }
    if (path.startsWith('/api/reminders/') && method === 'POST') return { status: 201, body: {} }
    const action = /^\/api\/ledger\/proofs\/([^/]+)\/(validate|reject)$/.exec(path)
    if (action && method === 'POST') {
      const answer = answers[action[2] as 'validate' | 'reject']
      if (answer && (answer.status ?? 200) >= 400) return answer
      queue = queue.filter((item) => item.id !== action[1])
      return answer ?? { body: { credit: null, period: { outstanding_clp: 0, closed: true } } }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

const PATH = '/admin/pagos/comprobantes'
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Validar comprobante', () => {
  it('shows the claim beside the open period, with the proof and the history', async () => {
    stubApi([DIEGO, JUAN])
    renderAt(PATH)

    expect(await screen.findByRole('heading', { name: 'Diego Morales' })).toBeInTheDocument()
    expect(screen.getByText(copy.position(1, 2))).toBeInTheDocument()
    const figures = screen.getByRole('region', { name: copy.claimLabel })
    expect(within(figures).getAllByText('$45.000')).toHaveLength(2)
    expect(within(figures).getByText(/transferencia/)).toBeInTheDocument()
    expect(within(figures).getByText('noviembre · vence 10 nov')).toBeInTheDocument()
    expect(screen.getByText(copy.match.matches)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: copy.proofLabel('Diego Morales') })).toHaveAttribute('src', DIEGO.proof_url)
    expect(screen.getByText(copy.sentByStudent)).toBeInTheDocument()
    expect(screen.getByText('Mensual adultos · día 10')).toBeInTheDocument()
    expect(screen.getByText('$0')).toBeInTheDocument()
    expect(screen.getByText('8 oct · 9 sept')).toBeInTheDocument()
    expect(screen.getByText(copy.attendanceCount(9))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.confirm('$45.000') })).toBeInTheDocument()
  })

  it('shows a cobro extra\'s proof against what its line owes, with no plan or history', async () => {
    const rifa: ProofReview = {
      ...DIEGO,
      id: 'e-rifa',
      membership_id: null,
      amount_clp: 10000,
      plan_name: null,
      plan_kind: null,
      anchor_day: null,
      period: null,
      extra_line: {
        id: 'l-rifa',
        extra_charge_id: 'x-rifa',
        title: 'Rifa de fin de año',
        category: 'rifa',
        due_date: '2026-11-30',
        amount_due_clp: 10000,
        paid_clp: 0,
        outstanding_clp: 10000,
      },
      prior_balance_clp: 0,
      last_payments: [],
    }
    stubApi([rifa])
    renderAt(PATH)

    const figures = await screen.findByRole('region', { name: copy.claimLabel })
    expect(within(figures).getAllByText('$10.000')).toHaveLength(2)
    expect(within(figures).getByText(copy.extraDue('Rifa', '30 nov'))).toBeInTheDocument()
    expect(screen.getByText(copy.match.matches)).toBeInTheDocument()
    expect(screen.getByText('Rifa de fin de año')).toBeInTheDocument()
    expect(screen.queryByText(copy.priorBalance)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.confirm('$10.000') })).toBeInTheDocument()
  })

  it('pages through the queue', async () => {
    const user = userEvent.setup()
    stubApi([DIEGO, JUAN])
    renderAt(PATH)
    await screen.findByRole('heading', { name: 'Diego Morales' })
    expect(screen.getByRole('button', { name: copy.previous })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: copy.next }))

    expect(screen.getByRole('heading', { name: 'Juan Rojas' })).toBeInTheDocument()
    expect(screen.getByText(copy.position(2, 2))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.next })).toBeDisabled()
    // Short of the period, a PDF sent by the guardian, no history.
    expect(screen.getByText(copy.match.short('$5.000'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: copy.openPdf })).toHaveAttribute('href', JUAN.proof_url)
    expect(screen.getByText(copy.sentBy('Marta Rojas'))).toBeInTheDocument()
    expect(screen.getByText('Kids')).toBeInTheDocument()
    expect(screen.getByText(copy.noPayments)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: copy.previous }))
    expect(screen.getByRole('heading', { name: 'Diego Morales' })).toBeInTheDocument()
  })

  it('confirms in one tap and moves on to the next proof', async () => {
    const user = userEvent.setup()
    const calls = stubApi([DIEGO, JUAN])
    renderAt(PATH)

    await user.click(await screen.findByRole('button', { name: copy.confirm('$45.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.validated('Diego Morales', '$45.000'))
    expect(await screen.findByRole('heading', { name: 'Juan Rojas' })).toBeInTheDocument()
    expect(screen.getByText(copy.position(1, 1))).toBeInTheDocument()
    expect(posts(calls)).toEqual([{ method: 'POST', path: '/api/ledger/proofs/e-diego/validate', body: undefined }])
  })

  it('says what an overpayment leaves in credit', async () => {
    const user = userEvent.setup()
    const over = { ...DIEGO, amount_clp: 55000 }
    stubApi([over], {
      validate: { body: { credit: { amount_clp: 10000, note: 'x' }, period: { outstanding_clp: 0, closed: true } } },
    })
    renderAt(PATH)
    expect(await screen.findByText(copy.match.over('$10.000'))).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: copy.confirm('$55.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      copy.validated('Diego Morales', '$55.000') + copy.credit('$10.000'),
    )
    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
  })

  it('needs a note to reject, and sends it', async () => {
    const user = userEvent.setup()
    const calls = stubApi([JUAN])
    renderAt(PATH)
    await screen.findByRole('heading', { name: 'Juan Rojas' })

    await user.click(screen.getByRole('button', { name: copy.reject }))

    expect(screen.getByRole('alert')).toHaveTextContent(copy.noteNeeded)
    const note = screen.getByLabelText(copy.noteLabel)
    expect(note).toHaveFocus()
    expect(posts(calls)).toEqual([])

    await user.type(note, '  falta $5.000 ')
    await user.click(screen.getByRole('button', { name: copy.reject }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.rejected('Marta Rojas'))
    expect(posts(calls)).toEqual([
      { method: 'POST', path: '/api/ledger/proofs/e-juan/reject', body: { note: 'falta $5.000' } },
    ])
    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
    // With no WhatsApp to send it on, the email is the follow-up.
    expect(screen.queryByRole('link', { name: /WhatsApp/ })).not.toBeInTheDocument()
  })

  it('offers the follow-up by WhatsApp after a rejection, and logs it as it opens', async () => {
    const user = userEvent.setup()
    const followUp = {
      billing_period_id: 'p-juan',
      person_id: 'juan',
      person_name: 'Juan Rojas',
      kind: 'proof_rejected_followup',
      rejection_note: 'falta $5.000',
      contact_name: 'Marta Rojas',
      whatsapp_url: 'https://wa.me/56912345678?text=Hola',
      reminders_sent: 0,
      reminded_at: null,
      reminder_due: true,
    }
    const calls = stubApi([JUAN], { reminders: [followUp] })
    renderAt(PATH)
    await screen.findByRole('heading', { name: 'Juan Rojas' })

    await user.type(screen.getByLabelText(copy.noteLabel), 'falta $5.000')
    await user.click(screen.getByRole('button', { name: copy.reject }))

    const link = await screen.findByRole('link', {
      name: es.admin.reminders.writeFor('Marta Rojas', 'Juan Rojas', '1.er'),
    })
    expect(link).toHaveTextContent(es.admin.reminders.followUp('Marta Rojas'))
    expect(link).toHaveAttribute('href', 'https://wa.me/56912345678?text=Hola')

    await user.click(link)

    await vi.waitFor(() => expect(posts(calls).map((c) => c.path)).toContain('/api/reminders/p-juan'))
  })

  it('explains a period paid meanwhile', async () => {
    const user = userEvent.setup()
    stubApi([DIEGO], { validate: { status: 409, body: { detail: 'billing period is already paid in full' } } })
    renderAt(PATH)

    await user.click(await screen.findByRole('button', { name: copy.confirm('$45.000') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.refused.paid)
    expect(screen.getByRole('heading', { name: 'Diego Morales' })).toBeInTheDocument()
  })

  it('zooms the proof and closes on Escape', async () => {
    const user = userEvent.setup()
    stubApi([DIEGO])
    renderAt(PATH)

    await user.click(await screen.findByRole('button', { name: copy.zoomLabel }))

    const dialog = screen.getByRole('dialog', { name: copy.proofLabel('Diego Morales') })
    expect(within(dialog).getByRole('button', { name: copy.close })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('leaves focus where it is while the zoomed proof stays open', async () => {
    const user = userEvent.setup()
    stubApi([DIEGO])
    renderAt(PATH)
    await user.click(await screen.findByRole('button', { name: copy.zoomLabel }))
    const dialog = screen.getByRole('dialog', { name: copy.proofLabel('Diego Morales') })

    // Typing a note re-renders the page beneath the zoom; focus must not jump back.
    const note = screen.getByLabelText(copy.noteLabel)
    note.focus()
    await user.keyboard('ilegible')

    expect(note).toHaveFocus()
    expect(dialog).toBeInTheDocument()
  })

  it('says when the proof file is missing', async () => {
    stubApi([{ ...DIEGO, proof_url: null, proof_content_type: null }])
    renderAt(PATH)

    expect(await screen.findByText(copy.missing)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.confirm('$45.000') })).toBeEnabled()
  })

  it('says when nothing waits for review', async () => {
    stubApi([])
    renderAt(PATH)

    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.reject })).not.toBeInTheDocument()
  })

  it('is reached from Pagos while proofs wait', async () => {
    const user = userEvent.setup()
    stubApi([DIEGO, JUAN])
    renderAt('/admin/pagos')

    await user.click(await screen.findByRole('link', { name: es.admin.payments.review(2) }))

    expect(await screen.findByRole('heading', { name: 'Diego Morales' })).toBeInTheDocument()
  })
})
