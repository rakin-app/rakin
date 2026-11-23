import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  notFound,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'
import { appPath, hadSession, landingFor, markSignedIn, SIGN_IN_PATH } from './api/auth'
import { ApiError, onUnauthorized } from './api/client'
import { keepDrafts } from './api/drafts'
import { hostQuery } from './api/host'
import { accessOf, myAccessQuery, myselfQuery, type MyRole } from './api/me'
import { PLATFORM_PATH, PLATFORM_SIGN_IN_PATH, platformMeQuery } from './api/platform'
import { AdminLayout } from './layouts/AdminLayout'
import { t } from './i18n/es'
import { wearPractice, wearVocabulary } from './i18n/vocabulary'
import { MeLayout } from './layouts/MeLayout'
import { PlatformLayout } from './layouts/PlatformLayout'
import { CheckIn } from './routes/CheckIn'
import { Classes, validateClassesSearch } from './routes/Classes'
import { Expenses, validateExpensesSearch } from './routes/Expenses'
import { Finances, validateFinancesSearch } from './routes/Finances'
import { ExtraChargeDetail } from './routes/ExtraChargeDetail'
import { ExtraChargeNew, validateExtraChargeNewSearch } from './routes/ExtraChargeNew'
import { ExtraCharges } from './routes/ExtraCharges'
import { ClassTimer } from './routes/ClassTimer'
import { Join } from './routes/Join'
import { MeHome } from './routes/MeHome'
import { MyData } from './routes/MyData'
import { MemberDetail } from './routes/MemberDetail'
import { MemberImport } from './routes/MemberImport'
import { NewMember } from './routes/NewMember'
import { NotFound, NotFoundBody } from './routes/NotFound'
import { MonthSummary, validateMonthSummarySearch } from './routes/MonthSummary'
import { Payments, validatePaymentsSearch } from './routes/Payments'
import { PlatformGym } from './routes/PlatformGym'
import { PlatformGyms } from './routes/PlatformGyms'
import { PlatformNewGym } from './routes/PlatformNewGym'
import { PlatformSignIn } from './routes/PlatformSignIn'
import { Privacy, validatePrivacySearch } from './routes/Privacy'
import { SessionDetail } from './routes/SessionDetail'
import { SignIn } from './routes/SignIn'
import { Settings, SETTINGS_SECTIONS, SettingsHome } from './routes/Settings'
import { Students, validateStudentsSearch } from './routes/Students'
import { Today } from './routes/Today'
import { trackTrail } from './trail'
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
    const me = await queryClient.ensureQueryData({ ...myAccessQuery(), retry: false })
    // The gym's words, before the shell's first screen reads them (#344).
    const myself = queryClient.getQueryData(myselfQuery().queryKey)
    wearVocabulary(myself?.vocabulary)
    wearPractice(myself?.practice)
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
    throw redirect({ href: me ? landingFor(accessOf(me)) : '/admin', replace: true })
  },
})

// A search flag, as the URL or a navigation gives it.
const flag = (value: unknown): true | undefined => (value === true || value === 'true' ? true : undefined)

// "Entrar": open to a signed-out visitor, as is the join form.
const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: SIGN_IN_PATH,
  // Set even when it is no path of ours: the root passes the raw query through, and
  // only an explicit `undefined` overrides it.
  // `expired`: the session ended rather than never began, which the page says (#212).
  // `noPanel`: signed in, with neither a place on the team nor a student page (#418).
  validateSearch: (search: Record<string, unknown>): { redirect?: string; expired?: true; noPanel?: true } => ({
    redirect: appPath(search.redirect),
    expired: flag(search.expired),
    noPanel: flag(search.noPanel),
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

// /admin/*: gym owners and coaches. Someone on no team, from an old bookmark or after
// leaving it, goes to their student page, or with none to sign in with another email
// (#418); staff who also train still reach /me from the nav.
const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'admin',
  beforeLoad: async ({ context, location }) => {
    const me = await requireSession(context, location.href)
    if (me === undefined || accessOf(me) !== null) return
    if (me.student_page) throw redirect({ to: '/me', replace: true })
    throw redirect({ to: SIGN_IN_PATH, search: { redirect: appPath(location.href), noPanel: true }, replace: true })
  },
  component: AdminLayout,
  // An unknown /admin path stays in the shell (#362).
  notFoundComponent: NotFoundBody,
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
  validateSearch: validateClassesSearch,
  component: Classes,
})

// "Entrada": checking people in at the door, for a gym with open access (#348).
const adminCheckInRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'entrada',
  component: CheckIn,
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

// Pagos › "Resumen del mes" (#505): what happened after the reminders and nudges.
const adminMonthSummaryRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos/resumen',
  validateSearch: validateMonthSummarySearch,
  component: MonthSummary,
})

// Finanzas (#316): money in and money out side by side, the month and the year, for who
// sees expenses.
const adminFinancesRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'finanzas',
  validateSearch: validateFinancesSearch,
  component: Finances,
})

// Finanzas › "Gastos" (#314): what the gym spends, apart from billing, by month.
const adminExpensesRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'finanzas/gastos',
  validateSearch: validateExpensesSearch,
  component: Expenses,
})

// Where Gastos was before Finanzas (#314), for a link or bookmark from then.
const adminOldExpensesRoute = createRoute({
  getParentRoute: () => adminRoute,
  path: 'pagos/gastos',
  validateSearch: validateExpensesSearch,
  beforeLoad: ({ search }) => {
    throw redirect({ to: '/admin/finanzas/gastos', search, replace: true })
  },
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
  validateSearch: validateExtraChargeNewSearch,
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

// "Mis datos" (#371): everything the gym holds on the student, with its download.
const meDataRoute = createRoute({
  getParentRoute: () => meRoute,
  path: 'datos',
  component: MyData,
})

/**
 * The platform's panel (#436) is the base host's alone: on a gym's own address it is not
 * found, as the API answers there. Whether this is a gym's address is asked once; if
 * that fails, the panel's own calls still answer 404 there.
 */
async function requireBaseHost({ queryClient }: AppContext) {
  const host = await queryClient.ensureQueryData({ ...hostQuery(), retry: false }).catch(() => undefined)
  if (host?.gym) throw notFound()
}

// "Entrar a la plataforma": an operator's sign-in, apart from a gym's `/ingresar`.
const platformSignInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: PLATFORM_SIGN_IN_PATH,
  beforeLoad: ({ context }) => requireBaseHost(context),
  component: PlatformSignIn,
})

// /plataforma/*: the platform's operators (#433), beside /admin and never inside a gym.
// No operator session (a 401) goes to its own sign-in; any other failure renders the
// shell, whose screens say what did not load.
const platformRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: PLATFORM_PATH,
  beforeLoad: async ({ context }) => {
    await requireBaseHost(context)
    // This check redirects on its own 401, as `requireSession` does.
    context.signIn.checking += 1
    try {
      await context.queryClient.ensureQueryData({ ...platformMeQuery(), retry: false })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        throw redirect({ to: PLATFORM_SIGN_IN_PATH, replace: true })
      }
    } finally {
      context.signIn.checking -= 1
    }
  },
  component: PlatformLayout,
})

// "Gimnasios": every gym Rakin hosts.
const platformGymsRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: '/',
  component: PlatformGyms,
})

// "Nuevo gimnasio" (#437): an operator adds a gym.
const platformNewGymRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: 'nuevo',
  component: PlatformNewGym,
})

// One gym's edit screen (#438), opened from the list.
const platformGymRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: '$gymId',
  component: PlatformGym,
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
    adminCheckInRoute,
    adminSessionRoute,
    adminSessionTimerRoute,
    adminPaymentsRoute,
    adminProofReviewRoute,
    adminMonthSummaryRoute,
    adminFinancesRoute,
    adminExpensesRoute,
    adminOldExpensesRoute,
    adminExtraChargesRoute,
    adminExtraChargeNewRoute,
    adminExtraChargeRoute,
    adminSettingsRoute.addChildren([adminSettingsIndexRoute, ...adminSettingsSectionRoutes]),
  ]),
  meRoute.addChildren([meHomeRoute, meDataRoute]),
  platformSignInRoute,
  platformRoute.addChildren([platformGymsRoute, platformNewGymRoute, platformGymRoute]),
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
    // Back, by the browser or a back link, finds a list where it was scrolled (#250).
    scrollRestoration: true,
  })
  // What a back link returns to: the pages this load has shown (#250).
  trackTrail(router.history)
  // A session that ends mid-use (a 401 on any call) goes back to sign in, the same way
  // a signed-out visitor does, saying it expired; what it had loaded is forgotten.
  onUnauthorized(() => {
    const { pathname, href } = router.state.location
    // The panel's session is its own (#436): it ends into the panel's sign-in, and
    // keeps no gym's drafts.
    if (pathname === PLATFORM_PATH || pathname.startsWith(`${PLATFORM_PATH}/`)) {
      if (pathname === PLATFORM_SIGN_IN_PATH || signIn.checking > 0) return
      context.queryClient.clear()
      void router.navigate({ to: PLATFORM_SIGN_IN_PATH, replace: true })
      return
    }
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

declare module '@tanstack/history' {
  interface HistoryState {
    // "Nuevo alumno" asked for the welcome then: the ficha waits for it (#246).
    welcomeSince?: number
    // "Agregar exalumno" just added them: the ficha offers "Agregar historial" (#294).
    offerHistory?: boolean
  }
}
