import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ExtraCharge, ExtraChargeSummary, Line, Preview } from '../api/extraCharges'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.extra

const SUMMARY: ExtraChargeSummary = {
  id: 'x-final',
  title: 'Bencina final',
  category: 'gasto_compartido',
  due_date: '2026-11-30',
  amount_mode: 'split',
  amount_clp: 180000,
  target_kind: 'group',
  target_label: 'Clasificados final',
  created_at: '2026-11-11T12:00:00Z',
  lines: 9,
  paid_lines: 7,
  waived_lines: 0,
  due_clp: 180000,
  collected_clp: 140000,
}

function line(id: string, name: string, extra: Partial<Line> = {}): Line {
  return {
    id,
    person: { id: `p-${id}`, name },
    guardian: null,
    amount_due_clp: 20000,
    overridden: false,
    paid_clp: 0,
    outstanding_clp: 20000,
    pending_clp: 0,
    status: 'open',
    cancelled_at: null,
    has_email: true,
    whatsapp_url: null,
    pending_proof_id: null,
    refundable_payments: [],
    ...extra,
  }
}

const CHARGE: ExtraCharge = {
  ...SUMMARY,
  description: null,
  message: 'Nos vamos el sábado.',
  people: [
    line('ana', 'Ana Rojas', { whatsapp_url: 'https://wa.me/56911112222?text=x' }),
    line('bea', 'Bea Soto', { status: 'paid', paid_clp: 20000, outstanding_clp: 0 }),
    line('carla', 'Carla Díaz', { status: 'in_review', pending_clp: 20000, pending_proof_id: 'e-1' }),
  ],
}

const PREVIEW: Preview = {
  lines: [
    {
      person: { id: 'p-ana', name: 'Ana Rojas' },
      amount_clp: 33334,
      overridden: false,
      contact_name: 'Ana Rojas',
      on_behalf: false,
      has_email: true,
      whatsapp_url: null,
    },
    {
      person: { id: 'p-juan', name: 'Juan Pérez' },
      amount_clp: 33333,
      overridden: false,
      contact_name: 'Marta Pérez',
      on_behalf: true,
      has_email: false,
      whatsapp_url: 'https://wa.me/56933334444?text=y',
    },
    {
      person: { id: 'p-luis', name: 'Luis Mora' },
      amount_clp: 33333,
      overridden: false,
      contact_name: 'Luis Mora',
      on_behalf: false,
      has_email: true,
      whatsapp_url: null,
    },
  ],
  total_clp: 100000,
  remainder_clp: 1,
  share_clp: 33333,
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi(
  role: string,
  extra: (path: string, method: string, body: unknown) => Answer | Promise<Answer> | undefined = () => undefined,
) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: url.pathname + url.search, body })
      const answer = (await extra(url.pathname, method, body)) ?? base(url.pathname, method)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function base(path: string, method: string): Answer {
    if (path === '/api/me/role') return { body: { role, person_id: 'me', gym_name: 'Academia Sur' } }
    if (path === '/api/ledger/pending') return { body: { count: 0 } }
    if (path === '/api/extra-charges' && method === 'GET') return { body: [SUMMARY] }
    if (path === '/api/groups') return { body: [{ id: 'g-final', name: 'Clasificados final', size: 3 }] }
    if (path === '/api/programs') return { body: [{ id: 'pr-kids', name: 'Kids', active: true }] }
    if (path === '/api/plans') return { body: [] }
    if (path === `/api/extra-charges/${CHARGE.id}`) return { body: CHARGE }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Cobros extra', () => {
  it('lists each cobro with how far along it is', async () => {
    stubApi('owner')
    renderAt('/admin/pagos/cobros')

    const list = await screen.findByRole('list', { name: copy.listLabel })
    const row = within(list).getByRole('link', { name: /Bencina final/ })
    expect(row).toHaveTextContent('Gasto compartido · vence 30 nov')
    expect(row).toHaveTextContent(copy.progress(7, 9, '$140.000', '$180.000'))
    expect(within(row).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '7')
    expect(screen.getByText('Clasificados final')).toBeInTheDocument()
  })

  it('tells a coach it is not for them and asks the API nothing', async () => {
    const calls = stubApi('coach')
    renderAt('/admin/pagos/cobros')

    expect(await screen.findByText(es.admin.payments.coachesOnly)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/extra-charges'))).toBe(false)
    expect(calls.some((c) => c.path.startsWith('/api/groups'))).toBe(false)
  })

  it('saves a group from a filter and someone picked by hand', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path, method) => {
      if (path === '/api/people' && method === 'GET') {
        return {
          body: {
            items: [{ id: 'p-kid', name: 'Tomás Kid', membership: null }],
            total: 1,
          },
        }
      }
      if (path === '/api/groups' && method === 'POST') return { status: 201, body: { id: 'g-new', name: 'Kids final', members: [] } }
      return undefined
    })
    renderAt('/admin/pagos/cobros')

    await user.click(await screen.findByRole('button', { name: copy.groups.create }))
    await user.type(screen.getByLabelText(copy.groups.name), 'Kids final')
    await user.selectOptions(screen.getByLabelText(copy.groups.program), 'pr-kids')
    await user.click(await screen.findByRole('button', { name: copy.groups.addAll(1) }))
    expect(screen.getByText(copy.groups.members(1))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: copy.groups.save }))

    expect(await screen.findByText(copy.groups.saved('Kids final'))).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      { method: 'POST', path: '/api/groups', body: { name: 'Kids final', person_ids: ['p-kid'] } },
    ])
  })
})

describe('Cobros extra: a group by belt', () => {
  const scheme = {
    ranks: [
      { key: 'white', label: 'Blanca', sub_ranks: [] },
      { key: 'blue', label: 'Azul', sub_ranks: [] },
      { key: 'black', label: 'Negra', sub_ranks: [] },
    ],
    kids_ladder: [],
    goal_metric: null,
  }

  it('adds everyone "Azul o superior", with a program or without', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path, method) => {
      if (path === '/api/gym/grading-scheme') return { body: scheme }
      if (path === '/api/people' && method === 'GET') {
        return { body: { items: [{ id: 'p-blue', name: 'Ana Azul', membership: null }], total: 1 } }
      }
      return undefined
    })
    renderAt('/admin/pagos/cobros')

    await user.click(await screen.findByRole('button', { name: copy.groups.create }))
    const belt = await screen.findByLabelText(copy.groups.rank)
    // No ladder for kids, so no groups: the adult belts, each exactly or "o superior".
    expect(within(belt).getAllByRole('option').map((o) => o.textContent)).toEqual([
      copy.groups.any,
      'Blanca',
      'Blanca o superior',
      'Azul',
      'Azul o superior',
      'Negra',
    ])
    await user.selectOptions(belt, 'Azul o superior')
    await user.click(await screen.findByRole('button', { name: copy.groups.addAll(1) }))
    expect(screen.getByText(copy.groups.members(1))).toBeInTheDocument()
    const asked = calls.filter((c) => c.path.startsWith('/api/people?')).map((c) => new URLSearchParams(c.path.split('?')[1]))
    expect(asked.at(-1)?.get('rank_min')).toBe('blue')

    await user.selectOptions(screen.getByLabelText(copy.groups.program), 'pr-kids')
    await user.selectOptions(belt, 'Negra')
    await screen.findByRole('button', { name: copy.groups.addAll(1) })
    const last = calls.filter((c) => c.path.startsWith('/api/people?')).at(-1)!
    const params = new URLSearchParams(last.path.split('?')[1])
    expect([params.getAll('rank'), params.get('rank_min'), params.getAll('program_id')]).toEqual([
      ['black'],
      null,
      ['pr-kids'],
    ])
  })

  it('offers no belt while the gym does not grade', async () => {
    const user = userEvent.setup()
    stubApi('owner', (path) =>
      path === '/api/gym/grading-scheme' ? { body: { ranks: [], kids_ladder: [], goal_metric: null } } : undefined,
    )
    renderAt('/admin/pagos/cobros')

    await user.click(await screen.findByRole('button', { name: copy.groups.create }))
    await screen.findByLabelText(copy.groups.program)
    expect(screen.queryByLabelText(copy.groups.rank)).not.toBeInTheDocument()
  })
})

describe('Nuevo cobro extra', () => {
  it('walks the details, the group, a split with its preview and override, the message, and creates it', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path, method) => {
      if (path === '/api/extra-charges/preview') return { body: PREVIEW }
      if (path === '/api/extra-charges' && method === 'POST') return { status: 201, body: CHARGE }
      return undefined
    })
    const router = renderAt('/admin/pagos/cobros/nuevo')
    const words = copy.wizard

    await user.click(await screen.findByRole('button', { name: words.next }))
    expect(screen.getByText(words.titleNeeded)).toBeInTheDocument()
    await user.type(screen.getByLabelText(words.titleLabel), 'Bencina final')
    await user.selectOptions(screen.getByLabelText(words.categoryLabel), 'gasto_compartido')
    await user.type(screen.getByLabelText(words.dueLabel), '2026-11-30')
    await user.click(screen.getByRole('button', { name: words.next }))

    await user.click(screen.getByRole('radio', { name: words.target.group }))
    await user.selectOptions(await screen.findByLabelText(words.groupLabel), 'g-final')
    await user.click(screen.getByRole('button', { name: words.next }))

    await user.click(screen.getByRole('radio', { name: words.mode.split }))
    await user.type(screen.getByLabelText(words.amountLabel.split), '100000')
    const preview = await screen.findByRole('region', { name: words.previewLabel })
    expect(within(preview).getByText(words.split('$33.333', 3))).toBeInTheDocument()
    expect(within(preview).getByText(words.remainder(1))).toBeInTheDocument()
    expect(within(preview).getByText(words.guardian('Marta Pérez'))).toBeInTheDocument()
    const luis = within(preview).getByLabelText(words.overrideLabel('Luis Mora'))
    await user.clear(luis)
    await user.type(luis, '0')
    // Next waits for the preview of the draft as it now stands.
    await user.click(await screen.findByRole('button', { name: words.next }))

    await user.type(screen.getByLabelText(words.messageLabel), 'Nos vamos el sábado.')
    await user.click(screen.getByRole('button', { name: words.next }))

    expect(screen.getByText(words.noEmail(1))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: words.whatsapp('Marta Pérez') })).toHaveAttribute(
      'href',
      'https://wa.me/56933334444?text=y',
    )
    await user.click(screen.getByRole('button', { name: words.create }))

    await screen.findByRole('heading', { name: 'Bencina final' })
    expect(router.state.location.pathname).toBe('/admin/pagos/cobros/x-final')
    const created = writes(calls).find((c) => c.path === '/api/extra-charges')
    expect(created!.body).toEqual({
      title: 'Bencina final',
      description: null,
      message: 'Nos vamos el sábado.',
      category: 'gasto_compartido',
      due_date: '2026-11-30',
      target: { kind: 'group', group_id: 'g-final' },
      amount_mode: 'split',
      amount_clp: 100000,
      overrides: [{ person_id: 'p-luis', amount_clp: 0 }],
      notify: true,
    })
  })
})

describe('Nuevo cobro extra, while the preview catches up', () => {
  it('neither advances nor confirms on a preview for an older draft', async () => {
    const user = userEvent.setup()
    const words = copy.wizard
    // Each preview waits until the test lets it answer, for the amount it was asked.
    const gates: { amount: number; open: () => void }[] = []
    stubApi('owner', (path, _method, body) => {
      if (path !== '/api/extra-charges/preview') return undefined
      const amount = (body as { amount_clp: number }).amount_clp
      return new Promise<Answer>((resolve) => {
        gates.push({ amount, open: () => resolve({ body: { ...PREVIEW, total_clp: amount } }) })
      })
    })
    renderAt('/admin/pagos/cobros/nuevo')

    await user.type(await screen.findByLabelText(words.titleLabel), 'Rifa')
    await user.type(screen.getByLabelText(words.dueLabel), '2026-11-30')
    await user.click(screen.getByRole('button', { name: words.next }))
    await user.click(screen.getByRole('button', { name: words.next }))

    await user.type(screen.getByLabelText(words.amountLabel.fixed), '5000')
    // Asked, not yet answered: Next waits, and says so.
    const waiting = await screen.findByRole('button', { name: words.previewLoading })
    expect(waiting).toBeDisabled()
    await vi.waitFor(() => expect(gates.length).toBe(1))
    gates[0]!.open()
    expect(await screen.findByRole('button', { name: words.next })).toBeEnabled()

    // A new amount: the old preview stays on screen, but it no longer counts.
    await user.type(screen.getByLabelText(words.amountLabel.fixed), '0')
    expect(screen.getByRole('button', { name: words.previewLoading })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: words.previewLoading }))
    expect(screen.getByRole('region', { name: words.stepOf(3, 5, words.steps[2]!) })).toBeInTheDocument()
    await vi.waitFor(() => expect(gates.length).toBe(2))
    expect(gates[1]!.amount).toBe(50000)
    gates[1]!.open()
    await user.click(await screen.findByRole('button', { name: words.next }))
    expect(screen.getByRole('region', { name: words.stepOf(4, 5, words.steps[3]!) })).toBeInTheDocument()
  })
})

describe('Un cobro extra', () => {
  it('shows each person with their status and what the admin can do', async () => {
    stubApi('owner')
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const ana = (await screen.findByRole('link', { name: 'Ana Rojas' })).closest('li')!
    expect(within(ana).getByText(copy.status.open)).toBeInTheDocument()
    expect(within(ana).getByRole('link', { name: copy.detail.whatsapp('Ana Rojas') })).toBeInTheDocument()
    const carla = screen.getByRole('link', { name: 'Carla Díaz' }).closest('li')!
    expect(within(carla).getByText(copy.status.in_review)).toBeInTheDocument()
    expect(within(carla).getByRole('link', { name: copy.detail.review })).toHaveAttribute('href', '/admin/pagos/comprobantes')
    const bea = screen.getByRole('link', { name: 'Bea Soto' }).closest('li')!
    expect(within(bea).getByText(copy.status.paid)).toBeInTheDocument()
    expect(within(bea).queryByRole('button', { name: copy.detail.markPaid })).not.toBeInTheDocument()
  })

  it('marks a line paid, and reminds who still owes', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path, method) => {
      if (path.endsWith('/payments') && method === 'POST') return { status: 201, body: {} }
      if (path.endsWith('/remind')) return { body: { sent: 1, without_email: 0 } }
      return undefined
    })
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const ana = (await screen.findByRole('link', { name: 'Ana Rojas' })).closest('li')!
    await user.click(within(ana).getByRole('button', { name: copy.detail.markPaid }))
    expect(within(ana).getByLabelText(copy.detail.amountLabel)).toHaveValue('20000')
    await user.selectOptions(within(ana).getByLabelText(copy.detail.methodLabel), 'cash')
    await user.click(within(ana).getByRole('button', { name: copy.detail.save }))
    await user.click(screen.getByRole('button', { name: copy.detail.remind }))

    expect(await screen.findByText(copy.detail.reminded(1, 0))).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      { method: 'POST', path: '/api/extra-charges/x-final/lines/ana/payments', body: { amount_clp: 20000, method: 'cash' } },
      { method: 'POST', path: '/api/extra-charges/x-final/remind', body: undefined },
    ])
  })

  it('cancels a line and divides the total again, showing the new amounts first', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path, method) => {
      if (path.endsWith('/lines/ana/cancel') && method === 'GET') {
        return { body: { resplit_allowed: true, amounts: { bea: 90000, carla: 90000 } } }
      }
      if (path.endsWith('/lines/ana/cancel') && method === 'POST') return { body: CHARGE }
      return undefined
    })
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const ana = (await screen.findByRole('link', { name: 'Ana Rojas' })).closest('li')!
    await user.click(within(ana).getByRole('button', { name: copy.detail.cancelLine }))
    await user.click(await within(ana).findByRole('checkbox', { name: copy.detail.resplit }))
    expect(within(ana).getByText(copy.detail.resplitAmount('Bea Soto', '$90.000'))).toBeInTheDocument()
    await user.click(within(ana).getByRole('button', { name: copy.detail.cancelConfirm }))

    await vi.waitFor(() =>
      expect(writes(calls)).toEqual([
        { method: 'POST', path: '/api/extra-charges/x-final/lines/ana/cancel', body: { resplit: true } },
      ]),
    )
  })

  it('says why a cancel was refused', async () => {
    const user = userEvent.setup()
    stubApi('owner', (path, method) => {
      if (path.endsWith('/cancel') && method === 'GET') return { body: { resplit_allowed: false, amounts: {} } }
      if (path.endsWith('/cancel') && method === 'POST') {
        return { status: 409, body: { detail: 'the line has money on it: refund it first' } }
      }
      return undefined
    })
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const bea = (await screen.findByRole('link', { name: 'Bea Soto' })).closest('li')!
    await user.click(within(bea).getByRole('button', { name: copy.detail.cancelLine }))
    expect(await within(bea).findByText(copy.detail.noResplit)).toBeInTheDocument()
    await user.click(within(bea).getByRole('button', { name: copy.detail.cancelConfirm }))

    expect(await within(bea).findByRole('alert')).toHaveTextContent(copy.detail.refused.money)
  })
})
