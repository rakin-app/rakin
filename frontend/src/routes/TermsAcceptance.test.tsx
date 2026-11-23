import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { TermsPage, TermsState } from '../api/terms'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'
import { declarationOf, demoted, validRut } from './TermsAcceptance'

const copy = es.terms

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

type Answer = { status: number; body?: unknown }
type Call = { path: string; method: string; body: unknown }

function stubApi(answer: (call: Call) => Answer | undefined) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined }
      calls.push(call)
      const { status, body } = answer(call) ?? { status: 404, body: { detail: 'Not Found' } }
      return new Response(JSON.stringify(body ?? {}), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

function me(role: string, terms: TermsState) {
  return {
    ...asRole(role),
    person_id: 'me',
    name: 'Dueña Norte',
    email: null,
    gym_name: 'Academia Norte',
    student_page: false,
    theme: 'bosque',
    gym_logo: null,
    terms,
    titular_name: 'Dueña Norte',
  }
}

const PAGE: TermsPage = {
  state: 'pending',
  gym_name: 'Academia Norte',
  documents: [
    {
      key: 'service',
      title: 'Términos de servicio',
      version: '2026-11-20',
      html: '<h1 id="ts-terminos">Términos de servicio</h1><p>Entre Rakin y <span class="legal-blank" data-blank="legal_name">[Razón social del gimnasio]</span>.</p>',
      changes: [],
    },
    {
      key: 'processor',
      title: 'Términos de encargo',
      version: '2026-11-20',
      html: '<h2>Anexo A</h2><p>Contacto: <span class="legal-blank" data-blank="contact_name">[nombre y cargo]</span>.</p>',
      changes: [],
    },
  ],
  prefill: { representative: 'Dueña Norte' },
  declarations: {
    service: 'Acepto los Términos de servicio en nombre de {legal_name}, y declaro que puedo representarla.',
    processor: 'Acepto los Términos de encargo en nombre de {legal_name}, incluida la autorización a cada subencargado del Anexo A: Hetzner y Resend.',
  },
  subprocessors: ['Hetzner', 'Resend'],
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

async function fillForm() {
  await userEvent.type(screen.getByLabelText(copy.legalName), 'Norte SpA')
  await userEvent.type(screen.getByLabelText(copy.rut), '76.123.456-0')
  await userEvent.type(screen.getByLabelText(copy.address), 'Av. Siempre Viva 123')
  await userEvent.type(screen.getByLabelText(copy.contactName), 'Ana Pérez, gerente')
  await userEvent.type(screen.getByLabelText(copy.contactEmail), 'ana@norte.cl')
  await userEvent.type(screen.getByLabelText(copy.contactPhone), '+56 9 1234 5678')
}

describe('the terms gate (#499)', () => {
  it('shows a pending gym’s titular only the acceptance page, on any admin path, until they accept', async () => {
    let terms: TermsState = 'pending'
    const calls = stubApi((call) => {
      if (call.path === '/api/me/role') return { status: 200, body: me('owner', terms) }
      if (call.path === '/api/terms') return { status: 200, body: PAGE }
      if (call.path === '/api/terms/accept') {
        terms = 'current'
        return { status: 201, body: { id: 'a', accepted_at: '2026-11-20T15:00:00Z' } }
      }
      return undefined
    })
    const router = renderAt('/admin/alumnos')

    expect(await screen.findByRole('heading', { name: copy.title })).toBeInTheDocument()
    await screen.findByLabelText(copy.legalName)
    expect(screen.queryByRole('navigation', { name: es.nav.label })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: es.signOut.label })).toBeInTheDocument()
    // Both texts, before the boxes, with a way to keep them.
    expect(screen.getByText('Términos de servicio', { selector: 'summary *' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.print })).toBeInTheDocument()

    const button = screen.getByRole('button', { name: copy.accept })
    expect(button).toBeDisabled()
    // Until the razón social is typed, the boxes accept in the gym's name, never in a
    // bracketed label (#570).
    const boxes = screen.getAllByRole('checkbox').map((box) => box.closest('label')!.textContent)
    expect(boxes[0]).toContain(`en nombre de ${copy.thePlace()}, y declaro`)
    for (const text of boxes) expect(text).not.toMatch(/\[|\]/)
    await fillForm()
    // The blanks in the text show what is typed, as the server will render them.
    expect(document.querySelector('[data-blank="legal_name"]')!.textContent).toBe('Norte SpA')
    const [service, processor] = screen.getAllByRole('checkbox')
    expect(service).not.toBeChecked()
    expect(screen.getByText(/en nombre de Norte SpA, y declaro que puedo representarla/)).toBeInTheDocument()
    await userEvent.click(service!)
    expect(button).toBeDisabled()
    await userEvent.click(processor!)
    expect(button).toBeEnabled()
    await userEvent.click(button)

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin'))
    expect(await screen.findByRole('navigation', { name: es.nav.label })).toBeInTheDocument()
    const [sent] = calls.filter((c) => c.path === '/api/terms/accept')
    expect(sent!.body).toEqual({
      service_version: '2026-11-20',
      processor_version: '2026-11-20',
      filled: {
        legal_name: 'Norte SpA',
        rut: '76.123.456-0',
        address: 'Av. Siempre Viva 123',
        representative: 'Dueña Norte',
        breach_contacts: [{ name_and_role: 'Ana Pérez, gerente', email: 'ana@norte.cl', phone: '+56 9 1234 5678' }],
      },
      accept_service: true,
      accept_processor: true,
    })
  })

  it('shows each text as a card that opens to be read, under the page’s one h1 (#570)', async () => {
    stubApi((call) => {
      if (call.path === '/api/me/role') return { status: 200, body: me('owner', 'pending') }
      if (call.path === '/api/terms') return { status: 200, body: PAGE }
      return undefined
    })
    renderAt('/admin')

    await screen.findByLabelText(copy.legalName)
    const titles = [...document.querySelectorAll('h1')].map((h) => h.textContent)
    expect(titles).toEqual([copy.title])
    // The texts' own headings, one level under the section's h2 and more.
    expect(document.querySelector('.legal h3')!.textContent).toBe('Términos de servicio')
    expect(document.querySelector('.legal h4')!.textContent).toBe('Anexo A')
    const summaries = [...document.querySelectorAll('summary')]
    expect(summaries.map((s) => s.textContent)).toEqual([
      `Términos de servicio${copy.version('2026-11-20')}${copy.read}`,
      `Términos de encargo${copy.version('2026-11-20')}${copy.read}`,
    ])
    const service = summaries[0]!.closest('details')!
    expect(service.open).toBe(false)
    await userEvent.click(summaries[0]!)
    expect(service.open).toBe(true)
  })

  it('holds the button until the form is complete, and says what is missing', async () => {
    const calls = stubApi((call) => {
      if (call.path === '/api/me/role') return { status: 200, body: me('owner', 'pending') }
      if (call.path === '/api/terms') return { status: 200, body: PAGE }
      return undefined
    })
    renderAt('/admin')

    await screen.findByLabelText(copy.legalName)
    for (const box of screen.getAllByRole('checkbox')) await userEvent.click(box)
    await userEvent.type(screen.getByLabelText(copy.rut), '76.123.456-1')
    await userEvent.click(screen.getByRole('button', { name: copy.accept }))
    expect(await screen.findByText(copy.refusals.rut)).toBeInTheDocument()
    expect(screen.getAllByText(copy.required).length).toBeGreaterThan(0)
    expect(calls.some((c) => c.path === '/api/terms/accept')).toBe(false)
  })

  it('reloads the texts when they changed while the titular read them', async () => {
    const calls = stubApi((call) => {
      if (call.path === '/api/me/role') return { status: 200, body: me('owner', 'pending') }
      if (call.path === '/api/terms') return { status: 200, body: PAGE }
      if (call.path === '/api/terms/accept') return { status: 409, body: { detail: { code: 'terms_changed' } } }
      return undefined
    })
    renderAt('/admin')

    await screen.findByLabelText(copy.legalName)
    await fillForm()
    for (const box of screen.getAllByRole('checkbox')) await userEvent.click(box)
    await userEvent.click(screen.getByRole('button', { name: copy.accept }))
    expect(await screen.findByText(copy.changed)).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/terms').length).toBeGreaterThan(1))
    for (const box of screen.getAllByRole('checkbox')) expect(box).not.toBeChecked()
  })

  it('shows an outdated gym’s titular what changed, first', async () => {
    stubApi((call) => {
      if (call.path === '/api/me/role') return { status: 200, body: me('owner', 'outdated') }
      if (call.path === '/api/terms') {
        const [service, processor] = PAGE.documents
        return {
          status: 200,
          body: {
            ...PAGE,
            state: 'outdated',
            prefill: { legal_name: 'Norte SpA' },
            documents: [service, { ...processor, changes: [{ version: '2026-11-20', html: '<ul><li>Puerto Montt.</li></ul>' }] }],
          },
        }
      }
      return undefined
    })
    renderAt('/admin')

    expect(await screen.findByText(copy.leadOutdated('Academia Norte'))).toBeInTheDocument()
    const changes = screen.getByRole('region', { name: copy.changes })
    expect(within(changes).getByText('Puerto Montt.')).toBeInTheDocument()
    expect(within(changes).getByText(copy.changesOf('Términos de encargo', '2026-11-20'))).toBeInTheDocument()
    expect(screen.getByLabelText(copy.legalName)).toHaveValue('Norte SpA')
  })

  it('shows the rest of the team of a pending gym who has to accept', async () => {
    stubApi((call) => (call.path === '/api/me/role' ? { status: 200, body: me('coach', 'pending') } : undefined))
    renderAt('/admin/clases')

    expect(await screen.findByRole('heading', { name: copy.pendingTitle('Academia Norte') })).toBeInTheDocument()
    expect(screen.getByText(copy.pending('Dueña Norte'))).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: es.nav.label })).not.toBeInTheDocument()
  })

  it('lets the rest of the team of an outdated gym work as before', async () => {
    stubApi((call) => (call.path === '/api/me/role' ? { status: 200, body: me('admin', 'outdated') } : undefined))
    renderAt('/admin')

    expect(await screen.findByRole('navigation', { name: es.nav.label })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: copy.title })).not.toBeInTheDocument()
  })
})

describe('validRut', () => {
  it('takes a RUT with its check digit, dotted or not', () => {
    expect(validRut('76.123.456-0')).toBe(true)
    expect(validRut('761234560')).toBe(true)
    expect(validRut('7654321-6')).toBe(true)
    expect(validRut('76.123.456-1')).toBe(false)
    expect(validRut('hola')).toBe(false)
  })
})

describe('declarationOf', () => {
  const service = PAGE.declarations.service
  it('accepts in the razón social once it is typed', () => {
    expect(declarationOf(service, 'Norte SpA')).toBe(
      'Acepto los Términos de servicio en nombre de Norte SpA, y declaro que puedo representarla.',
    )
  })

  it('accepts in the gym’s name until then, with no bracketed label', () => {
    expect(declarationOf(service, null)).toBe(
      `Acepto los Términos de servicio en nombre de ${copy.thePlace()}, y declaro que puedo representarla.`,
    )
    expect(declarationOf(service, null)).not.toMatch(/\[/)
  })
})

describe('demoted', () => {
  it('moves every heading down, to h6 at most, and leaves the rest alone', () => {
    expect(demoted('<h1 id="a">A</h1><h2>B</h2><h5>C</h5><hr><p>h1</p>', 2)).toBe(
      '<h3 id="a">A</h3><h4>B</h4><h6>C</h6><hr><p>h1</p>',
    )
  })
})
