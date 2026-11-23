import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MyData, PersonData } from '../api/myData'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.me.myData

function person(id: string, name: string, over: Partial<PersonData> = {}): PersonData {
  return {
    person_id: id,
    record: {
      name,
      rut: '12345678-5',
      email: `${id}@example.cl`,
      phone: '+56911112222',
      dob: '1990-04-02',
      no_whatsapp: false,
      member_since: null,
      prior_classes: null,
      left_on: null,
      left_reason: null,
      added_at: '2026-03-01T12:00:00Z',
      updated_at: '2026-03-01T12:00:00Z',
    },
    guardians: [],
    dependents: [],
    fields: [],
    memberships: [],
    plan_events: [],
    freezes: [],
    freeze_requests: [],
    periods: [],
    extra_charges: [],
    entries: [],
    history_payments: [],
    attendance: [],
    grades: [],
    requirements: [],
    consents: [],
    messages: [],
    charge_groups: [],
    unsubscribed_at: null,
    staff: null,
    ...over,
  }
}

const DATA: MyData = {
  exported_at: '2026-11-23T15:00:00Z',
  gym: {
    name: 'Academia Sur',
    timezone: 'America/Santiago',
    privacy: { legal_name: 'Academia Sur SpA', rut: '76123456-0', email: 'privacidad@example.cl', address: null },
  },
  people: [
    person('ana', 'Ana Rojas', {
      dependents: [{ person_id: 'tomas', name: 'Tomás Rojas' }],
      fields: [
        { key: 'contacto', label: 'Contacto de emergencia', value: 'Luis, +56933334444', sensitive: false, archived: false },
        { key: 'salud', label: 'Condición médica', value: 'Asma', sensitive: true, archived: false },
      ],
      memberships: [
        {
          id: 'm1',
          plan_name: 'Mensual adultos',
          status: 'active',
          started_at: '2026-03-01T12:00:00Z',
          current_period_end: '2026-11-30',
          credits_remaining: null,
          discount_pct: null,
          discount_reason: null,
          next_plan_name: null,
          next_plan_from: null,
          cancelled_at: null,
          cancel_reason: null,
          cancel_undone_at: null,
          reactivated_at: null,
          voided_at: null,
          void_reason: null,
          created_at: '2026-03-01T12:00:00Z',
        },
      ],
      history_payments: [
        {
          id: 'h1',
          paid_on: '2019-05-03',
          amount_clp: 30000,
          method: 'cash',
          covers_month: null,
          plan_name: 'Plan antiguo',
          note: 'Pagó en efectivo',
          source: 'manual',
          created_at: '2026-03-01T12:00:00Z',
        },
      ],
    }),
    person('tomas', 'Tomás Rojas', { guardians: [{ person_id: 'ana', name: 'Ana Rojas' }] }),
  ],
}

function stubApi(data: MyData) {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/me/data') return Response.json(data)
      if (url.pathname === '/api/me/role') {
        return Response.json({ ...asRole(null), person_id: 'ana', gym_name: 'Academia Sur', terms: 'current' })
      }
      return Response.json({ detail: 'Not Found' }, { status: 404 })
    }),
  )
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Mis datos (#371)', () => {
  it('shows the student and each dependent, with where to download and fix it all', async () => {
    stubApi(DATA)
    renderAt('/me/datos')

    const mine = within(await screen.findByRole('region', { name: copy.mine }))
    expect(screen.getByRole('region', { name: copy.theirs('Tomás Rojas') })).toBeInTheDocument()
    expect(screen.getByText(copy.introFamily)).toBeInTheDocument()

    // The ficha is open; RUT as Chile writes it.
    expect(mine.getByText('Ana Rojas')).toBeVisible()
    expect(mine.getByText('12.345.678-5')).toBeVisible()

    // Sensitive fields are the member's own: shown, and marked.
    await userEvent.click(mine.getByText(copy.count(copy.parts.fields, 2)))
    expect(mine.getByText('Condición médica: Asma')).toBeVisible()
    expect(mine.getByText(copy.field.sensitive)).toBeVisible()

    // The notes the staff wrote about them are theirs too.
    await userEvent.click(mine.getByText(copy.count(copy.parts.historyPayments, 1)))
    expect(mine.getByText(/Pagó en efectivo/)).toBeVisible()
    expect(mine.getByText(copy.count(copy.parts.dependents, 1))).toBeInTheDocument()
    // A part with nothing in it is not shown.
    expect(mine.queryByText(copy.count(copy.parts.attendance, 0))).not.toBeInTheDocument()

    const download = screen.getByRole('link', { name: copy.download })
    expect(download).toHaveAttribute('href', '/api/me/data?download=1')
    expect(download).toHaveAttribute('download')
    expect(screen.getByRole('link', { name: 'privacidad@example.cl' })).toHaveAttribute(
      'href',
      'mailto:privacidad@example.cl',
    )
    expect(screen.getByText(es.privacy.retention)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: copy.purposeLink })).toHaveAttribute('href', '/privacidad')
  })

  it('asks the gym itself to fix a datum while it has no privacy email', async () => {
    stubApi({ ...DATA, gym: { ...DATA.gym, privacy: null }, people: [person('ana', 'Ana Rojas')] })
    renderAt('/me/datos')

    expect(await screen.findByText(copy.fixNoEmail)).toBeInTheDocument()
    expect(screen.getByText(copy.intro)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.theirs('Tomás Rojas') })).not.toBeInTheDocument()
  })

  it('is reached from the student page', async () => {
    stubApi(DATA)
    renderAt('/me/datos')

    expect(await screen.findByRole('link', { name: copy.link })).toHaveAttribute('href', '/me/datos')
    expect(screen.getByRole('link', { name: copy.back })).toHaveAttribute('href', '/me')
  })
})
