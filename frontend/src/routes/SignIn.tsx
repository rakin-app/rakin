import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import {
  codeDigits,
  redeemCode,
  rememberReturnPath,
  requestLink,
  retryAfterSeconds,
  SIGN_IN_PATH,
} from '../api/auth'
import { ApiError } from '../api/client'
import { hostQuery } from '../api/host'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { GymMark } from '../components/GymMark'
import { PageHeader } from '../components/PageHeader'
import { RakinLogo } from '../components/RakinLogo'
import { t } from '../i18n/es'
import { RAKIN, useDocumentTitle } from '../pageTitle'
import './SignIn.css'
import { useSubmit } from '../api/submit'

const copy = t.signIn
const route = getRouteApi(SIGN_IN_PATH)

/**
 * "Entrar": ask for a sign-in link by email. The answer is the same whether or not
 * the address has an account, so the screen never tells who is registered. On a
 * gym's own address it names the gym; until that loads, or if it never does, it is
 * Rakin's. Reached because a session expired, it says so first (#212).
 *
 * Once asked, it takes the six-digit code the link came with (#276): the app on an
 * iPhone's home screen never opens a link from mail, which opens in Safari instead, and
 * the two keep separate sessions. The code signs in right here.
 */
export function SignIn() {
  const { redirect, expired } = route.useSearch()
  const gym = useQuery(hostQuery()).data?.gym ?? null
  useDocumentTitle(copy.tab, gym?.name ?? RAKIN)
  const [email, setEmail] = useState('')
  const emailId = useId()
  const [code, setCode] = useState('')
  const [resent, setResent] = useState(false)
  const codeId = useId()
  const hintId = useId()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const send = useSubmit({
    mutationFn: (address: string) => requestLink(address),
    // Kept for when the link lands them on `/`, in whichever tab they open it.
    onSuccess: () => rememberReturnPath(redirect),
  })
  const enter = useSubmit({
    mutationFn: ({ address, typed }: { address: string; typed: string }) => redeemCode(address, typed),
    // Where the link would have gone: `/` sends them on to the page they had asked for.
    onSuccess: async ({ next }) => {
      queryClient.clear()
      await navigate({ href: next, replace: true })
    },
  })
  const address = send.variables ?? email.trim()

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const address = email.trim()
    if (address) send.mutate(address)
  }

  function submitCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (code.length === 6) enter.mutate({ address, typed: code })
  }

  function resend() {
    setCode('')
    setResent(true)
    enter.reset()
    send.mutate(address)
  }

  function another() {
    setCode('')
    setResent(false)
    enter.reset()
    send.reset()
  }

  return (
    <div className="signin">
      <PageHeader
        mark={gym && <GymMark name={gym.name} logo={gym.logo} size="large" />}
        eyebrow={
          <>
            <RakinLogo className="signin__logo" />
            <span className="visually-hidden">{t.app.name}</span>
          </>
        }
        title={gym ? copy.titleAt(gym.name) : copy.title}
      />
      <div className="signin__card">
        {send.isSuccess || (resent && send.isPending) ? (
          <>
            <div role="status">
              <h2 className="signin__sent-title">{copy.sentTitle}</h2>
              <p className="signin__sent">{resent ? copy.resent : copy.sent(address)}</p>
            </div>
            <form className="signin__form" onSubmit={submitCode}>
              <label htmlFor={codeId} className="signin__label">
                {copy.codeLabel}
              </label>
              <Input
                id={codeId}
                className="signin__code"
                type="text"
                name="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                aria-describedby={hintId}
                required
                value={code}
                // Pasted as the email shows it, "123 456", it keeps the digits.
                onChange={(event) => setCode(codeDigits(event.target.value))}
              />
              <p id={hintId} className="signin__hint">
                {copy.codeHint}
              </p>
              {enter.isError && (
                <p className="signin__error" role="alert">
                  {codeProblem(enter.error, gym?.name ?? RAKIN)}
                </p>
              )}
              <Button
                type="submit"
                variant="primary"
                disabled={code.length !== 6 || enter.isPending}
                busy={enter.isPending}
              >
                {enter.isPending ? copy.codeChecking : copy.codeSubmit}
              </Button>
              {isExpired(enter.error) && (
                <Button onClick={resend} disabled={send.isPending} busy={send.isPending}>
                  {copy.resend}
                </Button>
              )}
            </form>
            <Button onClick={another}>{copy.another}</Button>
          </>
        ) : (
          <form className="signin__form" onSubmit={submit}>
            {expired && (
              <p className="signin__expired" role="status">
                {copy.expired}
              </p>
            )}
            <p className="signin__intro">{copy.intro}</p>
            <label htmlFor={emailId} className="signin__label">
              {copy.emailLabel}
            </label>
            <Input
              id={emailId}
              type="email"
              name="email"
              autoComplete="email"
              inputMode="email"
              autoCapitalize="none"
              spellCheck={false}
              required
              maxLength={254}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            {send.isError && (
              <p className="signin__error" role="alert">
                {problem(send.error)}
              </p>
            )}
            <Button type="submit" variant="primary" disabled={send.isPending} busy={send.isPending}>
              {send.isPending ? copy.sending : copy.submit}
            </Button>
          </form>
        )}
      </div>
    </div>
  )
}

function detailOf(error: Error | null): unknown {
  return error instanceof ApiError ? (error.body as { detail?: unknown } | undefined)?.detail : undefined
}

function isExpired(error: Error | null): boolean {
  return error instanceof ApiError && error.status === 400 && detailOf(error) === 'expired'
}

function codeProblem(error: Error, gym: string): string {
  if (!(error instanceof ApiError)) return copy.codeFailed
  if (error.status === 429) {
    const seconds = retryAfterSeconds(error.headers)
    return copy.codeTooMany(seconds === null ? null : Math.ceil(seconds / 60))
  }
  if (isExpired(error)) return copy.codeExpired
  if (error.status === 400 || error.status === 422) return copy.codeInvalid
  if (error.status === 403 && detailOf(error) === 'unreachable') return copy.codeUnreachable(gym)
  return copy.codeFailed
}

function problem(error: Error): string {
  if (!(error instanceof ApiError)) return copy.failed
  if (error.status === 429) {
    const seconds = retryAfterSeconds(error.headers)
    return copy.tooMany(seconds === null ? null : Math.ceil(seconds / 60))
  }
  if (error.status === 422) return copy.invalid
  return copy.failed
}
