import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from './api/queryClient'
import { App } from './App'
import { es } from './i18n/es'
import { createAppRouter } from './router'

// An owner, who sees every tab; anything else the screens ask for is not found.
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const owner = new URL(String(input), 'http://localhost').pathname === '/api/me/role'
      const me = { role: 'owner', person_id: 'me', name: 'Martín', email: null, gym_name: 'Academia Sur' }
      return new Response(JSON.stringify(owner ? me : { detail: 'Not Found' }), {
        status: owner ? 200 : 404,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

type Answer = { status: number; body?: unknown }

// Every call answered by `answer`, by path; the calls made are returned.
function stubApi(answer: (path: string, init?: RequestInit) => Answer) {
  const calls: { path: string; method: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      calls.push({ path, method: init?.method ?? 'GET' })
      const { status, body } = answer(path, init)
      return new Response(status === 204 ? null : JSON.stringify(body ?? {}), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

const signedOut = () => stubApi(() => ({ status: 401, body: { detail: 'Not authenticated' } }))

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

describe('/admin route tree', () => {
  it('renders the bottom nav with Hoy, Alumnos, Clases, Pagos, Ajustes in order', async () => {
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    // Pagos and Ajustes join once the role is known to reach them.
    await within(nav).findByRole('link', { name: es.nav.settings })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Hoy', 'Alumnos', 'Clases', 'Pagos', 'Ajustes'])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/admin',
      '/admin/alumnos',
      '/admin/clases',
      '/admin/pagos',
      '/admin/ajustes',
    ])
  })

  it.each([
    // "Hoy, lun 9 nov": today's date follows.
    ['/admin', es.nav.today, new RegExp(`^${es.admin.today.title},`)],
    ['/admin/alumnos', es.nav.students, es.admin.students.title],
    ['/admin/clases', es.nav.classes, es.admin.classes.title],
    ['/admin/pagos', es.nav.payments, es.admin.payments.title],
    // A phone's section page is titled by its section.
    ['/admin/ajustes/planes', es.nav.settings, es.admin.settings.sections.plans],
  ])('%s marks %s as the current page', async (path, navLabel, title) => {
    renderAt(path)

    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: es.nav.label })
    await within(nav).findByRole('link', { name: es.nav.payments })
    const current = within(nav)
      .getAllByRole('link')
      .filter((link) => link.getAttribute('aria-current') === 'page')
    expect(current.map((link) => link.textContent)).toEqual([navLabel])
  })

  it('names the gym in the sidebar, on Hoy and in each tab title', async () => {
    const router = renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    expect(await within(nav).findByText('Academia Sur')).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(await within(main).findByText('Academia Sur')).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe(`${es.admin.today.title} · Academia Sur`))

    await router.navigate({ to: '/admin/alumnos' })
    await waitFor(() => expect(document.title).toBe(`${es.admin.students.title} · Academia Sur`))
  })

  it('navigates between sections from the nav', async () => {
    const router = renderAt('/admin')
    const nav = await screen.findByRole('navigation', { name: es.nav.label })

    await userEvent.click(await within(nav).findByRole('link', { name: es.nav.payments }))

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

describe('signing in', () => {
  it('sends a signed-out visitor from / to the sign-in page, not the empty shell', async () => {
    signedOut()
    const router = renderAt('/')

    expect(await screen.findByRole('heading', { level: 1, name: es.signIn.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/ingresar')
    expect(router.state.location.search).toEqual({})
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it.each(['/admin/pagos', '/admin/alumnos?q=ana', '/me'])(
    'sends a signed-out visitor from %s to sign in, keeping the page',
    async (path) => {
      signedOut()
      const router = renderAt(path)

      expect(await screen.findByRole('heading', { level: 1, name: es.signIn.title })).toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/ingresar')
      expect(router.state.location.search).toEqual({ redirect: path })
    },
  )

  it('lands a staff member in /admin with the full nav, and a member on /me', async () => {
    stubApi((path) => (path === '/api/me/role' ? { status: 200, body: { role: 'owner' } } : { status: 404 }))
    const router = renderAt('/')
    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Hoy',
      'Alumnos',
      'Clases',
      'Pagos',
      'Ajustes',
    ])
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('lands a member on /me', async () => {
    stubApi((path) => (path === '/api/me/role' ? { status: 200, body: { role: null } } : { status: 404 }))
    const router = renderAt('/')

    expect(await screen.findByRole('heading', { level: 1, name: es.me.home.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/me')
  })

  it('returns them to the page they had asked for, once', async () => {
    localStorage.setItem('rakin.returnTo', '/admin/pagos')
    stubApi((path) => (path === '/api/me/role' ? { status: 200, body: { role: 'owner' } } : { status: 404 }))
    const router = renderAt('/')

    expect(await screen.findByRole('heading', { level: 1, name: es.admin.payments.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/pagos')
    expect(localStorage.getItem('rakin.returnTo')).toBeNull()
  })

  it('lands a member on /me although they had asked for an admin page', async () => {
    localStorage.setItem('rakin.returnTo', '/admin/pagos')
    stubApi((path) => (path === '/api/me/role' ? { status: 200, body: { role: null } } : { status: 404 }))
    const router = renderAt('/')

    expect(await screen.findByRole('heading', { level: 1, name: es.me.home.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/me')
  })

  it('sends them to sign in when the session ends mid-use', async () => {
    let live = true
    stubApi((path) => {
      if (!live) return { status: 401 }
      return path === '/api/me/role' ? { status: 200, body: { role: 'owner' } } : { status: 404 }
    })
    const router = renderAt('/admin')
    const nav = await screen.findByRole('navigation', { name: es.nav.label })

    live = false
    await userEvent.click(within(nav).getByRole('link', { name: es.nav.students }))

    expect(await screen.findByRole('heading', { level: 1, name: es.signIn.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/ingresar')
    expect(router.state.location.search).toEqual({ redirect: '/admin/alumnos' })
  })
})

describe('staff who also train (#214)', () => {
  const asRole = (role: string | null, studentPage: boolean) =>
    stubApi((path) =>
      path === '/api/me/role'
        ? { status: 200, body: { role, person_id: 'me', name: 'Felipe', email: null, gym_name: 'Academia Sur', student_page: studentPage } }
        : { status: 404 },
    )

  it('lands them on /me when that is the page they asked for', async () => {
    localStorage.setItem('rakin.returnTo', '/me')
    asRole('coach', true)
    const router = renderAt('/')

    expect(await screen.findByRole('heading', { level: 1, name: es.me.home.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/me')
  })

  it('gives staff with a membership a "Mi página" link in the nav, and the student page a way back', async () => {
    asRole('coach', true)
    const router = renderAt('/admin')
    const nav = await screen.findByRole('navigation', { name: es.nav.label })

    await userEvent.click(await within(nav).findByRole('link', { name: es.nav.myPage }))
    expect(await screen.findByRole('heading', { level: 1, name: es.me.home.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/me')

    await userEvent.click(screen.getByRole('link', { name: es.me.toAdmin }))
    expect(await screen.findByRole('navigation', { name: es.nav.label })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('shows no "Mi página" to staff without a membership', async () => {
    asRole('owner', false)
    renderAt('/admin')
    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    await within(nav).findByRole('link', { name: es.nav.settings })

    expect(within(nav).queryByRole('link', { name: es.nav.myPage })).not.toBeInTheDocument()
  })

  it('shows a member no way into the panel', async () => {
    asRole(null, true)
    renderAt('/me')

    expect(await screen.findByRole('heading', { level: 1, name: es.me.home.title })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: es.me.toAdmin })).not.toBeInTheDocument()
  })
})

describe('one trip to sign in', () => {
  // The handler's navigations to /ingresar, counted on `router.navigate`; `hold` keeps
  // the router where it is, as if the first navigation had not landed yet.
  function navigationsToSignIn(router: ReturnType<typeof renderAt>, { hold = false } = {}) {
    const navigate = router.navigate.bind(router)
    const spy = vi.spyOn(router, 'navigate').mockImplementation((options) =>
      hold && options.to === '/ingresar' ? Promise.resolve() : navigate(options),
    )
    return () => spy.mock.calls.filter(([options]) => options.to === '/ingresar').length
  }

  it('navigates once and clears once for a burst of 401s, before the first navigation lands', async () => {
    let live = true
    const calls = stubApi((path) => {
      if (!live) return { status: 401 }
      return path === '/api/me/role' ? { status: 200, body: { role: 'owner' } } : { status: 404 }
    })
    const router = renderAt('/admin')
    const { queryClient } = router.options.context
    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    await within(nav).findByRole('link', { name: es.nav.payments })
    const navigations = navigationsToSignIn(router, { hold: true })
    const clear = vi.spyOn(queryClient, 'clear')

    live = false
    const before = calls.length
    // Every query on the screen asks again at once, and each one is refused.
    queryClient.getQueryCache().getAll().forEach((query) => void query.fetch().catch(() => {}))

    await waitFor(() => expect(calls.length - before).toBeGreaterThan(2))
    await waitFor(() => expect(navigations()).toBe(1))
    expect(clear).toHaveBeenCalledTimes(1)
  })

  it('leaves a 401 on the session check to the check: one redirect, no second navigation', async () => {
    signedOut()
    const queryClient = createQueryClient()
    const clear = vi.spyOn(queryClient, 'clear')
    const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/admin/pagos'] }))
    const navigations = navigationsToSignIn(router)
    render(<App queryClient={queryClient} router={router} />)

    expect(await screen.findByRole('heading', { level: 1, name: es.signIn.title })).toBeInTheDocument()
    expect(router.state.location.href).toBe('/ingresar?redirect=%2Fadmin%2Fpagos')
    // The handler never navigates: the check's `redirect` is the only trip.
    expect(navigations()).toBe(0)
    expect(clear).toHaveBeenCalledTimes(1)
  })

  it('goes again the next time the session ends', async () => {
    let live = true
    stubApi((path) => {
      if (!live) return { status: 401 }
      return path === '/api/me/role' ? { status: 200, body: { role: 'owner' } } : { status: 404 }
    })
    const router = renderAt('/admin')
    const { queryClient } = router.options.context
    await screen.findByRole('navigation', { name: es.nav.label })
    live = false
    void queryClient.invalidateQueries()
    await screen.findByRole('heading', { level: 1, name: es.signIn.title })

    // Signed in again, in this tab, and the session ends once more.
    live = true
    await router.navigate({ to: '/admin' })
    await screen.findByRole('navigation', { name: es.nav.label })
    const navigations = navigationsToSignIn(router)
    live = false
    void queryClient.invalidateQueries()

    expect(await screen.findByRole('heading', { level: 1, name: es.signIn.title })).toBeInTheDocument()
    expect(navigations()).toBe(1)
  })
})

describe('Cerrar sesión', () => {
  it.each([
    ['owner', '/admin'],
    [null, '/me'],
  ])('ends the session of a %s on %s and returns to sign in', async (role, path) => {
    let live = true
    const calls = stubApi((api) => {
      if (api === '/api/auth/logout') {
        live = false
        return { status: 204 }
      }
      if (!live) return { status: 401 }
      return api === '/api/me/role' ? { status: 200, body: { role } } : { status: 404 }
    })
    const router = renderAt(path)

    await userEvent.click(await screen.findByRole('button', { name: es.signOut.label }))

    expect(await screen.findByRole('heading', { level: 1, name: es.signIn.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/ingresar')
    expect(calls).toContainEqual({ path: '/api/auth/logout', method: 'POST' })
  })

  it('stays put and says so when the session could not be ended', async () => {
    stubApi((api) => {
      if (api === '/api/auth/logout') return { status: 503 }
      return api === '/api/me/role' ? { status: 200, body: { role: 'owner' } } : { status: 404 }
    })
    const router = renderAt('/admin')

    await userEvent.click(await screen.findByRole('button', { name: es.signOut.label }))

    expect(await screen.findByText(es.signOut.failed)).toHaveAttribute('role', 'alert')
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin'))
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
