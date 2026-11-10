import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'
import { appPath, landingFor, SIGN_IN_PATH } from './api/auth'
import { ApiError, onUnauthorized } from './api/client'
import { myRoleQuery } from './api/me'
import { AdminLayout } from './layouts/AdminLayout'
import { t } from './i18n/es'
import { MeLayout } from './layouts/MeLayout'
import { Classes } from './routes/Classes'
import { MeHome } from './routes/MeHome'
import { MemberDetail } from './routes/MemberDetail'
import { MemberImport } from './routes/MemberImport'
import { NotFound } from './routes/NotFound'
import { Payments, validatePaymentsSearch } from './routes/Payments'
import { SessionDetail } from './routes/SessionDetail'
import { SignIn } from './routes/SignIn'
import { Settings, SETTINGS_SECTIONS } from './routes/Settings'
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

// While the session check is slow to answer (after the router's `defaultPendingMs`).
function Pending() {
  return (
    <p className="route-pending" role="status">
      {t.common.loading}
    </p>
  )
}

/**
 * Who is signed in, asked once before a shell renders: a 401 sends the visitor to
 * sign in, keeping the page they asked for. Any other failure lets the shell render,
 * and its screens say what did not load.
 */
async function requireSession(queryClient: QueryClient, href: string) {
  try {
    // No retries here: a shell that cannot reach the API still renders, and retries
    // the role itself.
    return await queryClient.ensureQueryData({ ...myRoleQuery(), retry: false })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      throw redirect({ to: SIGN_IN_PATH, search: { redirect: appPath(href) }, replace: true })
    }
    return undefined
  }
}

// Where a sign-in link lands: the page they had asked for, else staff in /admin and a
// member on /me.
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: async ({ context }) => {
    const me = await requireSession(context.queryClient, '/')
    throw redirect({ href: me ? landingFor(me.role) : '/admin', replace: true })
  },
})

// "Entrar": the one page open to a signed-out visitor.
const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: SIGN_IN_PATH,
  // Set even when it is no path of ours: the root passes the raw query through, and
  // only an explicit `undefined` overrides it.
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => ({ redirect: appPath(search.redirect) }),
  component: SignIn,
})

// /admin/*: gym owners and coaches.
const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'admin',
  beforeLoad: async ({ context, location }) => {
    await requireSession(context.queryClient, location.href)
  },
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

// "Ajustes": the gym's configuration, owner and admin only, one route per section.
const adminSettingsRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'ajustes',
  component: Settings,
})

// It opens on its first section.
const adminSettingsIndexRoute = createRoute({
  getParentRoute: () => adminSettingsRoute,
  path: '/',
  beforeLoad: () => {
    throw redirect({ to: `/admin/ajustes/${SETTINGS_SECTIONS[0].path}`, replace: true })
  },
})

const adminSettingsSectionRoutes = SETTINGS_SECTIONS.map((section) =>
  createRoute({ getParentRoute: () => adminSettingsRoute, path: section.path, component: section.component }),
)

// /me/*: the student page, reached by magic link.
const meRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'me',
  beforeLoad: async ({ context, location }) => {
    await requireSession(context.queryClient, location.href)
  },
  component: MeLayout,
})

const meHomeRoute = createRoute({
  getParentRoute: () => meRoute,
  path: '/',
  component: MeHome,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  signInRoute,
  adminRoute.addChildren([
    adminTodayRoute,
    adminStudentsRoute,
    adminImportRoute,
    adminMemberRoute,
    adminClassesRoute,
    adminSessionRoute,
    adminPaymentsRoute,
    adminProofReviewRoute,
    adminSettingsRoute.addChildren([adminSettingsIndexRoute, ...adminSettingsSectionRoutes]),
  ]),
  meRoute.addChildren([meHomeRoute]),
])

export function createAppRouter(context: RouterContext, history?: RouterHistory) {
  const router = createRouter({
    routeTree,
    context,
    history,
    defaultPreload: 'intent',
    defaultPendingComponent: Pending,
    // Loaders read through TanStack Query, which owns caching and staleness.
    defaultPreloadStaleTime: 0,
  })
  // A session that ends mid-use (a 401 on any call) goes back to sign in, the same way
  // a signed-out visitor does, and what it had loaded is forgotten.
  onUnauthorized(() => {
    const { pathname, href } = router.state.location
    if (pathname === SIGN_IN_PATH) return
    context.queryClient.clear()
    void router.navigate({ to: SIGN_IN_PATH, search: { redirect: appPath(href) }, replace: true })
  })
  return router
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
