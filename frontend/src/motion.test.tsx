import { createMemoryHistory, createRootRoute, createRoute, createRouter, Link, Outlet, RouterProvider } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { milliseconds, useRise } from './motion'

function Shell() {
  const rise = useRise<HTMLDivElement>()
  return (
    <div ref={rise} data-testid="page">
      <Outlet />
    </div>
  )
}

function renderRoutes() {
  const root = createRootRoute({ component: Shell })
  const routes = (['/', '/ingresar'] as const).map((path) =>
    createRoute({
      getParentRoute: () => root,
      path,
      component: () => <Link to={path === '/' ? '/ingresar' : '/'}>ir</Link>,
    }),
  )
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(<RouterProvider router={router} />)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useRise', () => {
  it('rises on a change of route, not on the first page, and never by transform', async () => {
    const animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation)
    Object.defineProperty(HTMLElement.prototype, 'animate', { value: animate, configurable: true })
    renderRoutes()

    await userEvent.click(await screen.findByRole('link'))
    await screen.findByRole('link')
    expect(animate).toHaveBeenCalledTimes(1)
    const [keyframes] = animate.mock.calls[0] as unknown as [Keyframe[]]
    // A transformed ancestor would place a fixed sheet against the page, not the screen.
    expect(keyframes.every((frame) => !('transform' in frame))).toBe(true)
    expect(keyframes.map((frame) => frame.opacity)).toEqual([0, 1])
  })
})

describe('milliseconds', () => {
  it.each([
    ['500ms', 500],
    ['0.5s', 500],
    [' 150ms ', 150],
    ['', 42],
    ['fast', 42],
  ])('reads %j as %d', (token, expected) => {
    expect(milliseconds(token, 42)).toBe(expected)
  })
})
