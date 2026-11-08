/**
 * Thin fetch wrapper for the Rakin API.
 *
 * The API is served from the same origin as the SPA (Caddy in production, the
 * Vite proxy in development), so requests take relative paths only and carry
 * the session cookie with `credentials: 'same-origin'`. There is no base URL to
 * configure and no CORS.
 */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//')) {
    throw new Error(`apiFetch takes a same-origin path starting with "/", got "${path}"`)
  }

  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const body: unknown = response.status === 204 ? undefined : await readBody(response)

  if (!response.ok) {
    throw new ApiError(response.status, body)
  }
  return body as T
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text === '') return undefined
  const contentType = response.headers.get('Content-Type') ?? ''
  return contentType.includes('json') ? JSON.parse(text) : text
}
