import { ApiError } from './client'

/**
 * The fields a 422 refused, from FastAPI's `detail` list: each field's path without
 * the leading `body` (`bank_account.rut`), to the error's type (`value_error`,
 * `missing`, `unknown_program`). A refusal of the body as a whole is under `''`. The
 * first refusal of a field wins. `skip` drops leading path segments that name no
 * field, such as the kind a plan's union is told apart by.
 */
export function validationErrors(error: unknown, skip: readonly string[] = []): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {}
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  if (!Array.isArray(detail)) return {}
  const errors: Record<string, string> = {}
  for (const item of detail as { loc?: unknown; type?: unknown }[]) {
    if (!Array.isArray(item.loc) || typeof item.type !== 'string') continue
    const path = item.loc.map(String)
    if (path[0] === 'body') path.shift()
    if (path[0] !== undefined && skip.includes(path[0])) path.shift()
    const field = path.join('.')
    if (!(field in errors)) errors[field] = item.type
  }
  return errors
}
