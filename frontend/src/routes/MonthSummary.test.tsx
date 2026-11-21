import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MonthSummary } from '../api/summary'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.summary

const NONE = { payments: 0, amount_clp: 0 }

const EMPTY: MonthSummary = {
  month: '2026-11-01',
  months: ['2026-11-01', '2026-10-01'],
  since: null,
  whatsapp: true,
  income_clp: 0,
  income_payments: 0,
  reminder_emails: 0,
  reminder_whatsapps: 0,
  after_reminders: { total: NONE, emails_only: NONE, after_whatsapp: NONE, income_percent: null },
  nudges: { nudged: 0, back: 0, percent: null },
  emails_sent: 0,
  own_payments: { by_members: 0, payments: 0, percent: null },
  proofs: { reviewed: 0, median_minutes: null },
  reactivated: 0,
  trials_converted: 0,
}

const NOVEMBER: MonthSummary = {
  ...EMPTY,
  income_clp: 6_900_000,
  income_payments: 52,
  reminder_emails: 64,
  after_reminders: {
    total: { payments: 31, amount_clp: 1_240_000 },
    emails_only: { payments: 23, amount_clp: 900_000 },
    after_whatsapp: { payments: 8, amount_clp: 340_000 },
    income_percent: 18,
  },
  nudges: { nudged: 12, back: 5, percent: 42 },
  emails_sent: 112,
  own_payments: { by_members: 38, payments: 52, percent: 73 },
  proofs: { reviewed: 38, median_minutes: 290 },
  reactivated: 3,
  trials_converted: 4,
}

type Call = { method: string; path: string }

function stubApi(role: string, summary: (month: string | null) => MonthSummary = () => NOVEMBER) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push({ method: init?.method ?? 'GET', path: url.pathname + url.search })
      let body: unknown = { detail: 'Not Found' }
      let status = 404
      if (url.pathname === '/api/me/role') {
        body = { ...asRole(role), person_id: 'me', gym_name: 'Academia Sur' }
        status = 200
      } else if (url.pathname === '/api/summary') {
        body = summary(url.searchParams.get('month'))
        status = 200
      }
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Resumen del mes', () => {
  it('says what came after the reminders, as part of what was collected', async () => {
    stubApi('owner')
    renderAt('/admin/pagos/resumen')

    expect(await screen.findByText(/Rakin envió 64 recordatorios de pago por correo\./)).toHaveTextContent(
      'Después de ellos llegaron 31 pagos atrasados, por $1.240.000: el 18 % de lo cobrado en el mes. ' +
        '23 llegaron sin que nadie del equipo escribiera. 8 llegaron después de un WhatsApp del equipo.',
    )
    expect(
      screen.getByText(
        'El equipo escribió por WhatsApp a 12 alumnos que no venían hace 14 días o más. ' +
          '5 de 12 volvieron a clases dentro de dos semanas (42 %).',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('38 de 52 pagos los informaron los mismos alumnos, con su comprobante.')).toBeInTheDocument()
    expect(screen.getByText('El equipo revisó 38 comprobantes; la mitad, en 5 horas o menos.')).toBeInTheDocument()
    expect(screen.getByText('3 planes vencidos volvieron a activarse.')).toBeInTheDocument()
    expect(screen.getByText(copy.how.title)).toBeInTheDocument()
    // Never "gracias a" or "recuperado".
    expect(document.body.textContent).not.toMatch(/gracias a Rakin|recuper/i)
  })

  it('writes "N de M" and no percentage under 5', async () => {
    stubApi('owner', () => ({
      ...NOVEMBER,
      income_payments: 3,
      after_reminders: { ...NOVEMBER.after_reminders, total: { payments: 1, amount_clp: 30_000 }, income_percent: null },
      nudges: { nudged: 3, back: 1, percent: null },
    }))
    renderAt('/admin/pagos/resumen')

    expect(await screen.findByText(/llegó 1 pago atrasado, por \$30\.000: de \$6\.900\.000 cobrados en el mes\./)).toBeInTheDocument()
    expect(screen.getByText(/1 de 3 volvió a clases dentro de dos semanas\.$/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/33 %/)
  })

  it('says when no reminder has gone out yet, and shows no figures it does not have', async () => {
    stubApi('owner', () => EMPTY)
    renderAt('/admin/pagos/resumen')

    expect(await screen.findByText(copy.noReminders)).toBeInTheDocument()
    expect(screen.queryByText(/volvieron|comprobantes|planes vencidos/)).toBeNull()
  })

  it('points to Ajustes with WhatsApp off, and says when a first month began', async () => {
    stubApi('owner', () => ({ ...NOVEMBER, whatsapp: false, since: '2026-11-12' }))
    renderAt('/admin/pagos/resumen')

    expect(await screen.findByText(copy.whatsappOff)).toBeInTheDocument()
    expect(screen.queryByText(/escribió por WhatsApp a/)).toBeNull()
    expect(screen.getByText('Desde el 12 de noviembre')).toBeInTheDocument()
  })

  it('asks for the month picked', async () => {
    const user = userEvent.setup()
    const calls = stubApi('owner', (month) => (month === '2026-10' ? { ...EMPTY, month: '2026-10-01' } : NOVEMBER))
    renderAt('/admin/pagos/resumen')
    await screen.findByText(/Rakin envió 64 recordatorios/)

    await user.selectOptions(screen.getByLabelText(copy.month), '2026-10-01')

    expect(await screen.findByText(copy.noRemindersPast)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/summary?month=2026-10')).toBe(true)
  })

  it('tells a coach it is not for them and asks the API nothing', async () => {
    const calls = stubApi('coach')
    renderAt('/admin/pagos/resumen')

    expect(await screen.findByText(es.admin.payments.coachesOnly)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/summary'))).toBe(false)
  })
})
