import { useMutation } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { rememberReturnPath, requestLink, retryAfterSeconds, SIGN_IN_PATH } from '../api/auth'
import { ApiError } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import './SignIn.css'

const copy = t.signIn
const route = getRouteApi(SIGN_IN_PATH)

/**
 * "Entrar": ask for a sign-in link by email. The answer is the same whether or not
 * the address has an account, so the screen never tells who is registered.
 */
export function SignIn() {
  const { redirect } = route.useSearch()
  const [email, setEmail] = useState('')
  const emailId = useId()
  const send = useMutation({
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
      <PageHeader eyebrow={t.app.name} title={copy.title} />
      <div className="signin__card">
        {send.isSuccess ? (
          <>
            <p role="status">{copy.sent(send.variables ?? email.trim())}</p>
            <button type="button" className="signin__button" onClick={() => send.reset()}>
              {copy.another}
            </button>
          </>
        ) : (
          <form className="signin__form" onSubmit={submit}>
            <p className="signin__intro">{copy.intro}</p>
            <label htmlFor={emailId} className="signin__label">
              {copy.emailLabel}
            </label>
            <input
              id={emailId}
              className="signin__input"
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
            <button type="submit" className="signin__button signin__button--primary" disabled={send.isPending}>
              {send.isPending ? copy.sending : copy.submit}
            </button>
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
