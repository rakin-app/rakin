import { useMutation, useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { ADULT_AGE, ageOn, joinFormQuery, submitJoinRequest, type JoinSubmission } from '../api/join'
import { privacyPath } from '../api/privacy'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Field, FieldError, Input } from '../components/Field'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import './Join.css'

const copy = t.join
const route = getRouteApi('/unirse/$token')

type Drafts = {
  first_name: string
  last_name: string
  rut: string
  phone: string
  email: string
  dob: string
  guardian_name: string
  guardian_phone: string
  guardian_email: string
  website: string
}

const EMPTY: Drafts = {
  first_name: '',
  last_name: '',
  rut: '',
  phone: '',
  email: '',
  dob: '',
  guardian_name: '',
  guardian_phone: '',
  guardian_email: '',
  website: '',
}

const orNull = (value: string) => value.trim() || null

/**
 * "Inscríbete": the form behind a gym's join link (#154), for someone with no account,
 * on their phone. They fill in their own details, and a guardian's when their birth
 * date makes them a minor on the gym's today; what they send waits for the gym's staff
 * to approve. The answer is the same whoever they are, so the form never tells who the
 * gym, or any other, already knows. A link revoked, regenerated or past its last day
 * says it no longer works. Consent, which the form requires, is to the gym's privacy
 * notice (#168), which the checkbox links.
 */
export function Join() {
  const { token } = route.useParams()
  const form = useQuery(joinFormQuery(token))

  if (form.isPending) {
    return (
      <Shell>
        <p role="status">{copy.loading}</p>
      </Shell>
    )
  }
  if (form.isError) {
    if (form.error instanceof ApiError && form.error.status === 404) {
      return (
        <Shell>
          <p role="alert">{copy.invalid}</p>
        </Shell>
      )
    }
    return (
      <Shell>
        <p role="alert">{copy.error}</p>
        <Button onClick={() => void form.refetch()}>
          {copy.retry}
        </Button>
      </Shell>
    )
  }
  return (
    <Shell title={copy.title(form.data.gym)}>
      <JoinFormBody
        token={token}
        today={form.data.today}
        program={form.data.program}
        siteKey={form.data.human_check_site_key}
      />
    </Shell>
  )
}

function Shell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="join">
      <PageHeader eyebrow={copy.eyebrow} title={title ?? t.app.name} />
      <div className="join__card">{children}</div>
    </div>
  )
}

function JoinFormBody({
  token,
  today,
  program,
  siteKey,
}: {
  token: string
  today: string
  program: string | null
  siteKey: string | null
}) {
  const [drafts, setDrafts] = useState<Drafts>(EMPTY)
  const [consent, setConsent] = useState(false)
  // Sent without it: the form says so itself, in Spanish, rather than ask the API.
  const [consentMissing, setConsentMissing] = useState(false)
  const consentErrorId = useId()
  const [humanToken, setHumanToken] = useState<string | null>(null)
  // Bumped after a failed submission: a widget token is good once, so the widget starts over.
  const [humanRound, setHumanRound] = useState(0)
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })
  const age = ageOn(drafts.dob, today)
  const minor = age !== null && age < ADULT_AGE

  const send = useMutation({
    mutationFn: () => {
      const body: JoinSubmission = {
        first_name: drafts.first_name,
        last_name: drafts.last_name,
        rut: drafts.rut,
        phone: orNull(drafts.phone),
        email: orNull(drafts.email),
        dob: drafts.dob,
        guardian_name: minor ? orNull(drafts.guardian_name) : null,
        guardian_phone: minor ? orNull(drafts.guardian_phone) : null,
        guardian_email: minor ? orNull(drafts.guardian_email) : null,
        consent,
        website: drafts.website,
        human_check_token: humanToken,
      }
      return submitJoinRequest(token, body)
    },
    onError: () => {
      setHumanToken(null)
      setHumanRound((round) => round + 1)
    },
  })
  const errors = validationErrors(send.error)
  const error = (field: string) => {
    const code = errors[field]
    if (code === undefined) return undefined
    return copy.refused[code === 'missing' || code.startsWith('string_') ? code : field] ?? copy.refused.failed
  }

  if (send.isSuccess) {
    return <p role="status">{copy.done}</p>
  }

  const consentInvalid = consentMissing || (!consent && 'consent' in errors)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!consent) {
      setConsentMissing(true)
      return
    }
    send.mutate()
  }

  return (
    <form className="join__form" onSubmit={submit} noValidate>
      {program && <p className="join__program">{copy.program(program)}</p>}
      <p className="join__intro">{copy.intro}</p>
      <TextField label={copy.firstName} error={error('first_name')} value={drafts.first_name} autoComplete="given-name" onChange={(v) => set('first_name', v)} />
      <TextField label={copy.lastName} error={error('last_name')} value={drafts.last_name} autoComplete="family-name" onChange={(v) => set('last_name', v)} />
      <TextField label={copy.rut} hint={copy.rutHint} error={error('rut')} value={drafts.rut} autoComplete="off" onChange={(v) => set('rut', v)} />
      <TextField label={copy.dob} error={error('dob')} value={drafts.dob} type="date" max={today} autoComplete="bday" onChange={(v) => set('dob', v)} />
      <TextField
        label={copy.phone}
        hint={minor ? copy.minorPhoneHint : copy.phoneHint}
        error={error('phone')}
        value={drafts.phone}
        type="tel"
        autoComplete="tel"
        onChange={(v) => set('phone', v)}
      />
      <TextField
        label={copy.email}
        hint={minor ? copy.minorEmailHint : undefined}
        error={error('email')}
        value={drafts.email}
        type="email"
        autoComplete="email"
        onChange={(v) => set('email', v)}
      />
      {minor && (
        <fieldset className="join__guardian">
          <legend className="join__legend">{copy.guardianTitle}</legend>
          <p className="join__intro">{copy.guardianIntro}</p>
          <TextField label={copy.guardianName} error={error('guardian_name')} value={drafts.guardian_name} autoComplete="off" onChange={(v) => set('guardian_name', v)} />
          <TextField label={copy.guardianPhone} error={error('guardian_phone')} value={drafts.guardian_phone} type="tel" autoComplete="off" onChange={(v) => set('guardian_phone', v)} />
          <TextField label={copy.guardianEmail} error={error('guardian_email')} value={drafts.guardian_email} type="email" autoComplete="off" onChange={(v) => set('guardian_email', v)} />
        </fieldset>
      )}
      {/* The honeypot: out of sight and out of the tab order, so only a script fills it in. */}
      <div className="join__honeypot" aria-hidden="true">
        <label>
          {copy.honeypot}
          <input type="text" name="website" tabIndex={-1} autoComplete="off" value={drafts.website} onChange={(e) => set('website', e.target.value)} />
        </label>
      </div>
      <label className="join__consent">
        <input
          type="checkbox"
          checked={consent}
          aria-required="true"
          aria-invalid={consentInvalid}
          aria-describedby={consentInvalid ? consentErrorId : undefined}
          onChange={(e) => {
            setConsent(e.target.checked)
            setConsentMissing(false)
          }}
        />
        <span>
          {copy.consentBefore}
          {/* A tab of its own, so what they have typed stays here. */}
          <a className="join__link" href={privacyPath(token)} target="_blank" rel="noreferrer">
            {copy.consentLink}
          </a>
          {copy.consentAfter}
        </span>
      </label>
      {consentInvalid && (
        <FieldError id={consentErrorId}>{copy.refused.consent}</FieldError>
      )}
      {siteKey && <HumanCheck key={humanRound} siteKey={siteKey} onToken={setHumanToken} />}
      {send.isError && (
        <p className="join__error" role="alert">
          {problem(send.error, Object.keys(errors).length > 0)}
        </p>
      )}
      <Button type="submit" variant="primary" disabled={send.isPending}>
        {send.isPending ? copy.working : copy.submit}
      </Button>
    </form>
  )
}

function problem(error: Error, fields: boolean): string {
  if (fields) return copy.invalidFields
  if (error instanceof ApiError) {
    if (error.status === 429) return copy.tooMany
    if (error.status === 400) return copy.humanCheck
    if (error.status === 404) return copy.invalid
  }
  return copy.failed
}

/** A text field of the form, with its hint and the API's refusal of it underneath. */
function TextField({
  label,
  hint,
  error,
  value,
  onChange,
  type = 'text',
  autoComplete,
  max,
}: {
  label: string
  hint?: string
  error?: string
  value: string
  onChange: (value: string) => void
  type?: string
  autoComplete: string
  max?: string
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(control) => (
        <Input
          {...control}
          type={type}
          inputMode={type === 'tel' ? 'tel' : type === 'email' ? 'email' : undefined}
          autoCapitalize={type === 'email' ? 'none' : undefined}
          autoComplete={autoComplete}
          max={max}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  )
}

type TurnstileOptions = {
  sitekey: string
  callback: (token: string) => void
  'expired-callback': () => void
  'error-callback': () => void
}

type Turnstile = {
  render: (element: HTMLElement, options: TurnstileOptions) => string
  remove: (widgetId: string) => void
}

declare global {
  interface Window {
    turnstile?: Turnstile
  }
}

const TURNSTILE_SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

/**
 * Cloudflare Turnstile's widget, when the instance checks for humans; its token goes
 * with the form. A token is good once and for a few minutes, so one that expires or
 * errors is dropped, and the form remounts the widget (its `key`) after a failed
 * submission, for a fresh one.
 */
function HumanCheck({ siteKey, onToken }: { siteKey: string; onToken: (token: string | null) => void }) {
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let widget: string | undefined
    const render = () => {
      if (box.current && window.turnstile && widget === undefined) {
        widget = window.turnstile.render(box.current, {
          sitekey: siteKey,
          callback: onToken,
          'expired-callback': () => onToken(null),
          'error-callback': () => onToken(null),
        })
      }
    }
    let script = document.querySelector<HTMLScriptElement>(`script[src="${TURNSTILE_SCRIPT}"]`)
    if (!script) {
      script = document.createElement('script')
      script.src = TURNSTILE_SCRIPT
      script.async = true
      document.head.appendChild(script)
    }
    if (window.turnstile) render()
    else script.addEventListener('load', render)
    return () => {
      script.removeEventListener('load', render)
      if (widget !== undefined) window.turnstile?.remove(widget)
    }
  }, [siteKey, onToken])

  return <div ref={box} className="join__human-check" />
}
