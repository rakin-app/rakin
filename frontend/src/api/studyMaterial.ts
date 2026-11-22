import { queryOptions, type QueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'

/**
 * Material de estudio (#537, backend `app.api.study_material`): notes and links a coach
 * shares on a class, or on a recurring class from a date on, for an audience chosen when
 * it is shared. Links are `https` addresses shown with their host: nothing is embedded.
 */

export const AUDIENCES = ['attendees', 'program', 'plans'] as const
export type Audience = (typeof AUDIENCES)[number]

// The backend's limits (`app.schemas.study_material`).
export const MAX_TITLE = 120
export const MAX_BODY = 5000
export const MAX_LINKS = 10

/** A material as staff read it on a class. A recurring one has no `session_id`, and the
 * date it shows from in `starts_on`. */
export type Material = {
  id: string
  title: string
  body: string | null
  links: string[]
  audience: Audience
  plans: { id: string; name: string }[]
  session_id: string | null
  starts_on: string | null
  shared_by_name: string | null
  created_at: string
  updated_at: string | null
}

/** A material on the student page, with the class it reached them through and its day. */
export type MyMaterial = {
  id: string
  title: string
  body: string | null
  links: string[]
  class_type_name: string
  program_name: string
  day: string
  recurring: boolean
  shared_by_name: string | null
  created_at: string
  /** The dependents it reaches, when it does not reach the signed-in person. */
  for_names: string[]
}

export type MaterialFields = {
  title: string
  body: string | null
  links: string[]
  audience: Audience
  plan_ids: string[]
}

/** New material; from a class, `recurring` puts it on its recurring class from `starts_on`. */
export type MaterialIn = MaterialFields & { recurring?: boolean; starts_on?: string | null }

/** Where a list of material lives: a class's, or a recurring class's. */
export type MaterialHost = { kind: 'session'; id: string } | { kind: 'slot'; id: string }

function hostPath(host: MaterialHost): string {
  const base = host.kind === 'session' ? '/api/sessions' : '/api/schedule'
  return `${base}/${encodeURIComponent(host.id)}/material`
}

export function materialQuery(host: MaterialHost) {
  return queryOptions({
    queryKey: ['material', host.kind, host.id],
    queryFn: () => apiFetch<Material[]>(hostPath(host)),
  })
}

export function myMaterialQuery() {
  return queryOptions({ queryKey: ['me', 'material'], queryFn: () => apiFetch<MyMaterial[]>('/api/me/material') })
}

export function shareMaterial(host: MaterialHost, body: MaterialIn): Promise<Material> {
  return apiFetch<Material>(hostPath(host), { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change. */
export function changeMaterial(id: string, body: Partial<MaterialFields> & { starts_on?: string }): Promise<Material> {
  return apiFetch<Material>(`/api/material/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) })
}

/** Members no longer see it; the gym's log keeps who removed it. */
export function removeMaterial(id: string): Promise<void> {
  return apiFetch<void>(`/api/material/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** A material shows on its class and on every class of its recurring class: every list. */
export function refreshMaterial(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: ['material'] })
}

/** The links typed one per line, blank lines dropped. */
export function linksOf(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

/** Whether `link` is one the backend takes: `https`, a host, no spaces. */
export function isHttpsLink(link: string): boolean {
  if (/\s/.test(link)) return false
  try {
    const url = new URL(link)
    return url.protocol === 'https:' && url.hostname !== ''
  } catch {
    return false
  }
}

/** The host a link goes to, as the list shows it: `youtube.com`, without `www.`. */
export function linkHost(link: string): string {
  try {
    return new URL(link).hostname.replace(/^www\./, '')
  } catch {
    return link
  }
}
