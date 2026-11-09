import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { createQueryClient } from './api/queryClient'
import { App } from './App'
import { es } from './i18n/es'
import { createAppRouter } from './router'

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

describe('/admin route tree', () => {
  it('renders the bottom nav with Hoy, Alumnos, Clases, Pagos in order', async () => {
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Hoy', 'Alumnos', 'Clases', 'Pagos'])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/admin',
      '/admin/alumnos',
      '/admin/clases',
      '/admin/pagos',
    ])
  })

  it.each([
    // "Hoy, lun 9 nov": today's date follows.
    ['/admin', es.nav.today, new RegExp(`^${es.admin.today.title},`)],
    ['/admin/alumnos', es.nav.students, es.admin.students.title],
    ['/admin/clases', es.nav.classes, es.admin.classes.title],
    ['/admin/pagos', es.nav.payments, es.admin.payments.title],
  ])('%s marks %s as the current page', async (path, navLabel, title) => {
    renderAt(path)

    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: es.nav.label })
    const current = within(nav)
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'page')
    expect(current.map((link) => link.textContent)).toEqual([navLabel])
  })

  it('navigates between sections from the nav', async () => {
    const router = renderAt('/admin')
    const nav = await screen.findByRole('navigation', { name: es.nav.label })

    await userEvent.click(within(nav).getByRole('link', { name: es.nav.payments }))

    expect(await screen.findByRole('heading', { level: 1, name: es.admin.payments.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/pagos')
  })
})

describe('/me route tree', () => {
  it('renders the student shell without the admin nav', async () => {
    renderAt('/me')

    expect(await screen.findByRole('heading', { level: 1, name: es.me.home.title })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})

describe('other paths', () => {
  it('redirects / to /admin', async () => {
    const router = renderAt('/')

    const title = new RegExp(`^${es.admin.today.title},`)
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('shows the not-found page for unknown paths', async () => {
    renderAt('/nope')
    expect(await screen.findByRole('heading', { level: 1, name: es.notFound.title })).toBeInTheDocument()
  })
})
