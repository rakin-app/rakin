import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { lastUpdated, TEMPLATE_UPDATED_ON, type PrivacyNotice } from '../api/privacy'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.privacy

const NOTICE: PrivacyNotice = {
  gym: 'Academia Sur',
  legal_name: 'Academia Sur SpA',
  rut: '76432109-K',
  email: 'privacidad@academiasur.example.com',
  address: 'Av. Pedro de Valdivia 1234, Providencia',
  updated_on: '2027-01-15',
}

type Answer = { status?: number; body?: unknown }

function stubApi(notice: Answer = { body: NOTICE }) {
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), 'http://localhost')
      asked.push(`${url.pathname}${url.search}`)
      let answer: Answer = { status: 404, body: { detail: 'Not Found' } }
      if (url.pathname === '/api/privacy') answer = notice
      if (url.pathname === '/api/me/role') answer = { body: { role: 'member', person_id: 'me' } }
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return asked
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Política de privacidad', () => {
  it('fills the template in with the gym’s details, with no session', async () => {
    const asked = stubApi()
    renderAt('/privacidad')

    expect(await screen.findByRole('heading', { name: copy.title('Academia Sur') })).toBeInTheDocument()
    expect(screen.getByText(copy.controller('Academia Sur SpA', '76.432.109-K', 'Academia Sur'), { exact: false })).toBeInTheDocument()
    expect(screen.getByText(copy.address(NOTICE.address!), { exact: false })).toBeInTheDocument()
    for (const link of screen.getAllByRole('link', { name: NOTICE.email })) {
      expect(link).toHaveAttribute('href', `mailto:${NOTICE.email}`)
    }
    for (const item of [...copy.data, ...copy.purpose, ...copy.subprocessors]) {
      expect(screen.getByText(item)).toBeInTheDocument()
    }
    expect(screen.getByText(copy.complaint)).toBeInTheDocument()
    expect(screen.getByText(copy.updated('15 de enero de 2027'))).toBeInTheDocument()
    expect(screen.getByText(copy.disclaimer)).toBeInTheDocument()
    expect(asked).toEqual(['/api/privacy'])
  })

  it('names the join link it was opened from', async () => {
    const asked = stubApi()
    renderAt('/privacidad?enlace=tok-123456789012345678901')

    await screen.findByRole('heading', { name: copy.title('Academia Sur') })
    expect(asked).toEqual(['/api/privacy?link=tok-123456789012345678901'])
  })

  it('says when the gym has not published one', async () => {
    stubApi({ status: 404, body: { detail: 'no_privacy_notice' } })
    renderAt('/privacidad')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.missing)
  })

  it('is linked from the student page', async () => {
    stubApi()
    renderAt('/me')

    expect(await screen.findByRole('link', { name: copy.link })).toHaveAttribute('href', '/privacidad')
  })
})

describe('lastUpdated', () => {
  it('is the template’s date or the gym’s, the later', () => {
    expect(lastUpdated({ ...NOTICE, updated_on: '2027-01-15' })).toBe('2027-01-15')
    expect(lastUpdated({ ...NOTICE, updated_on: '2020-01-01' })).toBe(TEMPLATE_UPDATED_ON)
  })
})
