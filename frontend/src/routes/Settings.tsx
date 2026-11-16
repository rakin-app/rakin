import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, Outlet, useRouterState } from '@tanstack/react-router'
import { useEffect, useRef, type ComponentType } from 'react'
import { useGrades } from '../api/activities'
import { managesGym, myRoleQuery } from '../api/me'
import { BackLink } from '../components/BackLink'
import { Card, listRowClass, ListRowContent } from '../components/Card'
import { ChevronRightIcon } from '../components/icons'
import { PageContainer, useDesktop } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { AccountSettings } from './AccountSettings'
import { BlockKindSettings } from './BlockKindSettings'
import { ClassTagSettings } from './ClassTagSettings'
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

type SectionKey = keyof typeof copy.sections & keyof typeof copy.descriptions

/** A section, its label and line read when shown: some name the gym's words (#344). */
function section<P extends string, C extends ComponentType>(path: P, key: SectionKey, component: C) {
  return {
    path,
    component,
    get label(): string {
      return copy.sections[key]
    },
    get description(): string {
      return copy.descriptions[key]
    },
  }
}

/**
 * The sections, in tab order: the router makes a route of each under `/admin/ajustes`,
 * and on a desktop the first is where it opens. A new section is its component and an
 * entry here, with the line the phone's list says it with.
 */
export const SETTINGS_SECTIONS = [
  section('gimnasio', 'gym', GymSettings),
  section('planes', 'plans', PlanSettings),
  section('programas', 'programs', ProgramSettings),
  section('horario', 'schedule', ScheduleSettings),
  section('etiquetas', 'tags', ClassTagSettings),
  section('bloques', 'blocks', BlockKindSettings),
  section('graduacion', 'grading', GradingSettings),
  section('campos', 'fields', FieldSettings),
  section('equipo', 'staff', StaffSettings),
  section('inscripcion', 'joinLink', JoinLinkSettings),
  section('cuenta', 'account', AccountSettings),
] as const satisfies readonly { path: string; label: string; description: string; component: ComponentType }[]

type Section = (typeof SETTINGS_SECTIONS)[number]

/** The sections the gym is offered: Graduación only while an activity grades (#245).
 * Its route stays, and says where to turn it on. */
function useSections(): readonly Section[] {
  const grades = useGrades()
  return grades ? SETTINGS_SECTIONS : SETTINGS_SECTIONS.filter((section) => section.path !== 'graduacion')
}

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
        <PageHeader
          title={inSection ? section.label : copy.title}
          back={inSection && <BackLink to="/admin/ajustes" label={copy.backLabel} />}
        />
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
  const sections = useSections()
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
      {sections.map((section) => (
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
  const sections = useSections()
  if (desktop) return <Navigate to={`/admin/ajustes/${SETTINGS_SECTIONS[0].path}`} replace />
  return (
    <nav aria-label={copy.sectionsLabel}>
      <Card as="ul" flush className="settings__card settings__card--rows settings__menu">
        {sections.map((section) => (
          <li key={section.path}>
            <Link to={`/admin/ajustes/${section.path}`} className={listRowClass(true)}>
              <ListRowContent title={section.label} detail={section.description} trailing={<ChevronRightIcon />} />
            </Link>
          </li>
        ))}
      </Card>
    </nav>
  )
}
