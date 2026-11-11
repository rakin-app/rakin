import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'
import { appPath, hadSession, landingFor, markSignedIn, SIGN_IN_PATH } from './api/auth'
import { ApiError, onUnauthorized } from './api/client'
import { keepDrafts } from './api/drafts'
import { myRoleQuery, type MyRole } from './api/me'
import { AdminLayout } from './layouts/AdminLayout'
import { t } from './i18n/es'
import { MeLayout } from './layouts/MeLayout'
import { Classes } from './routes/Classes'
import { ExtraChargeDetail } from './routes/ExtraChargeDetail'
import { ExtraChargeNew } from './routes/ExtraChargeNew'
import { ExtraCharges } from './routes/ExtraCharges'
import { ClassTimer } from './routes/ClassTimer'
import { Join } from './routes/Join'
import { MeHome } from './routes/MeHome'
import { MemberDetail } from './routes/MemberDetail'
import { MemberImport } from './routes/MemberImport'
import { NewMember } from './routes/NewMember'
import { NotFound } from './routes/NotFound'
import { Payments, validatePaymentsSearch } from './routes/Payments'
import { Privacy, validatePrivacySearch } from './routes/Privacy'
import { SessionDetail } from './routes/SessionDetail'
import { SignIn } from './routes/SignIn'
import { Settings, SETTINGS_SECTIONS, SettingsHome } from './routes/Settings'
import { Students, validateStudentsSearch } from './routes/Students'
import { Today } from './routes/Today'
import { ValidateProof } from './routes/ValidateProof'

export type RouterContext = {
  queryClient: QueryClient
}

/**
 * One trip to sign in per signed-out moment. A screen's queries can answer 401 all at
 * once, and a session check's own 401 also reaches the `onUnauthorized` handler; only
 * the first of them clears the cache and navigates. Reset on reaching `/ingresar`.
 */
type SignInGuard = {
  redirecting: boolean
  // Session checks asking for the role right now: they redirect on their own 401.
  checking: number
}

type AppContext = RouterContext & { signIn: SignInGuard }

const rootRoute = createRootRouteWithContext<AppContext>()({
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
async function requireSession({ queryClient, signIn }: AppContext, href: string) {
  signIn.checking += 1
  try {
    // No retries here: a shell that cannot reach the API still renders, and retries
    // the role itself.
    const me = await queryClient.ensureQueryData({ ...myRoleQuery(), retry: false })
    markSignedIn()
    return me
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      signIn.redirecting = true
      queryClient.clear()
      const expired = hadSession() || undefined
      throw redirect({ to: SIGN_IN_PATH, search: { redirect: appPath(href), expired }, replace: true })
    }
    return undefined
  } finally {
    signIn.checking -= 1
  }
}

// Where a sign-in link lands: the page they had asked for, else staff in /admin and a
// member on /me.
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: async ({ context }) => {
    const me = await requireSession(context, '/')
    throw redirect({ href: me ? landingFor(me.role) : '/admin', replace: true })
  },
})

// "Entrar": open to a signed-out visitor, as is the join form.
const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: SIGN_IN_PATH,
  // Set even when it is no path of ours: the root passes the raw query through, and
  // only an explicit `undefined` overrides it.
  // `expired`: the session ended rather than never began, which the page says (#212).
  validateSearch: (search: Record<string, unknown>): { redirect?: string; expired?: true } => ({
    redirect: appPath(search.redirect),
    expired: search.expired === true || search.expired === 'true' ? true : undefined,
  }),
  component: SignIn,
})

// "Inscríbete": the form behind a gym's join link (#154), open to anyone with the link.
const joinRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'unirse/$token',
  component: Join,
})

// "Política de privacidad": a gym's privacy notice (#168), open to anyone, linked from
// the join form and the student page.
const privacyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'privacidad',
  validateSearch: validatePrivacySearch,
  component: Privacy,
})

// /admin/*: gym owners and coaches.
const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'admin',
  beforeLoad: async ({ context, location }) => {
    await requireSession(context, location.href)
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

// "Nuevo alumno": a member added by hand (#157). Static too, so it wins over `$personId`.
const adminNewMemberRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'alumnos/nuevo',
  component: NewMember,
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

// "Abrir timer": the class timer, its blocks and countdown, for the coach (#139).
const adminSessionTimerRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'clases/$sessionId/timer',
  component: ClassTimer,
})

// Pagos: the gym's ledger, for who reads it.
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

// Pagos › "Cobros extra" (#195): one-off charges and the groups they target, a new one
// through its wizard, and one cobro's people. Static paths win over `$chargeId`.
const adminExtraChargesRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos/cobros',
  component: ExtraCharges,
})

const adminExtraChargeNewRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos/cobros/nuevo',
  component: ExtraChargeNew,
})

const adminExtraChargeRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos/cobros/$chargeId',
  component: ExtraChargeDetail,
})

// "Ajustes": the gym's configuration, owner and admin only, one route per section.
const adminSettingsRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'ajustes',
  component: Settings,
})

// It opens on the list of its sections on a phone, on its first section on a desktop.
const adminSettingsIndexRoute = createRoute({
  getParentRoute: () => adminSettingsRoute,
  path: '/',
  component: SettingsHome,
})

const adminSettingsSectionRoutes = SETTINGS_SECTIONS.map((section) =>
  createRoute({ getParentRoute: () => adminSettingsRoute, path: section.path, component: section.component }),
)

// /me/*: the student page, reached by magic link.
const meRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'me',
  beforeLoad: async ({ context, location }) => {
    await requireSession(context, location.href)
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
  joinRoute,
  privacyRoute,
  adminRoute.addChildren([
    adminTodayRoute,
    adminStudentsRoute,
    adminImportRoute,
    adminNewMemberRoute,
    adminMemberRoute,
    adminClassesRoute,
    adminSessionRoute,
    adminSessionTimerRoute,
    adminPaymentsRoute,
    adminProofReviewRoute,
    adminExtraChargesRoute,
    adminExtraChargeNewRoute,
    adminExtraChargeRoute,
    adminSettingsRoute.addChildren([adminSettingsIndexRoute, ...adminSettingsSectionRoutes]),
  ]),
  meRoute.addChildren([meHomeRoute]),
])

export function createAppRouter(context: RouterContext, history?: RouterHistory) {
  const signIn: SignInGuard = { redirecting: false, checking: 0 }
  const router = createRouter({
    routeTree,
    context: { ...context, signIn },
    history,
    defaultPreload: 'intent',
    defaultPendingComponent: Pending,
    // Loaders read through TanStack Query, which owns caching and staleness.
    defaultPreloadStaleTime: 0,
  })
  // A session that ends mid-use (a 401 on any call) goes back to sign in, the same way
  // a signed-out visitor does, saying it expired; what it had loaded is forgotten.
  onUnauthorized(() => {
    const { pathname, href } = router.state.location
    if (signIn.redirecting || signIn.checking > 0 || pathname === SIGN_IN_PATH) return
    signIn.redirecting = true
    // What the open screen held unsaved, kept for after signing in again (#212).
    keepDrafts(context.queryClient.getQueryData<MyRole>(['me', 'role'])?.person_id)
    // Said by the URL here: the flag is not needed for this sign-in page.
    hadSession()
    context.queryClient.clear()
    void router.navigate({ to: SIGN_IN_PATH, search: { redirect: appPath(href), expired: true }, replace: true })
  })
  router.subscribe('onResolved', ({ toLocation }) => {
    if (toLocation.pathname === SIGN_IN_PATH) signIn.redirecting = false
  })
  return router
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
