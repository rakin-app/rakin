import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'
import { PlaceholderPage } from './components/PlaceholderPage'
import { t } from './i18n/es'
import { AdminLayout } from './layouts/AdminLayout'
import { MeLayout } from './layouts/MeLayout'
import { NotFound } from './routes/NotFound'
import { Students, validateStudentsSearch } from './routes/Students'

export type RouterContext = {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  notFoundComponent: NotFound,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: () => {
    throw redirect({ to: '/admin' })
  },
})

// /admin/*: gym owners and coaches.
const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'admin',
  component: AdminLayout,
})

const adminTodayRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: '/',
  component: () => <PlaceholderPage title={t.admin.today.title} />,
})

const adminStudentsRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'alumnos',
  validateSearch: validateStudentsSearch,
  component: Students,
})

const adminClassesRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'clases',
  component: () => <PlaceholderPage title={t.admin.classes.title} />,
})

const adminPaymentsRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos',
  component: () => <PlaceholderPage title={t.admin.payments.title} />,
})

// /me/*: the student page, reached by magic link.
const meRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'me',
  component: MeLayout,
})

const meHomeRoute = createRoute({
  getParentRoute: () => meRoute,
  path: '/',
  component: () => <PlaceholderPage title={t.me.home.title} />,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  adminRoute.addChildren([adminTodayRoute, adminStudentsRoute, adminClassesRoute, adminPaymentsRoute]),
  meRoute.addChildren([meHomeRoute]),
])

export function createAppRouter(context: RouterContext, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context,
    history,
    defaultPreload: 'intent',
    // Loaders read through TanStack Query, which owns caching and staleness.
    defaultPreloadStaleTime: 0,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
