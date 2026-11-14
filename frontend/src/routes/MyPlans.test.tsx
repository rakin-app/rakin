import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FreezeRequest } from '../api/freezeRequests'
import type { MyPage, MyPlan } from '../api/me'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.me.plans

const PLAN: MyPlan = {
  membership_id: 'm-diego',
  person_id: 'diego',
  person_name: 'Diego Morales',
  plan_name: 'Mensual adultos',
  status: 'active',
  freeze: null,
  pending_request: null,
  last_decided: null,
}

const request = (over: Partial<FreezeRequest> = {}): FreezeRequest => ({
  id: 'fr-1',
  membership_id: 'm-diego',
  person_id: 'diego',
  person_name: 'Diego Morales',
  requested_by: 'diego',
  requested_by_name: 'Diego Morales',
  plan_name: 'Mensual adultos',
  from_date: '2099-11-20',
  to_date: '2099-12-04',
  reason: 'lesion',
  note: null,
  status: 'pending',
  decision_note: null,
  decided_at: null,
  created_at: '2026-11-13T12:00:00Z',
  ...over,
})

function page(plans: MyPlan[]): MyPage {
  return {
    gym_name: 'Academia Sur',
    timezone: 'America/Santiago',
    person_id: 'diego',
    name: 'Diego Morales',
    next_payment: null,
    bank_account: null,
    rank: null,
    attendance: { this_month: 0, total: 0 },
    payments: [],
    plans,
  }
}

type Call = { method: string; path: string; body: unknown }

/** The student page with `plans`; asking adds the request to the plan, withdrawing drops it. */
function stubApi(plans: MyPlan[], refuse?: { status: number; body: unknown }) {
  const calls: Call[] = []
  let current = plans
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: url.pathname, body })
      if (url.pathname === '/api/me/page') return Response.json(page(current))
      if (url.pathname === '/api/me/role') return Response.json({ role: null, person_id: 'diego', gym_name: 'Academia Sur' })
      if (url.pathname === '/api/me/time' || url.pathname === '/api/me/classes') {
        return Response.json({ detail: 'Not Found' }, { status: 404 })
      }
      if (url.pathname === '/api/me/freeze-requests' && method === 'POST') {
        if (refuse) return Response.json(refuse.body, { status: refuse.status })
        const made = request({ ...body, status: 'pending' })
        current = current.map((p) => (p.membership_id === body.membership_id ? { ...p, pending_request: made } : p))
        return Response.json(made, { status: 201 })
      }
      if (url.pathname.startsWith('/api/me/freeze-requests/') && method === 'DELETE') {
        current = current.map((p) => ({ ...p, pending_request: null }))
        return new Response(null, { status: 204 })
      }
      return Response.json({ detail: 'Not Found' }, { status: 404 })
    }),
  )
  return calls
}

function renderMe() {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/me'] }))
  render(<App queryClient={queryClient} router={router} />)
}

const plans = async () => within(await screen.findByRole('region', { name: copy.title }))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Mi plan: Pedir congelamiento (#270)', () => {
  it('asks for a freeze with its dates, reason and note, then shows it pending', async () => {
    const calls = stubApi([PLAN])
    renderMe()
    const section = await plans()

    await userEvent.click(section.getByRole('button', { name: copy.askLabel('Mensual adultos') }))
    const form = within(section.getByRole('form', { name: copy.formTitle }))
    await userEvent.clear(form.getByLabelText(copy.from))
    await userEvent.type(form.getByLabelText(copy.from), '2099-11-20')
    await userEvent.type(form.getByLabelText(copy.until), '2099-12-04')
    await userEvent.selectOptions(form.getByLabelText(copy.reason), 'lesion')
    await userEvent.type(form.getByLabelText(copy.note), 'Esguince de tobillo')
    await userEvent.click(form.getByRole('button', { name: copy.submit }))

    expect(await section.findByText(copy.pending)).toBeInTheDocument()
    expect(section.getByText(copy.pendingDates('20 de noviembre', '4 de diciembre'))).toBeInTheDocument()
    expect(section.queryByRole('button', { name: copy.askLabel('Mensual adultos') })).not.toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      membership_id: 'm-diego',
      from_date: '2099-11-20',
      to_date: '2099-12-04',
      reason: 'lesion',
      note: 'Esguince de tobillo',
    })
  })

  it('asks for the dates and a reason before sending, and a note for "Otro"', async () => {
    const calls = stubApi([PLAN])
    renderMe()
    const section = await plans()

    await userEvent.click(section.getByRole('button', { name: copy.askLabel('Mensual adultos') }))
    const form = within(section.getByRole('form', { name: copy.formTitle }))
    await userEvent.click(form.getByRole('button', { name: copy.submit }))
    expect(form.getByText(copy.untilNeeded)).toBeInTheDocument()
    expect(form.getByText(copy.reasonNeeded)).toBeInTheDocument()

    await userEvent.type(form.getByLabelText(copy.until), '2099-12-04')
    await userEvent.selectOptions(form.getByLabelText(copy.reason), 'otro')
    await userEvent.click(form.getByRole('button', { name: copy.submit }))
    expect(form.getByText(copy.noteNeeded)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('says why a request was refused', async () => {
    stubApi([PLAN], { status: 409, body: { detail: { code: 'has_pending' } } })
    renderMe()
    const section = await plans()

    await userEvent.click(section.getByRole('button', { name: copy.askLabel('Mensual adultos') }))
    const form = within(section.getByRole('form', { name: copy.formTitle }))
    await userEvent.type(form.getByLabelText(copy.until), '2099-12-04')
    await userEvent.selectOptions(form.getByLabelText(copy.reason), 'viaje')
    await userEvent.click(form.getByRole('button', { name: copy.submit }))

    expect(await form.findByRole('alert')).toHaveTextContent(copy.refused.has_pending)
  })

  it('withdraws a pending request with "Retirar"', async () => {
    const calls = stubApi([{ ...PLAN, pending_request: request() }])
    renderMe()
    const section = await plans()

    await userEvent.click(section.getByRole('button', { name: copy.withdrawLabel }))

    expect(await section.findByRole('button', { name: copy.askLabel('Mensual adultos') })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/api/me/freeze-requests/fr-1')
  })

  it("shows a rejection with the academy's note", async () => {
    stubApi([{ ...PLAN, last_decided: request({ status: 'rejected', decision_note: 'Conversemos primero' }) }])
    renderMe()
    const section = await plans()

    expect(section.getByText(copy.rejected('20 de noviembre', '4 de diciembre'))).toBeInTheDocument()
    expect(section.getByText(copy.rejectedNote('Conversemos primero'))).toBeInTheDocument()
    // The plan is still Active: they may ask again.
    expect(section.getByRole('button', { name: copy.askLabel('Mensual adultos') })).toBeInTheDocument()
  })

  it('shows an approved freeze running, with nothing to ask', async () => {
    const freeze = { id: 'f-1', from_date: '2026-11-10', to_date: '2099-12-04', reason: 'Lesión', started: true }
    stubApi([{ ...PLAN, status: 'frozen', freeze, last_decided: request({ status: 'approved' }) }])
    renderMe()
    const section = await plans()

    expect(section.getByText(copy.frozen('4 de diciembre'))).toBeInTheDocument()
    expect(section.getByText(copy.approved)).toBeInTheDocument()
    expect(section.queryByRole('button', { name: copy.askLabel('Mensual adultos') })).not.toBeInTheDocument()
  })

  it("names a dependent's plan, and leaves Retirar to whoever asked", async () => {
    stubApi([
      { ...PLAN, membership_id: 'm-juan', person_id: 'juan', person_name: 'Juan Morales', plan_name: 'Kids' },
      {
        ...PLAN,
        membership_id: 'm-sofia',
        person_id: 'sofia',
        person_name: 'Sofía Morales',
        plan_name: 'Juvenil',
        pending_request: request({ requested_by: 'sofia' }),
      },
    ])
    renderMe()
    const section = await plans()

    expect(section.getByText(`Kids · ${copy.theirs('Juan Morales')}`)).toBeInTheDocument()
    expect(section.getByText(copy.pending)).toBeInTheDocument()
    expect(section.queryByRole('button', { name: copy.withdrawLabel })).not.toBeInTheDocument()
  })

  it('is not there without a running plan', async () => {
    stubApi([])
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    expect(screen.queryByRole('region', { name: copy.title })).not.toBeInTheDocument()
  })
})
