import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { JoinForm } from '../api/join'
import { ageOn } from '../api/join'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.join

const FORM: JoinForm = { gym: 'Academia Sur', program: null, today: '2026-11-10', human_check_site_key: null }

type Sent = { method: string; path: string; body: Record<string, unknown> | undefined }
type Answer = { status?: number; body?: unknown }

function stubApi({ form = { body: FORM }, submit = { status: 202 } }: { form?: Answer; submit?: Answer } = {}) {
  const sent: Sent[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      const method = init?.method ?? 'GET'
      sent.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const answer = method === 'GET' ? form : submit
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return sent
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

async function fillAdult() {
  await userEvent.type(await screen.findByLabelText(copy.firstName), 'Ana')
  await userEvent.type(screen.getByLabelText(copy.lastName), 'Pérez')
  await userEvent.type(screen.getByLabelText(copy.rut), '7.654.321-6')
  fireEvent.change(screen.getByLabelText(copy.dob), { target: { value: '1990-05-20' } })
  await userEvent.type(screen.getByLabelText(copy.phone), '9 8765 4321')
  await userEvent.type(screen.getByLabelText(copy.email), 'ana@example.cl')
  await userEvent.click(screen.getByLabelText(copy.consent))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Inscríbete', () => {
  it('shows the gym and sends an adult’s details, with no session', async () => {
    const sent = stubApi()
    const router = renderAt('/unirse/tok-123456789012345678901')

    expect(await screen.findByRole('heading', { name: copy.title('Academia Sur') })).toBeInTheDocument()
    await fillAdult()
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.done)
    expect(router.state.location.pathname).toBe('/unirse/tok-123456789012345678901')
    expect(sent.map((s) => `${s.method} ${s.path}`)).toEqual([
      'GET /api/join/tok-123456789012345678901',
      'POST /api/join/tok-123456789012345678901',
    ])
    expect(sent[1]!.body).toEqual({
      first_name: 'Ana',
      last_name: 'Pérez',
      rut: '7.654.321-6',
      phone: '9 8765 4321',
      email: 'ana@example.cl',
      dob: '1990-05-20',
      guardian_name: null,
      guardian_phone: null,
      guardian_email: null,
      no_whatsapp: false,
      consent: true,
      website: '',
      human_check_token: null,
    })
  })

  it('sends no RUT and no phone for someone without either who has no WhatsApp', async () => {
    const sent = stubApi()
    renderAt('/unirse/tok-123456789012345678901')

    await userEvent.type(await screen.findByLabelText(copy.firstName), 'Ana')
    await userEvent.type(screen.getByLabelText(copy.lastName), 'Pérez')
    fireEvent.change(screen.getByLabelText(copy.dob), { target: { value: '1990-05-20' } })
    await userEvent.type(screen.getByLabelText(copy.email), 'ana@example.cl')
    await userEvent.click(screen.getByRole('checkbox', { name: copy.noWhatsapp }))
    await userEvent.click(screen.getByRole('checkbox', { name: copy.consent }))
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    await screen.findByRole('status')
    expect(sent[1]!.body).toMatchObject({ rut: null, phone: null, email: 'ana@example.cl', no_whatsapp: true })
  })

  it('asks a minor for their guardian, on the gym’s today', async () => {
    const sent = stubApi()
    renderAt('/unirse/tok-123456789012345678901')

    await userEvent.type(await screen.findByLabelText(copy.firstName), 'Juan')
    expect(screen.queryByLabelText(copy.guardianName)).not.toBeInTheDocument()
    // Eighteen tomorrow, on the gym's today.
    fireEvent.change(screen.getByLabelText(copy.dob), { target: { value: '2008-11-11' } })

    expect(screen.getByRole('group', { name: copy.guardianTitle })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(copy.guardianName), 'Marta')
    await userEvent.type(screen.getByLabelText(copy.guardianPhone), '912345678')
    await userEvent.type(screen.getByLabelText(copy.guardianEmail), 'marta@example.cl')
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    await screen.findByRole('status')
    expect(sent[1]!.body).toMatchObject({
      dob: '2008-11-11',
      phone: null,
      email: null,
      guardian_name: 'Marta',
      guardian_phone: '912345678',
      guardian_email: 'marta@example.cl',
    })
  })

  it('stops asking for a guardian once the birth date makes them an adult', async () => {
    stubApi()
    renderAt('/unirse/tok-123456789012345678901')

    const dob = await screen.findByLabelText(copy.dob)
    fireEvent.change(dob, { target: { value: '2008-11-11' } })
    expect(screen.getByLabelText(copy.guardianName)).toBeInTheDocument()
    fireEvent.change(dob, { target: { value: '2008-11-10' } })
    expect(screen.queryByLabelText(copy.guardianName)).not.toBeInTheDocument()
  })

  it('marks the fields the API refused', async () => {
    stubApi({
      submit: {
        status: 422,
        body: {
          detail: [
            { type: 'value_error', loc: ['body', 'rut'], msg: 'x' },
            { type: 'missing', loc: ['body', 'guardian_email'], msg: 'x' },
          ],
        },
      },
    })
    renderAt('/unirse/tok-123456789012345678901')

    await fillAdult()
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.invalidFields)
    expect(screen.getByLabelText(copy.rut)).toHaveAccessibleDescription(`${copy.rutHint} ${copy.refused.rut}`)
  })

  it('says when there were too many submissions', async () => {
    stubApi({ submit: { status: 429, body: { detail: 'too many' } } })
    renderAt('/unirse/tok-123456789012345678901')

    await fillAdult()
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.tooMany)
  })

  it('says a link that no longer works is not valid', async () => {
    stubApi({ form: { status: 404, body: { detail: 'invalid_link' } } })
    renderAt('/unirse/tok-123456789012345678901')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(screen.queryByLabelText(copy.firstName)).not.toBeInTheDocument()
  })

  it('keeps the honeypot out of sight and out of the tab order', async () => {
    stubApi()
    renderAt('/unirse/tok-123456789012345678901')

    await screen.findByLabelText(copy.firstName)
    const honeypot = document.querySelector<HTMLInputElement>('input[name="website"]')
    expect(honeypot).not.toBeNull()
    expect(honeypot!.tabIndex).toBe(-1)
    expect(screen.queryByRole('textbox', { name: copy.honeypot })).not.toBeInTheDocument()
  })

  it('shows the program the link is for', async () => {
    stubApi({ form: { body: { ...FORM, program: 'Kids' } } })
    renderAt('/unirse/tok-123456789012345678901')

    expect(await screen.findByText(copy.program('Kids'))).toBeInTheDocument()
  })
})

describe('Inscríbete with a human check', () => {
  afterEach(() => {
    delete window.turnstile
  })

  it('sends the widget’s token, and starts the widget over after a refusal', async () => {
    const tokens: ((token: string) => void)[] = []
    window.turnstile = {
      render: vi.fn((_element: HTMLElement, options: { callback: (token: string) => void }) => {
        tokens.push(options.callback)
        return `w${tokens.length}`
      }),
      remove: vi.fn(),
    } as unknown as NonNullable<typeof window.turnstile>
    const sent = stubApi({
      form: { body: { ...FORM, human_check_site_key: 'site' } },
      submit: { status: 400, body: { detail: 'human_check_failed' } },
    })
    renderAt('/unirse/tok-123456789012345678901')

    await fillAdult()
    await vi.waitFor(() => expect(tokens).toHaveLength(1))
    tokens[0]!('primero')
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.humanCheck)
    expect(sent[1]!.body).toMatchObject({ human_check_token: 'primero' })
    // A fresh widget, and the spent token is not sent again.
    await vi.waitFor(() => expect(tokens).toHaveLength(2))
    expect(window.turnstile!.remove).toHaveBeenCalledWith('w1')
    await userEvent.click(screen.getByRole('button', { name: copy.submit }))
    await vi.waitFor(() => expect(sent).toHaveLength(3))
    expect(sent[2]!.body).toMatchObject({ human_check_token: null })
  })
})

describe('ageOn', () => {
  it('counts whole years to the day', () => {
    expect(ageOn('2008-11-10', '2026-11-10')).toBe(18)
    expect(ageOn('2008-11-11', '2026-11-10')).toBe(17)
    expect(ageOn('2008-02-29', '2026-02-28')).toBe(17)
    expect(ageOn('2008-02-29', '2026-03-01')).toBe(18)
    expect(ageOn('', '2026-03-01')).toBeNull()
  })
})
