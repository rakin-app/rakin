import { useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { rememberReturnPath, requestLink, retryAfterSeconds, SIGN_IN_PATH } from '../api/auth'
import { ApiError } from '../api/client'
import { hostQuery } from '../api/host'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import './SignIn.css'
import { useSubmit } from '../api/submit'

const copy = t.signIn
const route = getRouteApi(SIGN_IN_PATH)

/**
 * "Entrar": ask for a sign-in link by email. The answer is the same whether or not
 * the address has an account, so the screen never tells who is registered. On a
 * gym's own address it names the gym; until that loads, or if it never does, it is
 * Rakin's. Reached because a session expired, it says so first (#212).
 */
export function SignIn() {
  const { redirect, expired } = route.useSearch()
  const gym = useQuery(hostQuery()).data?.gym ?? null
  const [email, setEmail] = useState('')
  const emailId = useId()
  const send = useSubmit({
    mutationFn: (address: string) => requestLink(address),
    // Kept for when the link lands them on `/`, in whichever tab they open it.
    onSuccess: () => rememberReturnPath(redirect),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const address = email.trim()
    if (address) send.mutate(address)
  }

  return (
    <div className="signin">
      <PageHeader eyebrow={t.app.name} title={gym ? copy.titleAt(gym.name) : copy.title} />
      <div className="signin__card">
        {send.isSuccess ? (
          <>
            <p role="status">{copy.sent(send.variables ?? email.trim())}</p>
            <Button onClick={() => send.reset()}>
              {copy.another}
            </Button>
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

function problem(error: Error): string {
  if (!(error instanceof ApiError)) return copy.failed
  if (error.status === 429) {
    const seconds = retryAfterSeconds(error.headers)
    return copy.tooMany(seconds === null ? null : Math.ceil(seconds / 60))
  }
  if (error.status === 422) return copy.invalid
  return copy.failed
}
