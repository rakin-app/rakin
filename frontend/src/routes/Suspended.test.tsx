import { createMemoryHistory } from '@tanstack/react-router'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const HOST = { gym: { slug: 'norte', name: 'Gimnasio Norte', theme: 'bosque', logo: null, suspended: true } }

// `/api/host` says the gym is suspended; anything else is a 401, as for a gym nobody
// can sign in to.
function stubApi() {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const path = new URL(String(input), 'http://localhost').pathname
      calls.push(path)
      if (path === '/api/host') {
        return new Response(JSON.stringify(HOST), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response(JSON.stringify({ detail: 'not authenticated' }), { status: 401 })
    }),
  )
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('a suspended gym’s address (#439)', () => {
  it.each(['/', '/ingresar', '/admin', '/admin/alumnos', '/me', '/unirse', '/privacidad', '/no-existe'])(
    'shows only the notice at %s',
    async (path) => {
      stubApi()
      const queryClient = createQueryClient()
      const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
      render(<App queryClient={queryClient} router={router} />)

      expect(await screen.findByText(es.suspended.notice)).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Gimnasio Norte' })).toBeInTheDocument()
      expect(screen.getAllByRole('heading')).toHaveLength(1)
      expect(screen.queryByRole('link')).not.toBeInTheDocument()
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    },
  )
})
