import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useSignOut } from '../api/auth'
import { managesGym, myAccessQuery, myselfQuery, readsExpenses, readsLedger } from '../api/me'
import { pendingCountQuery } from '../api/proofs'
import { useTimerSync } from '../api/sessionBlocks'
import { GymMark } from '../components/GymMark'
import { InstallHint } from '../components/InstallHint'
import { RakinLogo } from '../components/RakinLogo'
import { ClassesIcon, MyPageIcon, PaymentsIcon, SettingsIcon, SignOutIcon, StudentsIcon, TodayIcon } from '../components/icons'
import { t } from '../i18n/es'
import { useRise } from '../motion'
import { useGymName } from '../pageTitle'
import { PlainList } from '../components/Card'
import { TermsAcceptance } from '../routes/TermsAcceptance'
import { TermsPending } from '../routes/TermsPending'
import './AdminLayout.css'

type NavItem = {
  to: '/admin' | '/admin/alumnos' | '/admin/clases' | '/admin/pagos' | '/admin/pagos/gastos' | '/admin/ajustes'
  label: string
  icon: ReactNode
  exact?: boolean
}

// Each label read when the nav renders: "Alumnos" is the gym's word for its members (#344).
const NAV_ITEMS: readonly NavItem[] = [
  { to: '/admin', label: t.nav.today, icon: <TodayIcon />, exact: true },
  {
    to: '/admin/alumnos',
    get label() {
      return t.nav.students
    },
    icon: <StudentsIcon />,
  },
  { to: '/admin/clases', label: t.nav.classes, icon: <ClassesIcon /> },
  { to: '/admin/pagos', label: t.nav.payments, icon: <PaymentsIcon /> },
  { to: '/admin/ajustes', label: t.nav.settings, icon: <SettingsIcon /> },
]

// In Pagos' place, for someone who sees the gym's expenses and not its payments (#314):
// Gastos is under Pagos for everyone else, and the bar keeps to five tabs.
const EXPENSES_ITEM: NavItem = { to: '/admin/pagos/gastos', label: t.admin.payments.expenses, icon: <PaymentsIcon /> }

/**
 * Shell for the owner and coach screens. On a phone the nav is the bottom tab
 * bar from the mobile designs, five tabs at most, under a dark bar with the mark and the
 * gym's name; from 960px it becomes the dark sidebar of the desktop ledger design, with
 * the gym's name under the mark (#199). One <nav>, restyled by CSS,
 * so both share a tab order. "Cerrar sesión" is the sidebar's last item; on a phone it
 * is in Ajustes → Cuenta instead, so the bar keeps to the sections (#177). A coach has no
 * Ajustes: theirs is in the account menu of the phone's top bar, never a tab one thumb-tap
 * from Clases at the mat (#358). "Mi página", the student page of staff who also train
 * (#214), sits above it in the sidebar: in Cuenta on an owner's phone, a fourth tab on a
 * coach's.
 */
export function AdminLayout() {
  const me = useQuery(myselfQuery()).data
  // Until the gym accepts its current terms (#499), its titular sees only the page to
  // accept them, on every path; while it never has, the rest of the team a notice.
  if (me && me.terms !== undefined && me.terms !== 'current') {
    if (me.account_holder) {
      return (
        <TermsGate>
          <TermsAcceptance />
        </TermsGate>
      )
    }
    if (me.terms === 'pending') {
      return (
        <TermsGate>
          <TermsPending gym={me.gym_name} titular={me.titular_name ?? null} />
        </TermsGate>
      )
    }
  }
  return <AdminShell />
}

/** The admin's bar with no nav, over the terms' page: the gym, and a way to sign out. */
function TermsGate({ children }: { children: ReactNode }) {
  const gym = useGymName()
  const logo = useQuery(myselfQuery()).data?.gym_logo
  const signOut = useSignOut()
  return (
    <div className="admin-shell admin-shell--gate">
      <header className="admin-top admin-top--gate">
        <span className="admin-top__brand">
          <RakinLogo surface="dark" />
        </span>
        {gym && (
          <span className="admin-top__gym">
            <GymMark name={gym} logo={logo} />
            <span className="admin-top__gym-name">{gym}</span>
          </span>
        )}
        <button type="button" className="admin-top__sign-out" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
          <SignOutIcon />
          <span>{signOut.isPending ? t.signOut.working : t.signOut.label}</span>
        </button>
      </header>
      <main className="admin-main admin-main--gate">
        {signOut.isError && (
          <p className="admin-nav__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
        {children}
      </main>
    </div>
  )
}

function AdminShell() {
  // Proofs waiting for review, on the Pagos tab: asked for only by those who read
  // the ledger, so a coach never polls a request that would be refused.
  const access = useQuery(myAccessQuery())
  const studentPage = useQuery(myselfQuery()).data?.student_page ?? false
  const signOut = useSignOut()
  // A class timed without signal reaches the API from whichever screen is open.
  useTimerSync()
  const pending = useQuery({ ...pendingCountQuery(), enabled: readsLedger(access.data) })
  const badge = pending.data ?? 0
  const gym = useGymName()
  const logo = useQuery(myselfQuery()).data?.gym_logo
  const rise = useRise<HTMLDivElement>()
  // Pagos is money and Ajustes the gym's configuration: each shown only once the role
  // is known to reach it, so a coach never sees either tab, not even while the role loads.
  // Someone who sees only expenses has Gastos where Pagos would be.
  const navItems = NAV_ITEMS.flatMap((item) => {
    if (item.to === '/admin/ajustes' && !managesGym(access.data)) return []
    if (item.to !== '/admin/pagos' || readsLedger(access.data)) return [item]
    return readsExpenses(access.data) ? [EXPENSES_ITEM] : []
  })

  // A coach's phone has no Ajustes: "Mi página" is a tab of their bar, and signing out is
  // in the top bar's account menu. Only once the role is known, so nothing flashes in.
  const coach = access.isSuccess && !managesGym(access.data)
  const myPageClass = coach ? 'admin-nav__end admin-nav__end--bar' : 'admin-nav__end'

  return (
    <div className="admin-shell">
      {/* A phone's dark bar over the page: the mark, and the gym's own with its name. */}
      <header className="admin-top">
        <span className="admin-top__brand">
          <RakinLogo surface="dark" />
        </span>
        {gym && (
          <span className="admin-top__gym">
            <GymMark name={gym} logo={logo} />
            <span className="admin-top__gym-name">{gym}</span>
          </span>
        )}
        {coach && <AccountMenu />}
      </header>
      <nav className="admin-nav" aria-label={t.nav.label}>
        <div className="admin-nav__head">
          <span className="admin-nav__brand">
            <RakinLogo surface="dark" />
          </span>
          {gym && (
            <span className="admin-nav__gym">
              <GymMark name={gym} logo={logo} />
              <span className="admin-nav__gym-name">{gym}</span>
            </span>
          )}
        </div>
        <PlainList className="admin-nav__list">
          {navItems.map((item) => (
            <li key={item.to}>
              <Link to={item.to} activeOptions={{ exact: item.exact ?? false }} className="admin-nav__link">
                <span className="admin-nav__icon">
                  {item.icon}
                  {item.to === '/admin/pagos' && badge > 0 && (
                    <span className="admin-nav__badge" aria-hidden="true">
                      {badge}
                    </span>
                  )}
                </span>
                <span>{item.label}</span>
                {item.to === '/admin/pagos' && badge > 0 && (
                  <span className="visually-hidden">{t.nav.pendingBadge(badge)}</span>
                )}
              </Link>
            </li>
          ))}
          {studentPage && (
            <li className={myPageClass}>
              <Link to="/me" className="admin-nav__link">
                <span className="admin-nav__icon">
                  <MyPageIcon />
                </span>
                <span>{t.nav.myPage}</span>
              </Link>
            </li>
          )}
          {/* The sidebar's; on a phone it is in Ajustes → Cuenta, or a coach's account menu. */}
          <li className="admin-nav__end">
            <button
              type="button"
              className="admin-nav__link"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              <span className="admin-nav__icon">
                <SignOutIcon />
              </span>
              <span>{t.signOut.label}</span>
            </button>
          </li>
        </PlainList>
        {signOut.isError && (
          <p className="admin-nav__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
      </nav>
      <main className="admin-main">
        <InstallHint />
        <div ref={rise} className="page-rise">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

/** A coach's account on a phone (#358): who is signed in, and "Cerrar sesión", behind one
 * button of the top bar, as an owner's are in Ajustes → Cuenta. */
function AccountMenu() {
  const me = useQuery(myselfQuery())
  const signOut = useSignOut()
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const root = useRef<HTMLDivElement>(null)

  // A tap elsewhere or Escape closes it.
  useEffect(() => {
    if (!open) return
    const away = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  return (
    <div ref={root} className="admin-account">
      <button
        type="button"
        className="admin-account__toggle"
        aria-label={t.nav.account}
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen(!open)}
      >
        <MyPageIcon />
      </button>
      <div id={menuId} className="admin-account__menu" hidden={!open}>
        {me.data?.name && <p className="admin-account__name">{me.data.name}</p>}
        <button
          type="button"
          className="admin-account__item"
          disabled={signOut.isPending}
          onClick={() => signOut.mutate()}
        >
          <SignOutIcon />
          <span>{signOut.isPending ? t.signOut.working : t.signOut.label}</span>
        </button>
        {signOut.isError && (
          <p className="admin-account__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
      </div>
    </div>
  )
}
