import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GradingPreset, GradingScheme } from '../api/grading'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const settings = es.admin.settings
const copy = settings.grading

const stripes = [
  { key: '0', label: 'Sin grados', target: null },
  { key: '1', label: '1 grado', target: null },
]
const SCHEME: GradingScheme = {
  ranks: [
    { key: 'white', label: 'Blanca', target: 120, colors: ['#f4f4f1'], sub_ranks: stripes },
    { key: 'blue', label: 'Azul', target: null, sub_ranks: stripes },
  ],
  kids_ladder: [],
  goal_metric: 'classes_since_promotion',
}
const PRESETS: GradingPreset[] = [
  {
    key: 'judo-karate',
    label: 'Judo / karate',
    scheme: {
      ranks: [
        { key: 'kyu-2', label: '2.º kyu', target: null, colors: [], sub_ranks: [] },
        { key: 'kyu-1', label: '1.º kyu', target: null, colors: [], sub_ranks: [] },
      ],
      kids_ladder: [],
      goal_metric: 'time_in_rank',
    },
  },
  {
    key: 'none',
    label: 'Sin grados',
    scheme: { ranks: [], kids_ladder: [], goal_metric: null },
  },
]

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({ scheme, save }: { scheme?: Answer; save?: Answer } = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: url.pathname, body })
      const answer: Answer =
        url.pathname === '/api/me/role'
          ? { body: { role: 'admin' } }
          : url.pathname === '/api/gym/grading-scheme/presets'
            ? { body: PRESETS }
            : url.pathname === '/api/gym/grading-scheme' && method === 'GET'
              ? (scheme ?? { body: SCHEME })
              : url.pathname === '/api/gym/grading-scheme' && method === 'PUT'
                ? (save ?? { body })
                : { status: 404, body: { detail: 'Not Found' } }
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

function renderGrading() {
  const queryClient = createQueryClient()
  const router = createAppRouter(
    { queryClient },
    createMemoryHistory({ initialEntries: ['/admin/ajustes/graduacion'] }),
  )
  render(<App queryClient={queryClient} router={router} />)
}

const puts = (calls: Call[]) => calls.filter((c) => c.method === 'PUT').map((c) => c.body as GradingScheme)
const ladder = (name: string) => screen.getByRole('group', { name })
const rank = (name: string, n: number) => within(ladder(name)).getByRole('listitem', { name: copy.rank(n) })
const save = () => userEvent.click(screen.getByRole('button', { name: copy.submit }))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes: Graduación', () => {
  it('edits ranks, sub-ranks and targets, keeping the keys promotions name and giving new ones theirs', async () => {
    const calls = stubApi()
    renderGrading()

    const white = await screen.findByRole('listitem', { name: copy.rank(1) })
    expect(within(white).getByLabelText(copy.rank(1))).toHaveValue('Blanca')
    expect(within(white).getAllByLabelText(copy.target.classes_since_promotion)[0]).toHaveValue('120')

    // A rename keeps the key.
    const label = within(white).getByLabelText(copy.rank(1))
    await userEvent.clear(label)
    await userEvent.type(label, 'Blanca adultos')
    // A sub-rank's own target.
    await userEvent.click(within(white).getByText(copy.subRanks(2)))
    const second = within(white).getAllByRole('listitem')[1]!
    await userEvent.type(within(second).getByLabelText(copy.subTarget.classes_since_promotion), '40')
    await userEvent.click(within(white).getByRole('button', { name: copy.addSubRank }))
    await userEvent.type(within(white).getByLabelText(copy.subRank(3)), '2 grados')

    // A new rank, and one in the kids ladder whose name would make the same key.
    const ranks = ladder(copy.ladders.ranks)
    await userEvent.click(within(ranks).getByRole('button', { name: copy.addRank }))
    await userEvent.type(within(rank(copy.ladders.ranks, 3)).getByLabelText(copy.rank(3)), 'Morada')
    await userEvent.click(
      within(ladder(copy.ladders.kids_ladder)).getByRole('button', {
        name: copy.addRank,
      }),
    )
    await userEvent.type(within(rank(copy.ladders.kids_ladder, 1)).getByLabelText(copy.rank(1)), 'Morada')
    await save()

    expect(await screen.findByRole('status')).toHaveTextContent(copy.saved)
    const [sent] = puts(calls)
    expect(sent!.ranks.map((r) => [r.key, r.label, r.target])).toEqual([
      ['white', 'Blanca adultos', 120],
      ['blue', 'Azul', null],
      ['morada', 'Morada', null],
    ])
    expect(sent!.ranks[0]!.sub_ranks).toEqual([
      { key: '0', label: 'Sin grados', target: null },
      { key: '1', label: '1 grado', target: 40 },
      { key: '2-grados', label: '2 grados', target: null },
    ])
    expect(sent!.kids_ladder.map((r) => r.key)).toEqual(['morada-2'])
    expect(sent!.goal_metric).toBe('classes_since_promotion')
  })

  it('gives a rank its belt colours, a second for a two-tone belt, and takes them away', async () => {
    const calls = stubApi()
    renderGrading()
    const words = copy.belt

    // A rank with a colour is drawn as its belt, every stripe on the bar.
    const white = await screen.findByRole('listitem', { name: copy.rank(1) })
    const whiteBelt = within(white).getByRole('group', { name: words.title })
    expect(within(whiteBelt).getByRole('img', { name: words.preview('Blanca') })).toBeInTheDocument()
    expect(within(whiteBelt).getByLabelText(words.main)).toHaveValue('#f4f4f1')
    await userEvent.click(within(whiteBelt).getByRole('button', { name: words.addTone }))
    fireEvent.input(within(whiteBelt).getByLabelText(words.tone), { target: { value: '#1b1b1b' } })

    // One without shows as its name until it is given one.
    const blue = within(rank(copy.ladders.ranks, 2)).getByRole('group', { name: words.title })
    expect(within(blue).getByText(words.none)).toBeInTheDocument()
    expect(within(blue).queryByRole('img')).not.toBeInTheDocument()
    await userEvent.click(within(blue).getByRole('button', { name: words.add }))
    fireEvent.input(within(blue).getByLabelText(words.main), { target: { value: '#1f4fa3' } })
    await save()

    await screen.findByText(copy.saved)
    expect(puts(calls)[0]!.ranks.map((r) => r.colors)).toEqual([['#f4f4f1', '#1b1b1b'], ['#1f4fa3']])

    // The saved scheme reloads the form.
    const belt = (n: number) => within(rank(copy.ladders.ranks, n)).getByRole('group', { name: words.title })
    await userEvent.click(within(belt(1)).getByRole('button', { name: words.removeTone }))
    await userEvent.click(within(belt(2)).getByRole('button', { name: words.remove }))
    await save()
    await vi.waitFor(() => expect(puts(calls)).toHaveLength(2))
    expect(puts(calls)[1]!.ranks.map((r) => r.colors)).toEqual([['#f4f4f1'], []])
  })

  it('moves and removes ranks', async () => {
    const calls = stubApi()
    renderGrading()

    await screen.findByRole('listitem', { name: copy.rank(1) })
    await userEvent.click(screen.getByRole('button', { name: copy.moveDown('Blanca') }))
    expect(screen.getByRole('button', { name: copy.moveUp('Azul') })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: copy.remove('Blanca') }))
    await save()

    await screen.findByRole('status')
    expect(puts(calls)[0]!.ranks.map((r) => r.key)).toEqual(['blue'])
  })

  it('applies a preset as a starting point, saved only with the scheme', async () => {
    const calls = stubApi()
    renderGrading()

    const start = await screen.findByRole('group', { name: copy.start })
    await userEvent.selectOptions(await within(start).findByLabelText(copy.preset), 'Judo / karate')
    await userEvent.click(within(start).getByRole('button', { name: copy.apply }))

    expect(screen.getByRole('status')).toHaveTextContent(copy.applied('Judo / karate'))
    expect(screen.getByLabelText(copy.goalMetric)).toHaveValue('time_in_rank')
    expect(within(rank(copy.ladders.ranks, 1)).getByLabelText(copy.rank(1))).toHaveValue('2.º kyu')
    // Months in rank, for this metric.
    expect(within(rank(copy.ladders.ranks, 1)).getByLabelText(copy.target.time_in_rank)).toBeInTheDocument()
    expect(puts(calls)).toEqual([])

    await save()
    await screen.findByText(copy.saved)
    expect(puts(calls)).toEqual([PRESETS[0]!.scheme])
  })

  it('sends no targets when nothing is measured', async () => {
    const calls = stubApi()
    renderGrading()

    await screen.findByRole('listitem', { name: copy.rank(1) })
    await userEvent.selectOptions(screen.getByLabelText(copy.goalMetric), copy.goalMetrics.none)
    expect(screen.queryByLabelText(copy.target.classes_since_promotion)).not.toBeInTheDocument()
    await save()

    await screen.findByText(copy.saved)
    const [sent] = puts(calls)
    expect(sent!.goal_metric).toBeNull()
    expect(sent!.ranks[0]!.target).toBeNull()
  })

  it("puts the API's refusals under the fields they name, opening a rank's sub-ranks for them", async () => {
    stubApi({
      save: {
        status: 422,
        body: {
          detail: [
            {
              loc: ['body', 'ranks', 1, 'label'],
              type: 'string_too_short',
              msg: '',
            },
            {
              loc: ['body', 'ranks', 0, 'sub_ranks', 1, 'target'],
              type: 'greater_than_equal',
              msg: '',
            },
          ],
        },
      },
    })
    renderGrading()

    await screen.findByRole('listitem', { name: copy.rank(1) })
    await userEvent.clear(within(rank(copy.ladders.ranks, 2)).getByLabelText(copy.rank(2)))
    await save()

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(within(rank(copy.ladders.ranks, 2)).getByLabelText(copy.rank(2))).toHaveAccessibleDescription(
      settings.invalid.required,
    )
    const sub = within(rank(copy.ladders.ranks, 1)).getAllByRole('listitem')[1]!
    expect(sub.closest('details')).toHaveAttribute('open')
    expect(within(sub).getByLabelText(copy.subTarget.classes_since_promotion)).toHaveAccessibleDescription(
      copy.range.target,
    )
  })

  it('says a scheme refused as a whole needs ranks to measure', async () => {
    stubApi({
      scheme: { body: { ranks: [], kids_ladder: [], goal_metric: null } },
      save: {
        status: 422,
        body: { detail: [{ loc: ['body'], type: 'value_error', msg: '' }] },
      },
    })
    renderGrading()

    expect(await screen.findAllByText(copy.emptyLadder)).toHaveLength(2)
    await userEvent.selectOptions(screen.getByLabelText(copy.goalMetric), copy.goalMetrics.time_in_rank)
    await save()

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.schemeInvalid)
  })

  it('offers to re-apply a preset when the stored scheme no longer fits', async () => {
    const calls = stubApi({
      scheme: {
        status: 409,
        body: { detail: { code: 'grading_scheme_invalid' } },
      },
    })
    renderGrading()

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.stale)
    const start = screen.getByRole('group', { name: copy.start })
    await userEvent.selectOptions(await within(start).findByLabelText(copy.preset), 'Sin grados')
    await userEvent.click(within(start).getByRole('button', { name: copy.reapply }))
    expect(screen.getByRole('alert')).toHaveTextContent(copy.stale)
    await save()

    await screen.findByText(copy.saved)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(puts(calls)).toEqual([PRESETS[1]!.scheme])
  })

  it('says so when the scheme cannot be loaded for another reason', async () => {
    stubApi({ scheme: { status: 500, body: { detail: 'boom' } } })
    renderGrading()

    expect(await screen.findByRole('alert', {}, { timeout: 5000 })).toHaveTextContent(copy.error)
  })
})
