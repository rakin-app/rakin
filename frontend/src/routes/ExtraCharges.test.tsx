import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExtraCharge, ExtraChargeSummary, Line, Preview, PreviewLine } from '../api/extraCharges'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.extra

const SUMMARY: ExtraChargeSummary = {
  id: 'x-final',
  title: 'Bencina final',
  category: 'gasto_compartido',
  due_date: '2026-11-30',
  amount_mode: 'split',
  amount_clp: 180000,
  instalments: 1,
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
    instalment: 1,
    due_date: '2026-11-30',
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

// One person's instalments, each a line of its own.
const ANA = { id: 'p-ana', name: 'Ana Rojas' }

const CHARGE: ExtraCharge = {
  ...SUMMARY,
  description: null,
  message: 'Nos vamos el sábado.',
  people: [
    line('ana', 'Ana Rojas', { whatsapp_url: 'https://wa.me/56911112222?text=x' }),
    line('bea', 'Bea Soto', { status: 'paid', paid_clp: 20000, outstanding_clp: 0 }),
    line('carla', 'Carla Díaz', { status: 'in_review', pending_clp: 20000, pending_proof_id: 'e-1' }),
  ],
  schedule: [
    { instalment: 1, due_date: '2026-11-30', lines: 9, paid_lines: 7, waived_lines: 0, due_clp: 180000, collected_clp: 140000 },
  ],
}

const PREVIEW: Preview = {
  lines: [
    {
      person: { id: 'p-ana', name: 'Ana Rojas' },
      amount_clp: 33334,
      instalments_clp: [33334],
      overridden: false,
      contact_name: 'Ana Rojas',
      on_behalf: false,
      has_email: true,
      whatsapp_url: null,
    },
    {
      person: { id: 'p-juan', name: 'Juan Pérez' },
      amount_clp: 33333,
      instalments_clp: [33333],
      overridden: false,
      contact_name: 'Marta Pérez',
      on_behalf: true,
      has_email: false,
      whatsapp_url: 'https://wa.me/56933334444?text=y',
    },
    {
      person: { id: 'p-luis', name: 'Luis Mora' },
      amount_clp: 33333,
      instalments_clp: [33333],
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
  due_dates: ['2026-11-30'],
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
    if (path === '/api/me/role') return { body: { ...asRole(role), person_id: 'me', gym_name: 'Academia Sur' } }
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

  it('says there are no cobros and no groups the same way, each inside a card (#357)', async () => {
    stubApi('owner', (path, method) => {
      if (path === '/api/extra-charges' && method === 'GET') return { body: [] }
      if (path === '/api/groups') return { body: [] }
      return undefined
    })
    renderAt('/admin/pagos/cobros')

    for (const text of [copy.empty, copy.groups.empty]) {
      const said = await screen.findByText(text)
      expect(said).toHaveClass('empty-state__text')
      expect(said.closest('.card')).not.toBeNull()
    }
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
    // Cancelar first, then the save, as every form footer (#419).
    const footer = screen.getByRole('button', { name: copy.groups.save }).parentElement!
    expect([...footer.children].map((el) => el.textContent)).toEqual([copy.groups.cancel, copy.groups.save])
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
      { key: 'white', label: 'Blanca', colors: ['#f4f4f1'], sub_ranks: [] },
      { key: 'blue', label: 'Azul', sub_ranks: [] },
      { key: 'black', label: 'Negra', sub_ranks: [] },
    ],
    kids_ladder: [],
    goal_metric: null,
  }

  it('adds everyone "Azul o superior", with a program or without', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path, method) => {
      if (path === '/api/me/role') return { body: { ...asRole('owner'), person_id: 'me', uses_grades: true } }
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

  it('calls a scheme with no colours "Nivel" (#353)', async () => {
    const user = userEvent.setup()
    const levels = { ...scheme, ranks: scheme.ranks.map(({ key, label }) => ({ key, label, sub_ranks: [] })) }
    stubApi('owner', (path) =>
      path === '/api/me/role'
        ? { body: { ...asRole('owner'), person_id: 'me', uses_grades: true } }
        : path === '/api/gym/grading-scheme'
          ? { body: levels }
          : undefined,
    )
    renderAt('/admin/pagos/cobros')

    await user.click(await screen.findByRole('button', { name: copy.groups.create }))
    expect(await screen.findByLabelText(copy.groups.level)).toHaveDisplayValue(copy.groups.any)
    expect(screen.queryByLabelText(copy.groups.rank)).not.toBeInTheDocument()
  })

  it('offers no belt while no activity of the gym grades, whatever its scheme', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (path) => (path === '/api/gym/grading-scheme' ? { body: scheme } : undefined))
    renderAt('/admin/pagos/cobros')

    await user.click(await screen.findByRole('button', { name: copy.groups.create }))
    await screen.findByLabelText(copy.groups.program)
    expect(screen.queryByLabelText(copy.groups.rank)).not.toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/gym/grading-scheme')).toBe(false)
  })

  it('offers no belt while the gym does not grade', async () => {
    const user = userEvent.setup()
    stubApi('owner', (path) =>
      path === '/api/me/role'
        ? { body: { ...asRole('owner'), person_id: 'me', uses_grades: true } }
        : path === '/api/gym/grading-scheme'
          ? { body: { ranks: [], kids_ladder: [], goal_metric: null } }
          : undefined,
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

    // Cancelar on the left, Siguiente on the right, as Nuevo alumno's footer (#419).
    const footer = (await screen.findByRole('button', { name: words.next })).parentElement!
    expect([...footer.children].map((el) => el.textContent)).toEqual([words.cancel, words.next])

    await user.click(await screen.findByRole('button', { name: words.next }))
    expect(screen.getByText(words.titleNeeded)).toBeInTheDocument()
    // The field to fix takes focus, and says why (#362).
    expect(screen.getByLabelText(words.titleLabel)).toHaveFocus()
    expect(screen.getByLabelText(words.titleLabel)).toHaveAccessibleDescription(words.titleNeeded)
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

    // The last look says who, by what rule, how much each, the total, the due date and the
    // email as it goes out (#357).
    const look = screen.getByRole('region', { name: words.stepOf(5, 5, words.steps[4]!) })
    const facts = Object.fromEntries(
      within(look)
        .getAllByRole('term')
        .map((term) => [term.textContent, term.nextElementSibling!.textContent]),
    )
    expect(facts).toEqual({
      [words.confirm.charge]: 'Bencina final',
      [words.confirm.who]: words.confirm.whoIs(3, words.confirm.rule.group('Clasificados final')),
      [words.confirm.amount]: words.split('$33.333', 3),
      [words.confirm.total]: '$100.000',
      [words.confirm.due]: '30 de noviembre de 2026',
    })
    const email = within(look).getByRole('region', { name: words.confirm.message })
    expect(email).toHaveTextContent(words.confirm.hello('Ana Rojas'))
    expect(email).toHaveTextContent(words.confirm.sends('Academia Sur', 'Bencina final', null))
    expect(email).toHaveTextContent('Nos vamos el sábado.')
    expect(email).toHaveTextContent(words.confirm.owes(null, '$33.334', '30 de noviembre de 2026'))
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
      instalments: 1,
      notify: true,
    })
  })

  it('charges in instalments: how many, each one\'s amount, their dates, and the email about the first (#356)', async () => {
    const user = userEvent.setup()
    const DATES = ['2026-12-15', '2027-01-15', '2027-02-15']
    const calls = stubApi('owner', (path, method, body) => {
      if (path === '/api/extra-charges/preview') {
        const n = (body as { instalments: number }).instalments
        const split = n === 3 ? [33335, 33333, 33333] : [100001]
        const each = (person: PreviewLine['person'], email: boolean): PreviewLine => ({
          person,
          amount_clp: 100001,
          instalments_clp: split,
          overridden: false,
          contact_name: person.name,
          on_behalf: false,
          has_email: email,
          whatsapp_url: null,
        })
        return {
          body: {
            lines: [each({ id: 'p-ana', name: 'Ana Rojas' }, true)],
            total_clp: 100001,
            remainder_clp: 0,
            share_clp: null,
            due_dates: DATES.slice(0, n),
          } satisfies Preview,
        }
      }
      if (path === '/api/extra-charges' && method === 'POST') return { status: 201, body: CHARGE }
      return undefined
    })
    renderAt('/admin/pagos/cobros/nuevo')
    const words = copy.wizard

    await user.type(await screen.findByLabelText(words.titleLabel), 'Viaje a la regata')
    await user.type(screen.getByLabelText(words.dueLabel), DATES[0]!)
    await user.click(screen.getByRole('button', { name: words.next }))
    await user.click(screen.getByRole('radio', { name: words.target.group }))
    await user.selectOptions(await screen.findByLabelText(words.groupLabel), 'g-final')
    await user.click(screen.getByRole('button', { name: words.next }))

    await user.type(screen.getByLabelText(words.amountLabel.fixed), '100001')
    expect(screen.queryByLabelText(words.instalmentsLabel)).not.toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: new RegExp(words.inInstalments) }))
    await user.selectOptions(screen.getByLabelText(words.instalmentsLabel), '3')
    const preview = await screen.findByRole('region', { name: words.previewLabel })
    expect(await within(preview).findByText(words.splitFirst(3, '$33.335', '$33.333'))).toBeInTheDocument()
    expect(within(preview).getByText(words.instalmentsRemainder)).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: words.next }))
    await user.click(screen.getByRole('button', { name: words.next }))

    const look = screen.getByRole('region', { name: words.stepOf(5, 5, words.steps[4]!) })
    const terms = within(look).getAllByRole('term').map((term) => term.textContent)
    expect(terms).toContain(words.confirm.instalments)
    expect(terms).not.toContain(words.confirm.due)
    expect(look).toHaveTextContent(words.confirm.instalmentDue(1, '$33.335', '15 de diciembre de 2026'))
    expect(look).toHaveTextContent(words.confirm.instalmentDue(3, '$33.333', '15 de febrero de 2027'))
    const email = within(look).getByRole('region', { name: words.confirm.message })
    expect(email).toHaveTextContent(words.confirm.sends('Academia Sur', 'Viaje a la regata · cuota 1 de 3', null))
    // The email writes the date as the screen does (#417).
    expect(email).toHaveTextContent(words.confirm.owes(null, '$33.335', '15 de diciembre de 2026'))
    await user.click(screen.getByRole('button', { name: words.create }))

    await screen.findByRole('heading', { name: 'Bencina final' })
    const created = writes(calls).find((c) => c.path === '/api/extra-charges')
    expect(created!.body).toMatchObject({ amount_clp: 100001, instalments: 3, due_date: DATES[0] })
  })
})

describe('Nuevo cobro extra, in instalments for a programme (#417)', () => {
  // A seven-term split, said once: $89.990 in 7 is $12.860 and six of $12.855.
  const SPLIT = [12860, 12855, 12855, 12855, 12855, 12855, 12855]
  const DATES = ['2026-12-15', '2027-01-15', '2027-02-15', '2027-03-15', '2027-04-15', '2027-05-15', '2027-06-15']
  const kid = (i: number, amount: number, split: number[]): PreviewLine => ({
    person: { id: `p-kid-${i}`, name: `Kid ${String(i).padStart(2, '0')}` },
    amount_clp: amount,
    instalments_clp: split,
    overridden: amount !== 89990,
    contact_name: `Kid ${String(i).padStart(2, '0')}`,
    on_behalf: false,
    has_email: true,
    whatsapp_url: null,
  })

  async function toAmount(lines: PreviewLine[]) {
    const user = userEvent.setup()
    stubApi('owner', (path) => {
      if (path !== '/api/extra-charges/preview') return undefined
      return {
        body: {
          lines,
          total_clp: lines.reduce((sum, line) => sum + line.amount_clp, 0),
          remainder_clp: 0,
          share_clp: null,
          due_dates: DATES,
        } satisfies Preview,
      }
    })
    renderAt('/admin/pagos/cobros/nuevo')
    const words = copy.wizard
    await user.type(await screen.findByLabelText(words.titleLabel), 'Campeonato')
    await user.type(screen.getByLabelText(words.dueLabel), DATES[0]!)
    await user.click(screen.getByRole('button', { name: words.next }))
    await user.click(screen.getByRole('radio', { name: words.target.program }))
    await user.selectOptions(await screen.findByLabelText(words.programLabel), 'pr-kids')
    await user.click(screen.getByRole('button', { name: words.next }))
    await user.type(screen.getByLabelText(words.amountLabel.fixed), '89990')
    await user.click(screen.getByRole('checkbox', { name: new RegExp(words.inInstalments) }))
    await user.selectOptions(screen.getByLabelText(words.instalmentsLabel), '7')
    const preview = await screen.findByRole('region', { name: words.previewLabel })
    await within(preview).findByText(words.splitFirst(7, '$12.860', '$12.855'))
    return { user, preview }
  }

  it('says the split once when everyone pays the same, and gives each cuota its amount', async () => {
    const words = copy.wizard
    const { user, preview } = await toAmount(Array.from({ length: 20 }, (_, i) => kid(i + 1, 89990, SPLIT)))

    expect(within(preview).getAllByText(words.splitFirst(7, '$12.860', '$12.855'))).toHaveLength(1)
    expect(within(preview).getAllByRole('textbox')).toHaveLength(20)

    await user.click(await screen.findByRole('button', { name: words.next }))
    await user.click(screen.getByRole('button', { name: words.next }))
    const look = screen.getByRole('region', { name: words.stepOf(5, 5, words.steps[4]!) })
    expect(look).toHaveTextContent(words.confirm.instalmentDue(1, '$12.860', '15 de diciembre de 2026'))
    expect(look).toHaveTextContent(words.confirm.instalmentDue(2, '$12.855', '15 de enero de 2027'))
  })

  it("shows a person's own split only where it differs, and each cuota's total then", async () => {
    const words = copy.wizard
    const theirs = [10000, 10000, 10000, 10000, 10000, 10000, 10000]
    const { user, preview } = await toAmount([kid(1, 89990, SPLIT), kid(2, 70000, theirs), kid(3, 89990, SPLIT)])

    expect(within(preview).getAllByText(words.splitFirst(7, '$12.860', '$12.855'))).toHaveLength(1)
    const odd = within(preview).getByLabelText(words.overrideLabel('Kid 02')).closest('li')!
    expect(within(odd).getByText(words.splitEven(7, '$10.000'))).toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: words.next }))
    await user.click(screen.getByRole('button', { name: words.next }))
    const look = screen.getByRole('region', { name: words.stepOf(5, 5, words.steps[4]!) })
    expect(look).toHaveTextContent(
      words.confirm.instalmentDue(1, words.confirm.inAll('$35.720'), '15 de diciembre de 2026'),
    )
  })
})

describe('Nuevo cobro extra, from a ficha (#279)', () => {
  it('starts with the person "Cobro extra" was pressed for picked', async () => {
    const user = userEvent.setup()
    stubApi('owner', (path) =>
      path === '/api/people/p-luis' ? { body: { id: 'p-luis', name: 'Luis Mora' } } : undefined,
    )
    renderAt('/admin/pagos/cobros/nuevo?person=p-luis')
    const words = copy.wizard

    await user.type(await screen.findByLabelText(words.titleLabel), 'Matrícula')
    await user.type(screen.getByLabelText(words.dueLabel), '2026-11-30')
    await user.click(screen.getByRole('button', { name: words.next }))

    expect(screen.getByRole('radio', { name: words.target.people })).toBeChecked()
    expect(screen.getByRole('button', { name: copy.groups.remove('Luis Mora') })).toBeInTheDocument()
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
  // Before the charge's due date, 2026-11-30, or Ana's line reads as overdue (#330).
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-20T15:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

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

  it('sets what the cobro recovers beside what it collected, to who reads expenses (#318)', async () => {
    const expenses = { count: 2, expenses_clp: 170_000, collected_clp: 60_000, difference_clp: -110_000 }
    stubApi('owner', (path) => (path === `/api/extra-charges/${CHARGE.id}` ? { body: { ...CHARGE, expenses } } : undefined))
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const card = await screen.findByRole('region', { name: copy.detail.expensesLabel })
    const figure = (label: string) => within(card).getByText(label, { selector: 'dt' }).nextElementSibling
    expect(figure(copy.detail.expensesLabel)).toHaveTextContent('$170.000')
    expect(figure(copy.detail.collectedLabel)).toHaveTextContent('$60.000')
    expect(figure(copy.detail.differenceLabel)).toHaveTextContent('110.000')
    expect(figure(copy.detail.differenceLabel)).toHaveClass('extra__negative')
  })

  it('shows no expenses on a cobro whose answer carries none (#318)', async () => {
    stubApi('owner')
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)
    await screen.findByRole('link', { name: 'Ana Rojas' })
    expect(screen.queryByRole('region', { name: copy.detail.expensesLabel })).not.toBeInTheDocument()
  })

  it('gives each person one action, and the rest under their "Más" (#357)', async () => {
    stubApi('owner')
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    // What a row shows outside its menu: its one action, then "Más".
    const shown = (name: string) => {
      const row = screen.getByRole('group', { name: copy.detail.actions(name) })
      return [...row.querySelectorAll('a, button, summary')]
        .filter((control) => !control.closest('.more-menu__list'))
        .map((control) => control.getAttribute('aria-label') ?? control.textContent)
    }
    await screen.findByRole('link', { name: 'Ana Rojas' })
    expect(shown('Ana Rojas')).toEqual([copy.detail.markPaid, copy.detail.moreFor('Ana Rojas')])
    expect(shown('Carla Díaz')).toEqual([copy.detail.review, copy.detail.moreFor('Carla Díaz')])
    expect(shown('Bea Soto')).toEqual([copy.detail.moreFor('Bea Soto')])

    const ana = screen.getByRole('group', { name: copy.detail.actions('Ana Rojas') })
    const menu = ana.querySelector('.more-menu__list')!
    expect([...menu.children].map((item) => item.getAttribute('aria-label') ?? item.textContent)).toEqual([
      copy.detail.whatsapp('Ana Rojas'),
      copy.detail.notify,
      copy.detail.editAmount,
      copy.detail.cancelLine,
    ])
  })

  it('cuts a long title to two lines and shows it whole on request (#357)', async () => {
    const user = userEvent.setup()
    // jsdom lays nothing out: the heading says it overflows, as a long one does.
    const height = vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(200)
    try {
      stubApi('owner')
      renderAt(`/admin/pagos/cobros/${CHARGE.id}`)
      const heading = await screen.findByRole('heading', { level: 1, name: CHARGE.title })
      expect(heading).toHaveClass('extra__title--clamped')
      await user.click(screen.getByRole('button', { name: copy.titleMore }))
      expect(heading).not.toHaveClass('extra__title--clamped')
      expect(screen.getByRole('button', { name: copy.titleLess })).toHaveAttribute('aria-expanded', 'true')
    } finally {
      height.mockRestore()
    }
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
    await user.click(within(ana).getByText(copy.detail.more))
    await user.click(within(ana).getByRole('button', { name: copy.detail.cancelLine }))
    await user.click(await within(ana).findByRole('checkbox', { name: copy.detail.resplit }))
    expect(within(ana).getByText(copy.detail.resplitAmount('Bea Soto', '$90.000'))).toBeInTheDocument()
    // Not without a reason (#256).
    await user.click(within(ana).getByRole('button', { name: copy.detail.cancelConfirm }))
    expect(within(ana).getByText(copy.detail.cancelReasonNeeded)).toBeInTheDocument()
    await user.type(within(ana).getByLabelText(copy.detail.cancelReason), 'se retiró')
    await user.click(within(ana).getByRole('button', { name: copy.detail.cancelConfirm }))

    await vi.waitFor(() =>
      expect(writes(calls)).toEqual([
        { method: 'POST', path: '/api/extra-charges/x-final/lines/ana/cancel', body: { resplit: true, reason: 'se retiró' } },
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
    await user.click(within(bea).getByText(copy.detail.more))
    await user.click(within(bea).getByRole('button', { name: copy.detail.cancelLine }))
    expect(await within(bea).findByText(copy.detail.noResplit)).toBeInTheDocument()
    await user.type(within(bea).getByLabelText(copy.detail.cancelReason), 'se retiró')
    await user.click(within(bea).getByRole('button', { name: copy.detail.cancelConfirm }))

    expect(await within(bea).findByRole('alert')).toHaveTextContent(copy.detail.refused.money)
  })

  it("shows a cobro in instalments: each instalment's progress, and each line's own date (#356)", async () => {
    const IN_CUOTAS: ExtraCharge = {
      ...CHARGE,
      title: 'Viaje a la regata',
      instalments: 3,
      due_date: '2026-11-15',
      lines: 1,
      paid_lines: 0,
      due_clp: 100001,
      collected_clp: 33335,
      people: [
        line('ana-1', 'Ana Rojas', { person: ANA, instalment: 1, due_date: '2026-11-15', amount_due_clp: 33335, status: 'paid', paid_clp: 33335, outstanding_clp: 0 }),
        line('ana-2', 'Ana Rojas', { person: ANA, instalment: 2, due_date: '2026-12-15', amount_due_clp: 33333, outstanding_clp: 33333 }),
        line('ana-3', 'Ana Rojas', { person: ANA, instalment: 3, due_date: '2027-01-15', amount_due_clp: 33333, outstanding_clp: 33333 }),
      ],
      schedule: [
        { instalment: 1, due_date: '2026-11-15', lines: 1, paid_lines: 1, waived_lines: 0, due_clp: 33335, collected_clp: 33335 },
        { instalment: 2, due_date: '2026-12-15', lines: 1, paid_lines: 0, waived_lines: 0, due_clp: 33333, collected_clp: 0 },
        { instalment: 3, due_date: '2027-01-15', lines: 1, paid_lines: 0, waived_lines: 0, due_clp: 33333, collected_clp: 0 },
      ],
    }
    stubApi('owner', (path) => (path === `/api/extra-charges/${CHARGE.id}` ? { body: IN_CUOTAS } : undefined))
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const schedule = await screen.findByRole('region', { name: copy.detail.scheduleLabel })
    expect(within(schedule).getAllByRole('progressbar').map((bar) => bar.getAttribute('aria-label'))).toEqual([
      copy.progress(1, 1, '$33.335', '$33.335'),
      copy.progress(0, 1, '$0', '$33.333'),
      copy.progress(0, 1, '$0', '$33.333'),
    ])
    const people = screen.getByRole('region', { name: copy.detail.peopleLabel })
    // One row for the person (#417): how far along, the next cuota and its one action.
    expect(within(people).getAllByRole('link', { name: 'Ana Rojas' })).toHaveLength(1)
    const ana = within(people).getByRole('link', { name: 'Ana Rojas' }).closest('li')!
    expect(within(ana).getByText(copy.detail.instalmentsPaid(1, 3))).toBeInTheDocument()
    expect(within(ana).getByText(copy.detail.paidOf('$33.335', '$100.001'))).toBeInTheDocument()
    expect(within(ana).getByText(copy.detail.nextDue(2, 3, '15 dic', '$33.333'))).toBeInTheDocument()
    expect(within(ana).getByRole('button', { name: copy.detail.markPaidInstalment(2) })).toBeInTheDocument()
    expect(within(people).queryByRole('group', { name: copy.detail.actionsOf('Ana Rojas', 2) })).not.toBeInTheDocument()

    // "Ver cuotas": each cuota with its own date and actions.
    const user = userEvent.setup()
    await user.click(within(ana).getByRole('button', { name: copy.detail.showInstalmentsOf('Ana Rojas') }))
    const cuotas = within(ana).getByRole('list', { name: copy.detail.instalmentsOfPerson('Ana Rojas') })
    expect(within(cuotas).getAllByRole('listitem')).toHaveLength(3)
    const second = within(cuotas).getByRole('group', { name: copy.detail.actionsOf('Ana Rojas', 2) }).closest('li')!
    expect(within(second).getByText(copy.detail.instalmentDue(2, 3, '15 dic'))).toBeInTheDocument()
    expect(within(second).getByText(copy.status.open)).toBeInTheDocument()
    expect(within(cuotas).getByRole('group', { name: copy.detail.actionsOf('Ana Rojas', 1) })).toBeInTheDocument()
  })

  it('lists a 20-person, 7-cuota cobro as 20 rows, each reaching every cuota (#417)', async () => {
    const user = userEvent.setup()
    const days = ['2026-12-15', '2027-01-15', '2027-02-15', '2027-03-15', '2027-04-15', '2027-05-15', '2027-06-15']
    const split = [12860, 12855, 12855, 12855, 12855, 12855, 12855]
    const name = (k: number) => `Kid ${String(k).padStart(2, '0')}`
    const people = Array.from({ length: 20 }, (_, k) =>
      split.map((amount, i) =>
        line(`k${k + 1}-${i + 1}`, name(k + 1), {
          person: { id: `p-k${k + 1}`, name: name(k + 1) },
          instalment: i + 1,
          due_date: days[i]!,
          amount_due_clp: amount,
          // The first two cuotas of the first child are paid.
          ...(k === 0 && i < 2 ? { status: 'paid' as const, paid_clp: amount, outstanding_clp: 0 } : { outstanding_clp: amount }),
        }),
      ),
    ).flat()
    const KIDS: ExtraCharge = { ...CHARGE, title: 'Campeonato', instalments: 7, due_date: days[0]!, people }
    const calls = stubApi('owner', (path, method) => {
      if (path === `/api/extra-charges/${CHARGE.id}`) return { body: KIDS }
      if (path.endsWith('/payments') && method === 'POST') return { status: 201, body: {} }
      return undefined
    })
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const list = (await screen.findByRole('region', { name: copy.detail.peopleLabel })).querySelector('ul')!
    expect(list.children).toHaveLength(20)
    const first = within(list).getByRole('link', { name: 'Kid 01' }).closest('li')!
    expect(within(first).getByText(copy.detail.instalmentsPaid(2, 7))).toBeInTheDocument()
    expect(within(first).getByText(copy.detail.paidOf('$25.715', '$89.990'))).toBeInTheDocument()

    // The main action pays the next cuota.
    await user.click(within(first).getByRole('button', { name: copy.detail.markPaidInstalment(3) }))
    expect(within(first).getByLabelText(copy.detail.amountLabel)).toHaveValue('12855')
    await user.click(within(first).getByRole('button', { name: copy.detail.save }))
    await vi.waitFor(() =>
      expect(writes(calls)).toEqual([
        { method: 'POST', path: '/api/extra-charges/x-final/lines/k1-3/payments', body: { amount_clp: 12855, method: 'transfer' } },
      ]),
    )

    // Every cuota of the last child is a click away, with its own "Más".
    const last = within(list).getByRole('link', { name: 'Kid 20' }).closest('li')!
    await user.click(within(last).getByRole('button', { name: copy.detail.showInstalmentsOf('Kid 20') }))
    for (let i = 1; i <= 7; i++) {
      expect(within(last).getByRole('group', { name: copy.detail.actionsOf('Kid 20', i) })).toBeInTheDocument()
    }
  })

  it('counts a cancelled cuota out of what the person owes (#417)', async () => {
    const days = ['2026-12-15', '2027-01-15', '2027-02-15', '2027-03-15', '2027-04-15', '2027-05-15', '2027-06-15']
    const lines = days.map((day, i) =>
      line(`ana-${i + 1}`, 'Ana Rojas', {
        person: ANA,
        instalment: i + 1,
        due_date: day,
        amount_due_clp: 10000,
        ...(i < 2
          ? { status: 'paid' as const, paid_clp: 10000, outstanding_clp: 0 }
          : i === 6
            ? { status: 'cancelled' as const, outstanding_clp: 0, cancel_reason: 'se retiró' }
            : { outstanding_clp: 10000 }),
      }),
    )
    const CANCELLED: ExtraCharge = { ...CHARGE, instalments: 7, due_date: days[0]!, people: lines }
    stubApi('owner', (path) => (path === `/api/extra-charges/${CHARGE.id}` ? { body: CANCELLED } : undefined))
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const ana = (await screen.findByRole('link', { name: 'Ana Rojas' })).closest('li')!
    expect(within(ana).getByText(copy.detail.instalmentsPaid(2, 6))).toBeInTheDocument()
    expect(within(ana).getByText(copy.detail.paidOf('$20.000', '$60.000'))).toBeInTheDocument()
  })

  it('lists a cobro paid at once as one row per line, as before (#417)', async () => {
    stubApi('owner')
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    await screen.findByRole('link', { name: 'Ana Rojas' })
    expect(screen.queryByRole('button', { name: copy.detail.showInstalmentsOf('Ana Rojas') })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.detail.scheduleLabel })).not.toBeInTheDocument()
    const ana = screen.getByRole('link', { name: 'Ana Rojas' }).closest('li')!
    expect(within(ana).getByText('$20.000')).toBeInTheDocument()
  })

  it("reads an instalment due today as owed, not late, in the gym's evening (#356)", async () => {
    // 22:00 on 20 November in Santiago, already the 21st in UTC.
    vi.setSystemTime(new Date('2026-11-21T01:00:00Z'))
    const user = userEvent.setup()
    const TODAY: ExtraCharge = {
      ...CHARGE,
      instalments: 2,
      people: [
        line('ana-1', 'Ana Rojas', { person: ANA, instalment: 1, due_date: '2026-11-19' }),
        line('ana-2', 'Ana Rojas', { person: ANA, instalment: 2, due_date: '2026-11-20' }),
      ],
    }
    stubApi('owner', (path) => {
      if (path === `/api/extra-charges/${CHARGE.id}`) return { body: TODAY }
      if (path === '/api/sessions') return { body: { date: '2026-11-20', timezone: 'America/Santiago', sessions: [] } }
      return undefined
    })
    renderAt(`/admin/pagos/cobros/${CHARGE.id}`)

    const row = (i: number) =>
      screen.getByRole('group', { name: copy.detail.actionsOf('Ana Rojas', i) }).closest('li')!
    await user.click(await screen.findByRole('button', { name: copy.detail.showInstalmentsOf('Ana Rojas') }))
    await screen.findByRole('group', { name: copy.detail.actionsOf('Ana Rojas', 2) })
    await vi.waitFor(() => expect(within(row(2)).getByText(copy.status.open)).toBeInTheDocument())
    expect(within(row(1)).getByText(copy.status.overdue)).toBeInTheDocument()

    // Changing one instalment's amount says the others stay as they are.
    await user.click(within(row(2)).getByText(copy.detail.more))
    await user.click(within(row(2)).getByRole('button', { name: copy.detail.editAmount }))
    expect(within(row(2)).getByLabelText(copy.detail.amountLabel)).toHaveAccessibleDescription(
      copy.detail.amountOneInstalment,
    )
  })
})
