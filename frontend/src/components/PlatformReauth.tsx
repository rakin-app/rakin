import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { codeDigits } from '../api/auth'
import { ApiError } from '../api/client'
import { platformMeQuery, reauth, sendReauthCode } from '../api/platform'
import { useSubmit } from '../api/submit'
import { t } from '../i18n/es'
import { Button } from './Button'
import { Banner, cardClass, SectionTitle } from './Card'
import { Input } from './Field'
import './PlatformReauth.css'

const copy = t.platform.reauth

/**
 * "Confirma que eres tú" (#438): an action of the panel that needs a recent proof was
 * refused with `reauth`. A code goes to the operator's email as soon as this opens; once
 * it is typed, the session is proved for 10 minutes and `onFresh` runs, which tries the
 * action again. Any action that asks for the proof shows it the same way.
 */
export function PlatformReauth({ onFresh, onCancel }: { onFresh: () => void; onCancel: () => void }) {
  const queryClient = useQueryClient()
  const me = useQuery(platformMeQuery())
  const [code, setCode] = useState('')
  const titleId = useId()
  const codeId = useId()
  const send = useSubmit({ offline: 'refuse', mutationFn: () => sendReauthCode() })
  const confirm = useSubmit({
    offline: 'refuse',
    mutationFn: (typed: string) => reauth(typed),
    onSuccess: async () => {
      // Its `fresh_until` moved.
      await queryClient.invalidateQueries({ queryKey: platformMeQuery().queryKey })
      onFresh()
    },
  })

  // Once, on opening: asking again would end the code just sent.
  const asked = useRef(false)
  const { mutate: ask } = send
  useEffect(() => {
    if (asked.current) return
    asked.current = true
    ask()
  }, [ask])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (code.length === 6) confirm.mutate(code)
  }

  const again = () => {
    setCode('')
    confirm.reset()
    send.mutate()
  }

  return (
    <section role="dialog" aria-labelledby={titleId} className={cardClass({}, 'platform-reauth')}>
      <SectionTitle as="h3" id={titleId}>
        {copy.title}
      </SectionTitle>
      {send.isPending ? (
        <p role="status">{copy.sending}</p>
      ) : send.isError ? (
        <Banner tone="error">{send.error instanceof ApiError && send.error.status === 429 ? copy.tooMany : copy.sendFailed}</Banner>
      ) : (
        <p role="status">{copy.sent(me.data?.email ?? '')}</p>
      )}
      <form className="platform-reauth__form" onSubmit={submit}>
        <label htmlFor={codeId} className="field__label">
          {copy.codeLabel}
        </label>
        <Input
          id={codeId}
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          value={code}
          onChange={(event) => setCode(codeDigits(event.target.value))}
        />
        {confirm.isError && <Banner tone="error">{codeProblem(confirm.error)}</Banner>}
        <div className="platform-reauth__actions">
          <Button onClick={onCancel}>{copy.cancel}</Button>
          <Button onClick={again} disabled={send.isPending}>
            {copy.again}
          </Button>
          <Button type="submit" variant="primary" disabled={code.length !== 6 || confirm.isPending} busy={confirm.isPending}>
            {confirm.isPending ? copy.checking : copy.submit}
          </Button>
        </div>
      </form>
    </section>
  )
}

function codeProblem(error: Error): string {
  if (!(error instanceof ApiError)) return copy.failed
  if (error.status === 400) return copy.invalid
  if (error.status === 429) return copy.tooMany
  return copy.failed
}
