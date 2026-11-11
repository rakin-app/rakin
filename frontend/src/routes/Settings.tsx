import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, Outlet, useRouterState } from '@tanstack/react-router'
import { useEffect, useRef, type ComponentType } from 'react'
import { managesGym, myRoleQuery } from '../api/me'
import { buttonClass } from '../components/Button'
import { ListRowContent, listRowClass } from '../components/Card'
import { ChevronLeftIcon, ChevronRightIcon } from '../components/icons'
import { PageContainer, useDesktop } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { AccountSettings } from './AccountSettings'
import { BlockKindSettings } from './BlockKindSettings'
import { FieldSettings } from './FieldSettings'
import { GradingSettings } from './GradingSettings'
import { GymSettings } from './GymSettings'
import { JoinLinkSettings } from './JoinLinkSettings'
import { PlanSettings } from './PlanSettings'
import { ProgramSettings } from './ProgramSettings'
import { ScheduleSettings } from './ScheduleSettings'
import { StaffSettings } from './StaffSettings'
import { AdminsOnly } from './settingsForm'
import './Settings.css'

const copy = t.admin.settings

/**
 * The sections, in tab order: the router makes a route of each under `/admin/ajustes`,
 * and on a desktop the first is where it opens. A new section is its component and an
 * entry here, with the line the phone's list says it with.
 */
export const SETTINGS_SECTIONS = [
  { path: 'gimnasio', label: copy.sections.gym, description: copy.descriptions.gym, component: GymSettings },
  { path: 'planes', label: copy.sections.plans, description: copy.descriptions.plans, component: PlanSettings },
  {
    path: 'programas',
    label: copy.sections.programs,
    description: copy.descriptions.programs,
    component: ProgramSettings,
  },
  {
    path: 'horario',
    label: copy.sections.schedule,
    description: copy.descriptions.schedule,
    component: ScheduleSettings,
  },
  { path: 'bloques', label: copy.sections.blocks, description: copy.descriptions.blocks, component: BlockKindSettings },
  {
    path: 'graduacion',
    label: copy.sections.grading,
    description: copy.descriptions.grading,
    component: GradingSettings,
  },
  { path: 'campos', label: copy.sections.fields, description: copy.descriptions.fields, component: FieldSettings },
  { path: 'equipo', label: copy.sections.staff, description: copy.descriptions.staff, component: StaffSettings },
  {
    path: 'inscripcion',
    label: copy.sections.joinLink,
    description: copy.descriptions.joinLink,
    component: JoinLinkSettings,
  },
  { path: 'cuenta', label: copy.sections.account, description: copy.descriptions.account, component: AccountSettings },
] as const satisfies readonly { path: string; label: string; description: string; component: ComponentType }[]

type Section = (typeof SETTINGS_SECTIONS)[number]

/** The section `pathname` is on, if any: `/admin/ajustes/planes` is Planes. */
function sectionOf(pathname: string): Section | undefined {
  const match = /^\/admin\/ajustes\/([^/]+)/.exec(pathname)
  return SETTINGS_SECTIONS.find((section) => section.path === match?.[1])
}

/**
 * "Ajustes": the gym's configuration, one section per route under it. Owner and admin
 * only, as the API is; a coach is told so and nothing is asked of the API.
 *
 * On a phone it opens on a list of the sections, each with its line, and a section's
 * page has a way back to it (#177): a row of nine tabs hid most of them off the side.
 * From 960px the sections are tabs over the open one, the open tab scrolled into view.
 */
export function Settings() {
  const role = useQuery(myRoleQuery())
  const desktop = useDesktop()
  const section = sectionOf(useRouterState({ select: (state) => state.location.pathname }))
  usePageTitle(section?.label ?? copy.title)
  // A phone's section page is titled by its section, under a way back to the list.
  const inSection = !desktop && section !== undefined

  return (
    <div className="settings">
      <PageContainer>
        {inSection && (
          <Link
            to="/admin/ajustes"
            aria-label={copy.backLabel}
            className={buttonClass({ variant: 'ghost', className: 'settings__back' })}
          >
            <ChevronLeftIcon />
            {copy.back}
          </Link>
        )}
        <PageHeader title={inSection ? section.label : copy.title} />
        {managesGym(role.data) ? (
          <>
            {desktop && <SectionTabs current={section} />}
            <div className="settings__body">
              <Outlet />
            </div>
          </>
        ) : role.isError ? (
          <p className="settings__note" role="alert">
            {copy.roleError}
          </p>
        ) : (
          role.isSuccess && <AdminsOnly />
        )}
      </PageContainer>
    </div>
  )
}

/** The sections as tabs, on a desktop: a row that scrolls sideways if they do not fit, and keeps the open one in view. */
function SectionTabs({ current }: { current: Section | undefined }) {
  const nav = useRef<HTMLElement>(null)
  useEffect(() => {
    const active = nav.current?.querySelector<HTMLElement>('[aria-current="page"]')
    // `scrollIntoView` on the row's own axis only, so the page itself does not jump.
    if (active && nav.current && typeof nav.current.scrollTo === 'function') {
      const row = nav.current
      const left = active.offsetLeft - row.offsetLeft
      if (left < row.scrollLeft || left + active.offsetWidth > row.scrollLeft + row.clientWidth) {
        row.scrollTo({ left: left - (row.clientWidth - active.offsetWidth) / 2 })
      }
    }
  }, [current])
  return (
    <nav ref={nav} className="settings__sections" aria-label={copy.sectionsLabel}>
      {SETTINGS_SECTIONS.map((section) => (
        <Link key={section.path} to={`/admin/ajustes/${section.path}`} className="settings__section-link">
          {section.label}
        </Link>
      ))}
    </nav>
  )
}

/**
 * Where `/admin/ajustes` itself lands: on a phone, the list of sections; on a desktop,
 * which has the tabs, the first section.
 */
export function SettingsHome() {
  const desktop = useDesktop()
  if (desktop) return <Navigate to={`/admin/ajustes/${SETTINGS_SECTIONS[0].path}`} replace />
  return (
    <nav aria-label={copy.sectionsLabel}>
      <ul className="settings__card settings__card--rows settings__menu">
        {SETTINGS_SECTIONS.map((section) => (
          <li key={section.path}>
            <Link to={`/admin/ajustes/${section.path}`} className={listRowClass(true)}>
              <ListRowContent title={section.label} detail={section.description} trailing={<ChevronRightIcon />} />
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
