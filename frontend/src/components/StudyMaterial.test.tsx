import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import { isHttpsLink, linkHost, linksOf, type Material, type MaterialHost } from '../api/studyMaterial'
import { es } from '../i18n/es'
import { StudyMaterial, type Recurring } from './StudyMaterial'

const copy = es.admin.material

const GUARD: Material = {
  id: 'mat-1',
  title: 'Pasaje de guardia',
  body: 'Repasen\nlos tres pasos.',
  links: ['https://www.youtube.com/watch?v=abc'],
  audience: 'plans',
  plans: [{ id: 'plan-kids', name: 'Mensual niños' }],
  session_id: 's-1',
  starts_on: null,
  shared_by_name: 'Profe Prueba',
  created_at: '2026-11-22T12:00:00Z',
  updated_at: null,
}

const PLANS = [
  { id: 'plan-adults', name: 'Mensual adultos', kind: 'monthly', program_id: 'p-1', active: true },
  { id: 'plan-kids', name: 'Mensual niños', kind: 'monthly', program_id: 'p-2', active: true },
]

type Sent = { method: string; path: string; body: unknown }

function stub(listed: Material[]): Sent[] {
  const sent: Sent[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      if (method !== 'GET') {
        sent.push({ method, path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : undefined })
        if (method === 'DELETE') return new Response(null, { status: 204 })
        return Response.json({ ...GUARD, id: 'mat-new' }, { status: method === 'POST' ? 201 : 200 })
      }
      if (url.pathname === '/api/plans') return Response.json(PLANS)
      if (url.pathname.endsWith('/material')) return Response.json(listed)
      return Response.json({ detail: 'Not Found' }, { status: 404 })
    }),
  )
  return sent
}

function show(host: MaterialHost, canShare: boolean, recurring?: Recurring) {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <StudyMaterial host={host} canShare={canShare} recurring={recurring} today="2026-11-22" />
    </QueryClientProvider>,
  )
}

const section = () => screen.getByRole('region', { name: copy.title })

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('links', () => {
  it('takes only https links, one per line', () => {
    expect(linksOf(' https://a.cl/x \n\n https://b.cl ')).toEqual(['https://a.cl/x', 'https://b.cl'])
    expect(isHttpsLink('https://drive.google.com/file/1')).toBe(true)
    expect(isHttpsLink('http://example.com')).toBe(false)
    expect(isHttpsLink('javascript:alert(1)')).toBe(false)
    expect(isHttpsLink('https://exa mple.com')).toBe(false)
    expect(linkHost('https://www.youtube.com/watch?v=abc')).toBe('youtube.com')
  })
})

describe('StudyMaterial', () => {
  it('shows each material with who sees it, who shared it, its text and its links', async () => {
    stub([GUARD])
    show({ kind: 'session', id: 's-1' }, false)

    const region = within(await screen.findByRole('region', { name: copy.title }))
    expect(await region.findByText('Pasaje de guardia')).toBeInTheDocument()
    expect(region.getByText(copy.shownTo('Planes (Mensual niños)'))).toBeInTheDocument()
    expect(region.getByText(copy.sharedBy('Profe Prueba'))).toBeInTheDocument()
    expect(region.getByText(/Repasen/)).toHaveTextContent('Repasen los tres pasos.')
    const link = region.getByRole('link', { name: /youtube\.com/ })
    expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    // Who does not run the class reads it, and changes nothing.
    expect(region.queryByRole('button', { name: copy.add })).not.toBeInTheDocument()
    expect(region.queryByRole('button', { name: copy.remove })).not.toBeInTheDocument()
  })

  it('shares material for the program, after its audience is chosen', async () => {
    const sent = stub([])
    show({ kind: 'session', id: 's-1' }, true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.add }))
    await user.type(screen.getByLabelText(copy.form.title), 'Pasaje de guardia')
    await user.type(screen.getByLabelText(copy.form.links), 'https://www.youtube.com/watch?v=abc')
    await user.click(screen.getByRole('button', { name: copy.form.submit }))
    // Nothing goes out until someone is chosen to see it.
    expect(await screen.findByText(copy.form.audienceMissing)).toBeInTheDocument()
    expect(sent).toEqual([])

    await user.click(screen.getByRole('radio', { name: new RegExp(copy.audience.program) }))
    await user.click(screen.getByRole('button', { name: copy.form.submit }))

    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toEqual({
      method: 'POST',
      path: '/api/sessions/s-1/material',
      body: {
        title: 'Pasaje de guardia',
        body: null,
        links: ['https://www.youtube.com/watch?v=abc'],
        audience: 'program',
        plan_ids: [],
      },
    })
    expect(await within(section()).findByText(copy.shared)).toBeInTheDocument()
  })

  it('opens its form with focus in it, and a refused save focuses what is missing, read with its error (#569)', async () => {
    stub([])
    show({ kind: 'session', id: 's-1' }, true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.add }))
    const title = screen.getByLabelText(copy.form.title)
    expect(title).toHaveFocus()
    expect(title).toHaveAttribute('placeholder', 'Ej.: Repaso de la semana')

    await user.click(screen.getByRole('button', { name: copy.form.submit }))
    expect(title).toHaveFocus()
    expect(title).toHaveAccessibleDescription(copy.form.titleMissing)

    // With a title, the audience is the first thing missing.
    await user.type(title, 'Repaso')
    await user.click(screen.getByRole('button', { name: copy.form.submit }))
    const first = screen.getByRole('radio', { name: new RegExp(copy.audience.attendees) })
    expect(first).toHaveFocus()
    expect(first).toHaveAccessibleDescription(copy.form.audienceMissing)
  })

  it('refuses a cleared Desde with an error, and focuses it (#569)', async () => {
    const sent = stub([])
    show({ kind: 'slot', id: 'slot-1' }, true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.add }))
    await user.type(screen.getByLabelText(copy.form.title), 'Repaso')
    await user.click(screen.getByRole('radio', { name: new RegExp(copy.audience.program) }))
    const from = screen.getByLabelText(copy.form.from)
    await user.clear(from)
    await user.click(screen.getByRole('button', { name: copy.form.submit }))

    expect(from).toHaveFocus()
    expect(from).toHaveAccessibleDescription(copy.form.fromMissing)
    expect(sent).toEqual([])
  })

  it('refuses a link that is not https before sending', async () => {
    const sent = stub([])
    show({ kind: 'session', id: 's-1' }, true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.add }))
    await user.type(screen.getByLabelText(copy.form.title), 'Guardia')
    await user.type(screen.getByLabelText(copy.form.links), 'http://example.com')
    await user.click(screen.getByRole('radio', { name: new RegExp(copy.audience.program) }))
    await user.click(screen.getByRole('button', { name: copy.form.submit }))

    expect(screen.getByText(copy.form.badLinks(1))).toBeInTheDocument()
    expect(sent).toEqual([])
  })

  it('shares on the recurring class from the class date, for some plans', async () => {
    const sent = stub([])
    show({ kind: 'session', id: 's-1' }, true, { slotDate: '2026-11-24' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.add }))
    await user.type(screen.getByLabelText(copy.form.title), 'Ciclo de fuerza')
    await user.click(screen.getByRole('radio', { name: new RegExp(copy.audience.plans) }))
    await user.click(await screen.findByRole('checkbox', { name: 'Mensual niños' }))
    await user.click(screen.getByRole('radio', { name: copy.form.everyClass }))
    expect(screen.getByLabelText(copy.form.from)).toHaveValue('2026-11-24')
    await user.click(screen.getByRole('button', { name: copy.form.submit }))

    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]!.body).toMatchObject({
      audience: 'plans',
      plan_ids: ['plan-kids'],
      recurring: true,
      starts_on: '2026-11-24',
    })
  })

  it('removes material after asking, and says members stop seeing it', async () => {
    const sent = stub([GUARD])
    show({ kind: 'session', id: 's-1' }, true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.remove }))
    expect(screen.getByText(copy.removeConfirm.question('Pasaje de guardia'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: copy.removeConfirm.confirm }))

    await waitFor(() => expect(sent).toEqual([{ method: 'DELETE', path: '/api/material/mat-1', body: undefined }]))
  })

  it('edits only through the material id', async () => {
    const sent = stub([GUARD])
    show({ kind: 'session', id: 's-1' }, true)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: copy.edit }))
    const title = screen.getByLabelText(copy.form.title)
    await user.clear(title)
    await user.type(title, 'Pasaje de guardia, parte 2')
    await user.click(screen.getByRole('button', { name: copy.form.save }))

    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({
      method: 'PATCH',
      path: '/api/material/mat-1',
      body: { title: 'Pasaje de guardia, parte 2', audience: 'plans', plan_ids: ['plan-kids'] },
    })
  })
})
