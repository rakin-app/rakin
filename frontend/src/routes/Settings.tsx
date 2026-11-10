import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import type { ComponentType } from 'react'
import { managesGym, myRoleQuery } from '../api/me'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
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
 * and the first is where it opens. A new section is its component and an entry here.
 */
export const SETTINGS_SECTIONS = [
  { path: 'gimnasio', label: copy.sections.gym, component: GymSettings },
  { path: 'planes', label: copy.sections.plans, component: PlanSettings },
  { path: 'programas', label: copy.sections.programs, component: ProgramSettings },
  { path: 'horario', label: copy.sections.schedule, component: ScheduleSettings },
  { path: 'bloques', label: copy.sections.blocks, component: BlockKindSettings },
  { path: 'graduacion', label: copy.sections.grading, component: GradingSettings },
  { path: 'campos', label: copy.sections.fields, component: FieldSettings },
  { path: 'equipo', label: copy.sections.staff, component: StaffSettings },
  { path: 'inscripcion', label: copy.sections.joinLink, component: JoinLinkSettings },
] as const satisfies readonly { path: string; label: string; component: ComponentType }[]

/**
 * "Ajustes": the gym's configuration, one section per route under it. Owner and admin
 * only, as the API is; a coach is told so and nothing is asked of the API. The
 * sections are a row of tabs that scrolls sideways on a phone once there are more
 * than fit (#57's other config screens hang off it).
 */
export function Settings() {
  const role = useQuery(myRoleQuery())

  return (
    <div className="settings">
      <PageHeader title={copy.title} />
      {managesGym(role.data) ? (
        <>
          <nav className="settings__sections" aria-label={copy.sectionsLabel}>
            {SETTINGS_SECTIONS.map((section) => (
              <Link key={section.path} to={`/admin/ajustes/${section.path}`} className="settings__section-link">
                {section.label}
              </Link>
            ))}
          </nav>
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
    </div>
  )
}
