import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MyClasses, TagHours } from '../api/classTags'
import type { PersonTime } from '../api/matTime'
import type { BankAccount, Dependent, MyPage, MyPayment } from '../api/me'
import type { OpenPeriod } from '../api/proofs'
import type { PersonRequirements } from '../api/requirements'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

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
  kind: 'payment',
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

const NO_TIME: PersonTime = {
  timezone: 'America/Santiago',
  month_start: `${YEAR}-11-01`,
  this_month: { by_kind: [], sparring_seconds: 0, open_mat_seconds: 0, classes: 0, open_mats: 0 },
  all_time: { by_kind: [], sparring_seconds: 0, open_mat_seconds: 0, classes: 0, open_mats: 0 },
}

const NO_CLASSES: MyClasses = { timezone: 'America/Santiago', people: [] }

const hoursOf = (tags: TagHours['tags'], untagged = 0): TagHours => ({
  first_day: `${YEAR}-11-01`,
  last_day: `${YEAR}-11-30`,
  tags,
  untagged_minutes: untagged,
  no_duration_classes: 0,
  no_duration: [],
})

function diego(over: Partial<MyPage> = {}): MyPage {
  return {
    gym_name: 'Academia Sur',
    timezone: 'America/Santiago',
    person_id: 'diego',
    name: 'Diego Morales',
    member_since: '2024-03-30',
    next_payment: { period: NOVEMBER, status: 'in_review' },
    bank_account: BANK,
    rank: null,
    attendance: { this_month: 0, total: 0 },
    payments: [
      payment({ id: 'e-nov', status: 'pending', period_start: NOVEMBER.period_start, claimed_at: new Date().toISOString(), validated_at: null }),
      payment({ id: 'e-oct' }),
      payment({ id: 'e-old', period_start: `${YEAR - 1}-09-10`, validated_at: '2025-09-09T15:00:00Z' }),
    ],
    ...over,
  }
}

function stubPage(
  answer: MyPage | { status: number },
  time: PersonTime = NO_TIME,
  classes: MyClasses = NO_CLASSES,
  // Whether an activity of the gym grades (#245); by default one does.
  grades = true,
  // What the gym asks before training (#349); by default nothing.
  requirements: PersonRequirements[] = [],
  // A guardian's dependents (#66), and each one's time on the mat; by default none.
  dependents: Dependent[] = [],
  dependentTime: Record<string, PersonTime> = {},
) {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/me/page') {
        if ('status' in answer) return new Response('{}', { status: answer.status })
        return Response.json(answer)
      }
      if (url.pathname === '/api/me/periods') return Response.json([NOVEMBER])
      if (url.pathname === '/api/me/extra-lines') return Response.json([])
      if (url.pathname === '/api/me/time') return Response.json(time)
      if (url.pathname === '/api/me/classes') return Response.json(classes)
      if (url.pathname === '/api/me/requirements') return Response.json(requirements)
      if (url.pathname === '/api/me/dependents') return Response.json(dependents)
      const theirs = /^\/api\/me\/dependents\/([^/]+)\/time$/.exec(url.pathname)?.[1]
      if (theirs && dependentTime[theirs]) return Response.json(dependentTime[theirs])
      if (url.pathname === '/api/me/role') {
        return Response.json({ ...asRole(null), person_id: 'diego', gym_name: 'Academia Sur', uses_grades: grades })
      }
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
    await waitFor(() => expect(document.title).toBe('Mi página · Academia Sur'))
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

  it('names the plan by what is due and by each payment for someone on two plans (#354)', async () => {
    const plan = (membership_id: string, plan_name: string) => ({
      membership_id,
      person_id: 'diego',
      person_name: 'Diego Morales',
      plan_name,
      status: 'active' as const,
      freeze: null,
      pending_request: null,
      last_decided: null,
    })
    stubPage(
      diego({
        plans: [plan('m-diego', 'Mensual adultos'), plan('m-curso', 'Curso de iniciación')],
        payments: [
          payment({ id: 'e-curso', period_start: `${YEAR}-10-02`, plan_name: 'Curso de iniciación' }),
          payment({ id: 'e-oct', plan_name: 'Mensual adultos' }),
        ],
      }),
    )
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    expect(within(nextCard()).getByText('vence el 10 de noviembre · Mensual adultos')).toBeInTheDocument()
    const history = screen.getByRole('region', { name: copy.history.title })
    expect(within(history).getByText('Octubre · Curso de iniciación')).toBeInTheDocument()
    expect(within(history).getByText('Octubre · Mensual adultos')).toBeInTheDocument()
  })

  it('names no plan for someone who changed plan, on one now (#354)', async () => {
    stubPage(
      diego({
        plans: [
          {
            membership_id: 'm-diego',
            person_id: 'diego',
            person_name: 'Diego Morales',
            plan_name: 'Mensual adultos',
            status: 'active',
            freeze: null,
            pending_request: null,
            last_decided: null,
          },
        ],
        payments: [
          payment({ id: 'e-oct', plan_name: 'Mensual adultos' }),
          payment({ id: 'e-sep', period_start: `${YEAR}-09-10`, plan_name: 'Estudiante' }),
        ],
      }),
    )
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    expect(within(nextCard()).getByText('vence el 10 de noviembre')).toBeInTheDocument()
    const history = screen.getByRole('region', { name: copy.history.title })
    expect(within(history).getByText('Octubre')).toBeInTheDocument()
    expect(within(history).getByText('Septiembre')).toBeInTheDocument()
  })

  it('names no plan for someone on one', async () => {
    stubPage(diego({ payments: [payment({ id: 'e-oct', plan_name: 'Mensual adultos' })] }))
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    expect(within(nextCard()).getByText('vence el 10 de noviembre')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: copy.history.title })).getByText('Octubre')).toBeInTheDocument()
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

  it('says a proof is in review, and offers another one as the quiet action (#362)', async () => {
    stubPage(diego())
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.next.title }))
    expect(card.getByText(copy.next.inReview)).toBeInTheDocument()
    const another = card.getByRole('button', { name: copy.next.uploadAnother })
    expect(another).not.toHaveClass('button--primary')
    expect(card.queryByRole('button', { name: copy.next.upload })).not.toBeInTheDocument()
  })

  it('makes the upload the main action while nothing is sent', async () => {
    stubPage(diego({ next_payment: { period: NOVEMBER, status: 'due' } }))
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.next.title }))
    expect(card.getByRole('button', { name: copy.next.upload })).toHaveClass('button--primary')
    expect(card.queryByText(copy.next.inReview)).not.toBeInTheDocument()
  })

  it('opens the proof upload from the card', async () => {
    stubPage(diego({ next_payment: { period: NOVEMBER, status: 'due' } }))
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
    expect(screen.getByRole('button', { name: copy.next.uploadAnother })).toBeInTheDocument()
  })

  it('calls an uncoloured rank a grade, not a belt, and since when', async () => {
    stubPage(
      diego({
        rank: { rank_key: 'purple', rank_label: 'Morada', sub_rank: '1', sub_rank_label: '1 grado', awarded_on: '2025-06-14' },
      }),
    )
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.training.title }))
    expect(await card.findByText(copy.training.rank)).toBeInTheDocument()
    expect(card.queryByText(copy.training.belt)).not.toBeInTheDocument()
    expect(card.getByText('Morada · 1 grado')).toBeInTheDocument()
    expect(card.getByText('desde 14 jun 2025')).toBeInTheDocument()
    expect(card.queryByRole('img')).not.toBeInTheDocument()
  })

  it('says since when they train here (#293)', async () => {
    stubPage(diego({ member_since: '2019-03-05' }))
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.training.title }))
    expect(await card.findByText(copy.training.memberSince('mar 2019'))).toBeInTheDocument()
  })

  it('shows no rank while no activity of the gym grades (#245)', async () => {
    const rank = { rank_key: 'purple', rank_label: 'Morada', sub_rank: '1', sub_rank_label: '1 grado', awarded_on: '2025-06-14' }
    stubPage(diego({ rank }), NO_TIME, NO_CLASSES, false)
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.training.title }))
    expect(card.getByText(copy.training.month)).toBeInTheDocument()
    // Once the gym has said it does not grade, as well as before.
    const asked = () => vi.mocked(fetch).mock.calls.map(([input]) => new URL(String(input), 'http://localhost').pathname)
    await waitFor(() => expect(asked()).toContain('/api/me/role'))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(card.queryByText('Morada · 1 grado')).not.toBeInTheDocument()
    expect(card.queryByText(copy.training.rank)).not.toBeInTheDocument()
  })

  it('draws the belt when the gym colours it', async () => {
    stubPage(
      diego({
        rank: {
          rank_key: 'black',
          rank_label: 'Negra',
          sub_rank: '1',
          sub_rank_label: '1 grado',
          awarded_on: '2025-06-14',
          belt: { colors: ['#1b1b1b'], stripes: 1, max_stripes: 4 },
        },
      }),
    )
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.training.title }))
    expect(await card.findByText(copy.training.belt)).toBeInTheDocument()
    expect(card.getByRole('img', { name: 'Negra, 1 grado' })).toBeInTheDocument()
    expect(card.getByText('Negra · 1 grado')).toBeInTheDocument()
  })

  it('has no belt card until the gym records a rank, as in a gym with no grades (#226)', async () => {
    stubPage(diego())
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.training.title }))
    expect(card.queryByText(copy.training.belt)).not.toBeInTheDocument()
    expect(card.queryByText(copy.training.rank)).not.toBeInTheDocument()
    expect(document.querySelector('.belt')).toBeNull()
  })

  it("counts this month's classes and all of them", async () => {
    stubPage(diego({ attendance: { this_month: 11, total: 312 } }))
    renderMe()

    const card = within(await screen.findByRole('region', { name: copy.training.title }))
    expect(card.getByText(copy.training.month)).toBeInTheDocument()
    expect(card.getByText('11 clases')).toBeInTheDocument()
    expect(card.getByText('312 en total')).toBeInTheDocument()
  })

  it('shows the time on the mat, from the API', async () => {
    const month = {
      by_kind: [{ block_kind_id: 'k-spar', name: 'Sparring', is_sparring: true, seconds: 23400 }],
      sparring_seconds: 23400,
      open_mat_seconds: 0,
      classes: 5,
      open_mats: 0,
    }
    stubPage(diego(), { ...NO_TIME, this_month: month, all_time: { ...month, classes: 40, sparring_seconds: 360000 } })
    renderMe()

    const card = within(await screen.findByRole('region', { name: es.matTime.mine, busy: false }))
    expect(card.getByRole('list', { name: es.matTime.byKind })).toHaveTextContent('Sparring6 h 30 min')
  })

  it("shows each dependent's rank, classes and time on the mat (#66)", async () => {
    const mateo: Dependent = {
      id: 'mateo',
      name: 'Mateo Morales',
      rank: {
        rank_key: 'grey',
        rank_label: 'Gris',
        sub_rank: '2',
        sub_rank_label: '2 grados',
        awarded_on: '2026-04-02',
        belt: { colors: ['#8a8a8a'], stripes: 2, max_stripes: 4 },
      },
      attendance: { this_month: 3, total: 41 },
    }
    const lucia: Dependent = { id: 'lucia', name: 'Lucía Morales', rank: null, attendance: { this_month: 0, total: 0 } }
    const month = {
      by_kind: [{ block_kind_id: 'k-juegos', name: 'Juegos', is_sparring: false, seconds: 1800 }],
      sparring_seconds: 0,
      open_mat_seconds: 0,
      classes: 3,
      open_mats: 0,
    }
    stubPage(diego(), NO_TIME, NO_CLASSES, true, [], [mateo, lucia], {
      mateo: { ...NO_TIME, this_month: month, all_time: month },
      lucia: NO_TIME,
    })
    renderMe()

    const his = within(await screen.findByRole('region', { name: copy.training.theirs('Mateo Morales') }))
    expect(his.getByRole('img', { name: 'Gris, 2 grados' })).toBeInTheDocument()
    expect(his.getByText('Gris · 2 grados')).toBeInTheDocument()
    expect(his.getByText('desde 2 abr 2026')).toBeInTheDocument()
    expect(his.getByText(copy.training.classes(3))).toBeInTheDocument()
    expect(his.getByText(copy.training.total(41))).toBeInTheDocument()
    const time = within(await his.findByRole('region', { name: es.matTime.ofDependent('Mateo Morales'), busy: false }))
    expect(time.getByRole('list', { name: es.matTime.byKind })).toHaveTextContent('Juegos30 min')

    // No rank yet: only her classes, and no timed class.
    const hers = within(screen.getByRole('region', { name: copy.training.theirs('Lucía Morales') }))
    expect(hers.queryByText(copy.training.belt)).not.toBeInTheDocument()
    expect(hers.getByText(copy.training.classes(0))).toBeInTheDocument()
    expect(await hers.findByText(es.matTime.emptyTheirs)).toBeInTheDocument()
  })

  it('shows no dependent for someone who is nobody\'s guardian', async () => {
    stubPage(diego())
    renderMe()

    await screen.findByRole('region', { name: copy.training.title })
    expect(screen.queryByRole('region', { name: /^Entrenamiento de / })).not.toBeInTheDocument()
  })

  it('says there is no timed class yet', async () => {
    stubPage(diego())
    renderMe()

    const card = within(await screen.findByRole('region', { name: es.matTime.mine, busy: false }))
    expect(card.getByText(es.matTime.emptyMine)).toBeInTheDocument()
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

  it('lists refunds and adjustments, so the history adds up to what is owed', async () => {
    // Two payments of $20.000 against $45.000, one given back, and a $5.000 discount (#210).
    const at = (day: string) => ({
      claimed_at: null,
      validated_at: `${YEAR}-11-${day}T15:00:00Z`,
      created_at: `${YEAR}-11-${day}T15:00:00Z`,
    })
    const nov = `${YEAR}-11-10`
    stubPage(
      diego({
        payments: [
          payment({ id: 'a-2', kind: 'adjustment', amount_clp: -3000, period_start: nov, ...at('06') }),
          payment({ id: 'a-1', kind: 'adjustment', amount_clp: 5000, period_start: nov, ...at('05') }),
          payment({ id: 'r-1', kind: 'refund', amount_clp: 20000, period_start: nov, ...at('04') }),
          payment({ id: 'p-2', amount_clp: 20000, period_start: nov, ...at('03') }),
          payment({
            id: 'c-1',
            kind: 'adjustment',
            amount_clp: 5000,
            period_start: null,
            note: 'Pagó $50.000, quedan $5.000 a favor',
            ...at('02'),
          }),
        ],
      }),
    )
    renderMe()

    const history = within(await screen.findByRole('region', { name: copy.history.title }))
    expect(history.getAllByRole('listitem').map((row) => row.textContent)).toEqual([
      'Recargo noviembrese suma a lo que debes · 6 nov+$3.000',
      'Descuento noviembrese descuenta de lo que debes · 5 nov−$5.000',
      'Devolución noviembrete devolvieron 4 nov−$20.000',
      'Noviembrevalidado 3 nov$20.000',
      'Saldo a favorPagó $50.000, quedan $5.000 a favor · 2 nov$5.000',
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

  it("lists each class's topic and tags, theirs and a dependent's, with hours per tag", async () => {
    const guard = { id: 'guard', name: 'Pasaje de guardia', archived: false }
    const row = { tag_id: 'guard', name: 'Pasaje de guardia', archived: false, classes: 2, minutes: 150 }
    stubPage(diego(), NO_TIME, {
      timezone: 'America/Santiago',
      people: [
        {
          person_id: 'diego',
          name: 'Diego Morales',
          classes: [
            {
              session_id: 's1',
              starts_at: `${YEAR}-11-10T22:00:00Z`,
              duration_minutes: 90,
              class_type_name: 'Fundamentos',
              program_name: 'Adultos',
              topic: 'Pasaje torreando',
              tags: [guard],
            },
            {
              session_id: 's2',
              starts_at: `${YEAR}-11-03T22:00:00Z`,
              duration_minutes: 60,
              class_type_name: 'Fundamentos',
              program_name: 'Adultos',
              topic: null,
              tags: [],
            },
          ],
          this_month: hoursOf([row], 60),
          this_year: hoursOf([{ ...row, classes: 10, minutes: 750 }]),
        },
        {
          person_id: 'juan',
          name: 'Juan Morales',
          classes: [],
          this_month: hoursOf([]),
          this_year: hoursOf([]),
        },
      ],
    })
    renderMe()

    const mine = within(await screen.findByRole('region', { name: copy.classes.title }))
    // The class names the row; its topic follows the day, and one with none says nothing of it (#362).
    expect(mine.getAllByText('Fundamentos')).toHaveLength(2)
    expect(mine.getByText('10 nov · Pasaje torreando')).toBeInTheDocument()
    expect(mine.getByText('3 nov')).toBeInTheDocument()
    expect(mine.getByRole('list', { name: copy.classes.tags })).toHaveTextContent('Pasaje de guardia')
    expect(mine.queryByText(/Sin tema/)).not.toBeInTheDocument()

    const hours = within(screen.getByRole('region', { name: copy.classes.hours }))
    expect(hours.getByText('2,5 h · 2 clases')).toBeInTheDocument()
    expect(hours.getByText(es.tagHours.untagged('1 h'))).toBeInTheDocument()
    await userEvent.click(hours.getByRole('button', { name: es.tagHours.thisYear }))
    expect(hours.getByText('12,5 h · 10 clases')).toBeInTheDocument()

    const son = within(screen.getByRole('region', { name: copy.classes.theirs('Juan Morales') }))
    expect(son.getByText(copy.classes.empty)).toBeInTheDocument()
  })
})

describe('Mis requisitos (#349)', () => {
  const words = copy.requirements

  it('shows none when the gym asks for nothing', async () => {
    stubPage(diego())
    renderMe()

    await screen.findByRole('heading', { level: 1, name: 'Hola, Diego' })
    expect(screen.queryByRole('region', { name: words.title })).not.toBeInTheDocument()
  })

  it('shows their own and a dependent’s, each with its state and dates', async () => {
    stubPage(diego(), NO_TIME, NO_CLASSES, true, [
      {
        person_id: 'diego',
        name: 'Diego Soto',
        requirements: [
          { id: 'w', name: 'Declaración de riesgos firmada', state: 'ok', done_on: '2026-03-01', expires_on: null },
          { id: 'm', name: 'Certificado médico', state: 'expiring', done_on: '2025-12-01', expires_on: '2026-12-01' },
        ],
      },
      {
        person_id: 'tomas',
        name: 'Tomás Soto',
        requirements: [{ id: 'w', name: 'Declaración de riesgos firmada', state: 'pending', done_on: null, expires_on: null }],
      },
    ])
    renderMe()

    const mine = await screen.findByRole('region', { name: words.title })
    expect(within(mine).getByText(words.state.ok)).toBeInTheDocument()
    expect(within(mine).getByText(words.done(es.common.longDayYear('2026-03-01')))).toBeInTheDocument()
    expect(within(mine).getByText(words.state.expiring)).toBeInTheDocument()
    expect(
      within(mine).getByText(`${words.done(es.common.longDayYear('2025-12-01'))} · ${words.until(es.common.longDayYear('2026-12-01'))}`),
    ).toBeInTheDocument()
    const theirs = screen.getByRole('region', { name: words.theirs('Tomás Soto') })
    expect(within(theirs).getByText(words.state.pending)).toBeInTheDocument()
    // Read-only: nothing to record here.
    expect(within(mine).queryByRole('button')).not.toBeInTheDocument()
  })
})
