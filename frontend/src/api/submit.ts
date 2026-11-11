/**
 * One run per submission (#201): every form's mutation is a `useSubmit`.
 *
 * A double tap reaches the handler twice before the button re-renders disabled,
 * since `isPending` arrives with React Query's batched notify, not synchronously.
 * So the hook does two things `useMutation` does not:
 *
 * - While a submission runs, a second one with the same variables is the same
 *   submission: `mutate` drops it and `mutateAsync` hands back the first's promise.
 *   Different variables (another student's attendance) run as before.
 * - Each submission carries a key, which `apiFetch` sends as `Idempotency-Key` on its
 *   mutating request. The server keeps the answer a day and replays it for a request
 *   with the same key (`app.idempotency`), so a repeat that slips past the first
 *   guard, or a retry after a dropped connection that did land, runs once. The key
 *   lasts until the submission succeeds; after an error, the retry sends it again.
 *
 * `apiFetch` reads the key synchronously, when it is called. The first mutating
 * request of a submission takes the key and any more made in the same tick take
 * `<key>:2`, `<key>:3`: the same on a retry. A request made after an `await` gets
 * none unless the flow passes one: `submissionKey()` read at its start, with a step
 * name (`submitProof`).
 */
import { useMutation, type UseMutationOptions, type UseMutationResult } from '@tanstack/react-query'
import { useCallback, useMemo, useRef } from 'react'

type Running = { key: string; taken: number }

let running: Running | null = null

/** Run `start` as the submission `key`: the requests it makes before its first `await`. */
export function withSubmission<T>(key: string, start: () => T): T {
  const previous = running
  running = { key, taken: 0 }
  try {
    return start()
  } finally {
    running = previous
  }
}

/** The key for the next mutating request of the submission starting now, if any. */
export function takeSubmissionKey(): string | undefined {
  if (running === null) return undefined
  running.taken += 1
  return running.taken === 1 ? running.key : `${running.key}:${running.taken}`
}

/** The key of the submission starting now, for a flow to name its later steps by. */
export function submissionKey(): string | undefined {
  return running?.key
}

/** A random UUID, where `crypto.randomUUID` is missing too (plain http on a LAN). */
export function newKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function identify(variables: unknown): string {
  return JSON.stringify(variables) ?? ''
}

/** `useMutation`, for a form: a repeat while it runs is the same submission, and keyed. */
export function useSubmit<TData = unknown, TError = Error, TVariables = void, TContext = unknown>(
  options: UseMutationOptions<TData, TError, TVariables, TContext>,
): UseMutationResult<TData, TError, TVariables, TContext> {
  const keys = useRef(new Map<string, string>())
  const inFlight = useRef(new Map<string, Promise<TData>>())
  const { mutationFn } = options
  const mutation = useMutation({
    ...options,
    mutationFn: (variables, context) => {
      if (mutationFn === undefined) throw new Error('useSubmit needs a mutationFn')
      const id = identify(variables)
      let key = keys.current.get(id)
      if (key === undefined) {
        key = newKey()
        keys.current.set(id, key)
      }
      return withSubmission(key, () => mutationFn(variables, context)).then((data) => {
        keys.current.delete(id)
        return data
      })
    },
  })
  const { mutateAsync: run } = mutation

  type Result = UseMutationResult<TData, TError, TVariables, TContext>
  const mutateAsync = useCallback<Result['mutateAsync']>(
    (...args) => {
      const id = identify(args[0])
      const first = inFlight.current.get(id)
      if (first !== undefined) return first
      const started = run(...args).finally(() => inFlight.current.delete(id))
      inFlight.current.set(id, started)
      return started
    },
    [run],
  )
  const mutate = useCallback<Result['mutate']>(
    (...args) => {
      // As `mutate` does: the error is on the result, never thrown here.
      mutateAsync(...args).catch(() => {})
    },
    [mutateAsync],
  )
  return useMemo(() => ({ ...mutation, mutate, mutateAsync }), [mutation, mutate, mutateAsync])
}
