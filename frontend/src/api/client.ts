/**
 * Thin fetch wrapper for the Rakin API.
 *
 * The API is served from the same origin as the SPA (Caddy in production, the
 * Vite proxy in development), so requests take relative paths only and carry
 * the session cookie with `credentials: 'same-origin'`. There is no base URL to
 * configure and no CORS.
 *
 * A mutating request made by a form's submission (`useSubmit`) carries that
 * submission's `Idempotency-Key`, so the server runs it once however often it arrives.
 */
import { takeSubmissionKey } from './submit'

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
// The sign-in routes set cookies, which a replayed answer would not carry (`app.idempotency`):
// a gym's and the platform's (#436).
const UNKEYED_PREFIXES = ['/api/auth/', '/api/platform/auth/']

export type ApiInit = RequestInit & {
  /** The key for a step a submission makes after an `await`: `<submissionKey()>:<step>`. */
  idempotencyKey?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown
  readonly headers: Headers

  constructor(status: number, body: unknown, headers: Headers = new Headers()) {
    super(`API request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.headers = headers
  }
}

type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

/**
 * Who hears of a 401, from any call: the router, which sends the visitor to sign in
 * (`createAppRouter`). One handler at a time; the returned function removes it.
 */
export function onUnauthorized(handler: UnauthorizedHandler): () => void {
  unauthorizedHandler = handler
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null
  }
}

export async function apiFetch<T>(path: string, { idempotencyKey, ...init }: ApiInit = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new Error(`apiFetch takes a same-origin path starting with "/", got "${path}"`)
  }

  const headers = new Headers(init.headers)
  if (MUTATING.has((init.method ?? 'GET').toUpperCase()) && !UNKEYED_PREFIXES.some((prefix) => path.startsWith(prefix))) {
    // Read now, synchronously: after the first `await` the submission is no longer running.
    const key = idempotencyKey ?? takeSubmissionKey()
    if (key !== undefined) headers.set('Idempotency-Key', key)
  }
  headers.set('Accept', 'application/json')
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const body: unknown = response.status === 204 ? undefined : await readBody(response)

  if (!response.ok) {
    // A 401 `reauth` asks for a recent proof (#438): still signed in, so no sign-in.
    if (response.status === 401 && !isReauth(body)) unauthorizedHandler?.()
    throw new ApiError(response.status, body, response.headers)
  }
  return body as T
}

/** Whether a 401's body asks for a new proof of who is signed in (`{"code": "reauth"}`). */
export function isReauth(body: unknown): boolean {
  const detail = (body as { detail?: unknown } | undefined)?.detail
  return typeof detail === 'object' && detail !== null && (detail as { code?: unknown }).code === 'reauth'
}

/** An API refusal's detail, `{"detail": {"code": "receipt_taken", …}}`, or null. */
export function refusal(error: unknown): Record<string, unknown> | null {
  if (!(error instanceof ApiError)) return null
  const detail = (error.body as { detail?: unknown } | null)?.detail
  return typeof detail === 'object' && detail !== null && 'code' in detail ? (detail as Record<string, unknown>) : null
}

/** The code of an API refusal, or null. */
export function refusalCode(error: unknown): string | null {
  const detail = refusal(error)
  return detail ? String(detail.code) : null
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text === '') return undefined
  const contentType = response.headers.get('Content-Type') ?? ''
  if (!contentType.includes('json')) return text
  try {
    return JSON.parse(text)
  } catch {
    // A proxy error page can claim JSON; keep the text so the caller still gets the status.
    return text
  }
}
