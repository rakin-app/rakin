import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'
import { AdminLayout } from './layouts/AdminLayout'
import { MeLayout } from './layouts/MeLayout'
import { Classes } from './routes/Classes'
import { MeHome } from './routes/MeHome'
import { MemberDetail } from './routes/MemberDetail'
import { MemberImport } from './routes/MemberImport'
import { NotFound } from './routes/NotFound'
import { Payments, validatePaymentsSearch } from './routes/Payments'
import { SessionDetail } from './routes/SessionDetail'
import { Students, validateStudentsSearch } from './routes/Students'
import { Today } from './routes/Today'
import { ValidateProof } from './routes/ValidateProof'

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

// "Hoy": what is overdue and what waits for review.
const adminTodayRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: '/',
  component: Today,
})

const adminStudentsRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'alumnos',
  validateSearch: validateStudentsSearch,
  component: Students,
})

// "Importar alumnos": the gym's spreadsheet, brought over. A static path, so it wins
// over `alumnos/$personId`.
const adminImportRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'alumnos/importar',
  component: MemberImport,
})

// "Ficha de alumno": one member, their plan and, for who reads the ledger, their money.
const adminMemberRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'alumnos/$personId',
  component: MemberDetail,
})

// "Clases": today's classes, and starting one.
const adminClassesRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'clases',
  component: Classes,
})

// One class: its topic and notes.
const adminSessionRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'clases/$sessionId',
  component: SessionDetail,
})

// "Libro de pagos": the gym's ledger, for who reads it.
const adminPaymentsRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos',
  validateSearch: validatePaymentsSearch,
  component: Payments,
})

// "Validar comprobante": the queue of proofs waiting for review.
const adminProofReviewRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos/comprobantes',
  component: ValidateProof,
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
  component: MeHome,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  adminRoute.addChildren([
    adminTodayRoute,
    adminStudentsRoute,
    adminImportRoute,
    adminMemberRoute,
    adminClassesRoute,
    adminSessionRoute,
    adminPaymentsRoute,
    adminProofReviewRoute,
  ]),
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
