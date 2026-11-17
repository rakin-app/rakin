import type { RequirementState } from '../api/requirements'
import { t } from '../i18n/es'
import { StatusPill, type Status } from './StatusPill'

const PILL: Record<RequirementState, Status> = {
  ok: 'done',
  expiring: 'expiring',
  expired: 'overdue',
  pending: 'required',
}

/** Al día, vence pronto, vencido or pendiente (#349), on the ficha and the student page. */
export function RequirementPill({ state }: { state: RequirementState }) {
  return <StatusPill status={PILL[state]}>{t.admin.member.requirements.state[state]}</StatusPill>
}

/** "Hecho el 1 de marzo de 2026 · vence el 1 de marzo de 2027", or null while never done. */
export function requirementDates(
  requirement: { state: RequirementState; done_on: string | null; expires_on: string | null },
  words: { done: (day: string) => string; until: (day: string) => string; expiredOn: (day: string) => string },
): string | null {
  if (requirement.done_on === null) return null
  const done = words.done(t.common.longDayYear(requirement.done_on))
  if (requirement.expires_on === null) return done
  const end = requirement.state === 'expired' ? words.expiredOn : words.until
  return `${done} · ${end(t.common.longDayYear(requirement.expires_on))}`
}
