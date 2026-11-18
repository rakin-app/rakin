import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { codeDigits, retryAfterSeconds } from '../api/auth'
import { ApiError } from '../api/client'
import { redeemPlatformCode, requestPlatformLink } from '../api/platform'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Input } from '../components/Field'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import './SignIn.css'

const copy = t.platform.signIn

/**
 * "Entrar a la plataforma" (#436): an operator's email, then "revisa tu correo" with the
 * code the link came with, as a gym's `SignIn` asks. The answer is the same whether or
 * not the address is an operator's. The link itself lands on `/plataforma`.
 */
export function PlatformSignIn() {
  useDocumentTitle(copy.tab, t.platform.tab)
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const emailId = useId()
  const codeId = useId()
  const hintId = useId()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const send = useSubmit({ mutationFn: (address: string) => requestPlatformLink(address) })
  const enter = useSubmit({
    mutationFn: ({ address, typed }: { address: string; typed: string }) => redeemPlatformCode(address, typed),
    onSuccess: async ({ next }) => {
      queryClient.clear()
      await navigate({ href: next, replace: true })
    },
  })
  const address = send.variables ?? email.trim()

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const typed = email.trim()
    if (typed) send.mutate(typed)
  }

  function submitCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (code.length === 6) enter.mutate({ address, typed: code })
  }

  function another() {
    setCode('')
    enter.reset()
    send.reset()
  }

  return (
    <main className="signin">
      <PageHeader eyebrow={t.platform.brand} title={copy.title} />
      <Card as="div" className="signin__card">
        {send.isSuccess ? (
          <>
            <div role="status">
              <h2 className="signin__sent-title">{copy.sentTitle}</h2>
              <p className="signin__sent">{copy.sent(address)}</p>
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
                onChange={(event) => setCode(codeDigits(event.target.value))}
              />
              <p id={hintId} className="signin__hint">
                {copy.codeHint}
              </p>
              {enter.isError && (
                <p className="signin__error" role="alert">
                  {codeProblem(enter.error)}
                </p>
              )}
              <Button type="submit" variant="primary" disabled={code.length !== 6 || enter.isPending} busy={enter.isPending}>
                {enter.isPending ? copy.codeChecking : copy.codeSubmit}
              </Button>
            </form>
            <Button onClick={another}>{copy.another}</Button>
          </>
        ) : (
          <form className="signin__form" onSubmit={submit}>
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
      </Card>
    </main>
  )
}

function tooMany(error: ApiError): string {
  const seconds = retryAfterSeconds(error.headers)
  return copy.tooMany(seconds === null ? null : Math.ceil(seconds / 60))
}

function codeProblem(error: Error): string {
  if (!(error instanceof ApiError)) return copy.codeFailed
  if (error.status === 429) return tooMany(error)
  if (error.status === 400 || error.status === 422) return copy.codeInvalid
  return copy.codeFailed
}

function problem(error: Error): string {
  if (!(error instanceof ApiError)) return copy.failed
  if (error.status === 429) return tooMany(error)
  if (error.status === 422) return copy.invalid
  return copy.failed
}
