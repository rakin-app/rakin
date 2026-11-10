import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

/** One of the gym's names for a part of a class (backend `BlockKind`). A sparring
 * kind's time counts as sparring. */
export type BlockKind = {
  id: string
  name: string
  is_sparring: boolean
  position: number
  archived: boolean
  created_at: string
}

export type BlockKindChanges = Partial<{ name: string; is_sparring: boolean; archived: boolean }>

/** The gym's block kinds in its order, archived ones last. Any staff role may read them. */
export const blockKindsQuery = queryOptions({
  queryKey: ['block-kinds'],
  queryFn: () => apiFetch<BlockKind[]>('/api/block-kinds'),
})

/** A new kind goes last in the gym's order. */
export function createBlockKind(body: { name: string; is_sparring: boolean }): Promise<BlockKind> {
  return apiFetch<BlockKind>('/api/block-kinds', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change. */
export function updateBlockKind(id: string, changes: BlockKindChanges): Promise<BlockKind> {
  return apiFetch<BlockKind>(`/api/block-kinds/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** `ids` must name every kind of the gym, once. */
export function reorderBlockKinds(ids: string[]): Promise<BlockKind[]> {
  return apiFetch<BlockKind[]>('/api/block-kinds/order', { method: 'PUT', body: JSON.stringify({ ids }) })
}

/** Only a kind no session's block is of; one in use is archived instead. */
export function deleteBlockKind(id: string): Promise<void> {
  return apiFetch<void>(`/api/block-kinds/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** The 409 `block_kind_in_use`: how many sessions' blocks are of the kind. */
export function blocksInUse(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { code?: unknown; blocks?: unknown } } | undefined)?.detail
  return detail?.code === 'block_kind_in_use' && typeof detail.blocks === 'number' ? detail.blocks : null
}
