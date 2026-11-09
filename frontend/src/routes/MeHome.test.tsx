import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BankAccount, MyPage, MyPayment } from '../api/me'
import type { OpenPeriod } from '../api/proofs'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.me
const YEAR = new Date().getFullYear()

const BANK: BankAccount = {
  bank: 'Banco Estado',
  account_type: 'Cuenta Vista',
  holder: 'Academia Sur SpA',
  rut: '76432109-K',
  number: '000012348821',
  email: 'pagos@academiasur.example.com',
}

const NOVEMBER: OpenPeriod = {
  id: 'p-nov',
  membership_id: 'm-diego',
  person_id: 'diego',
  person_name: 'Diego Morales',
  plan_name: 'Mensual adultos',
  period_start: `${YEAR}-11-10`,
  period_end: `${YEAR}-12-09`,
  due_date: `${YEAR}-11-10`,
  amount_due_clp: 45000,
  paid_clp: 0,
  outstanding_clp: 45000,
  pending_clp: 45000,
}

const payment = (over: Partial<MyPayment>): MyPayment => ({
  id: 'e-1',
  person_id: 'diego',
  person_name: 'Diego Morales',
  amount_clp: 45000,
  status: 'validated',
  period_start: `${YEAR}-10-10`,
  claimed_at: '2026-10-07T20:00:00Z',
  validated_at: '2026-10-08T15:00:00Z',
  note: null,
  created_at: '2026-10-07T20:00:00Z',
  ...over,
})

function diego(over: Partial<MyPage> = {}): MyPage {
  return {
    gym_name: 'Academia Sur',
    timezone: 'America/Santiago',
    person_id: 'diego',
    name: 'Diego Morales',
    next_payment: { period: NOVEMBER, status: 'in_review' },
    bank_account: BANK,
    payments: [
      payment({ id: 'e-nov', status: 'pending', period_start: NOVEMBER.period_start, claimed_at: new Date().toISOString(), validated_at: null }),
      payment({ id: 'e-oct' }),
      payment({ id: 'e-old', period_start: `${YEAR - 1}-09-10`, validated_at: '2025-09-09T15:00:00Z' }),
    ],
    ...over,
  }
}

function stubPage(answer: MyPage | { status: number }) {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/me/page') {
        if ('status' in answer) return new Response('{}', { status: answer.status })
        return Response.json(answer)
      }
      if (url.pathname === '/api/me/periods') return Response.json([NOVEMBER])
      return Response.json({ detail: 'Not Found' }, { status: 404 })
    }),
  )
}

function renderMe() {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/me'] }))
  render(<App queryClient={queryClient} router={router} />)
}

const nextCard = () => screen.getByRole('region', { name: copy.next.title })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Mi página', () => {
  it('greets the student by first name, under the gym', async () => {
    stubPage(diego())
    renderMe()

    expect(await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })).toBeInTheDocument()
    expect(screen.getByText('Academia Sur')).toBeInTheDocument()
    expect(screen.getByText(copy.home.signedIn)).toBeInTheDocument()
  })

  it('shows the next payment with its proof in review, and where to transfer', async () => {
    stubPage(diego())
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    const card = within(nextCard())
    expect(card.getByText(copy.next.status.in_review)).toBeInTheDocument()
    expect(card.getByText('$45.000')).toBeInTheDocument()
    expect(card.getByText('vence el 10 de noviembre')).toBeInTheDocument()
    // Masked, as the design shows them.
    expect(card.getByText('Banco Estado · Cta. Vista')).toBeInTheDocument()
    expect(card.getByText('Academia Sur SpA')).toBeInTheDocument()
    expect(card.getByText('76.•••.•••-K')).toBeInTheDocument()
    expect(card.getByText('•••• 8821')).toBeInTheDocument()
  })

  it.each([
    ['overdue', copy.next.status.overdue],
    ['due', copy.next.status.due],
  ] as const)('marks a %s payment', async (status, label) => {
    stubPage(diego({ next_payment: { period: { ...NOVEMBER, pending_clp: 0 }, status } }))
    renderMe()

    expect(await within(await screen.findByRole('region', { name: copy.next.title })).findByText(label)).toBeInTheDocument()
  })

  it('copies the bank details in full', async () => {
    const user = userEvent.setup()
    stubPage(diego())
    renderMe()

    await user.click(await screen.findByRole('button', { name: copy.next.copy }))

    expect(await navigator.clipboard.readText()).toBe(
      [
        'Academia Sur SpA',
        'RUT 76.432.109-K',
        'Banco Estado',
        'Cuenta Vista',
        'N.º 000012348821',
        'pagos@academiasur.example.com',
      ].join('\n'),
    )
    expect(screen.getByRole('button', { name: copy.next.copied })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(copy.next.copied)
  })

  it('says so when the copy fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'))
    stubPage(diego())
    renderMe()

    await user.click(await screen.findByRole('button', { name: copy.next.copy }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.next.copyFailed)
  })

  it('opens the proof upload from the card', async () => {
    stubPage(diego())
    renderMe()

    const upload = await screen.findByRole('button', { name: copy.next.upload })
    expect(upload).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('heading', { name: copy.proof.title })).not.toBeInTheDocument()
    await userEvent.click(upload)

    expect(upload).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByRole('heading', { name: copy.proof.title })).toBeInTheDocument()
  })

  it('still offers the upload when the gym has no bank details yet', async () => {
    stubPage(diego({ bank_account: null }))
    renderMe()

    expect(await screen.findByText(copy.next.noBank)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.next.copy })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.next.upload })).toBeInTheDocument()
  })

  it('is paid up', async () => {
    stubPage(diego({ next_payment: null }))
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    const card = within(nextCard())
    expect(card.getByText(copy.next.status.paid)).toBeInTheDocument()
    expect(card.getByText(copy.next.paidUp)).toBeInTheDocument()
    expect(card.queryByRole('button')).not.toBeInTheDocument()
  })

  it("names the dependent a guardian's next payment is for", async () => {
    const juan = { ...NOVEMBER, person_id: 'juan', person_name: 'Juan', pending_clp: 0 }
    stubPage(diego({ next_payment: { period: juan, status: 'due' } }))
    renderMe()

    expect(await screen.findByText('vence el 10 de noviembre · de Juan')).toBeInTheDocument()
  })

  it('lists the payments with how each was reviewed', async () => {
    stubPage(diego())
    renderMe()

    const history = within(await screen.findByRole('region', { name: copy.history.title }))
    const rows = history.getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringMatching(/^Noviembrecomprobante enviado hoy \d{2}:\d{2}En revisión$/),
      'Octubrevalidado 8 oct$45.000',
      `Septiembre ${YEAR - 1}validado 9 sep$45.000`,
    ])
  })

  it("shows a rejection's note, and whose payment it was", async () => {
    stubPage(
      diego({
        payments: [
          payment({ status: 'rejected', note: 'falta $5.000' }),
          payment({ id: 'e-juan', person_id: 'juan', person_name: 'Juan' }),
        ],
      }),
    )
    renderMe()

    const history = within(await screen.findByRole('region', { name: copy.history.title }))
    expect(history.getByText('rechazado 8 oct: falta $5.000')).toBeInTheDocument()
    expect(history.getByText(copy.history.status.rejected)).toBeInTheDocument()
    expect(history.getByText('Octubre · Juan')).toBeInTheDocument()
  })

  it('has no payments yet', async () => {
    stubPage(diego({ payments: [] }))
    renderMe()

    expect(await screen.findByText(copy.history.empty)).toBeInTheDocument()
  })

  it('says so when the page cannot load, and retries', async () => {
    stubPage({ status: 500 })
    renderMe()

    expect(await screen.findByRole('alert', {}, { timeout: 5000 })).toHaveTextContent(copy.home.error)
    stubPage(diego())
    await userEvent.click(screen.getByRole('button', { name: copy.home.retry }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })).toBeInTheDocument()
  })
})
