import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  createGym,
  newGymChoicesQuery,
  PLATFORM_PATH,
  platformGymsQuery,
  slugCheckQuery,
  type CreatedGym,
  type NewGymChoices,
} from '../api/platform'
import { useSubmit } from '../api/submit'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Banner, cardClass, SectionTitle } from '../components/Card'
import { Input, Select } from '../components/Field'
import { useFocusFirstInvalid } from '../components/focusInvalid'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import { Field, LoadFailed, refusal } from './settingsForm'
import './PlatformNewGym.css'

const copy = t.platform.newGym

// How long the slug rests before it is checked, so a check is not made per keystroke.
export const SLUG_CHECK_DELAY_MS = 300

const DEFAULT_TIMEZONE = 'America/Santiago'

type Drafts = {
  name: string
  slug: string
  timezone: string
  grading: string
  owner_email: string
  owner_name: string
  owner_rut: string
  owner_phone: string
  signed_on: string
}

const EMPTY: Drafts = {
  name: '',
  slug: '',
  timezone: DEFAULT_TIMEZONE,
  grading: 'none',
  owner_email: '',
  owner_name: '',
  owner_rut: '',
  owner_phone: '',
  signed_on: '',
}

const REFUSALS = { range: {}, value: copy.refusals as Record<string, string> }

/** `value`, once it has stayed the same for `delay` ms. */
function useSettled<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return settled
}

/**
 * "Nuevo gimnasio" (#437): an operator adds a gym, with the same fields `python -m
 * app.gyms create` takes and the Términos de encargo always. The slug is checked as it
 * is typed, with the address it makes; once created, that address works at once and its
 * titular has been emailed a link to sign in there.
 */
export function PlatformNewGym() {
  useDocumentTitle(copy.tab, t.platform.tab)
  const choices = useQuery(newGymChoicesQuery())
  const [created, setCreated] = useState<{ gym: CreatedGym; name: string; email: string } | null>(null)
  return (
    <>
      <PageHeader title={created ? copy.created : copy.title} />
      {created ? (
        <Created {...created} again={() => setCreated(null)} />
      ) : choices.isPending ? (
        <Loading className="platform-new__note" role="status">
          {copy.loading}
        </Loading>
      ) : choices.isError ? (
        <LoadFailed error={choices.error} message={copy.failedChoices} retry={() => void choices.refetch()} />
      ) : (
        <NewGymForm choices={choices.data} onCreated={setCreated} />
      )}
    </>
  )
}

function NewGymForm({
  choices,
  onCreated,
}: {
  choices: NewGymChoices
  onCreated: (created: { gym: CreatedGym; name: string; email: string }) => void
}) {
  const queryClient = useQueryClient()
  const [drafts, setDrafts] = useState(EMPTY)
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  const slug = useSettled(drafts.slug, SLUG_CHECK_DELAY_MS)
  const check = useQuery({ ...slugCheckQuery(slug), enabled: slug !== '' })
  const checked = slug === drafts.slug && check.data ? check.data : null

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: createGym,
    onSuccess: (gym, sent) => {
      void queryClient.invalidateQueries({ queryKey: platformGymsQuery().queryKey })
      onCreated({ gym, name: drafts.name.trim(), email: sent.owner_email })
    },
  })
  const errors = validationErrors(save.error)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusFirstInvalid(formRef, save.error)
  const errorOf = (field: keyof Drafts) =>
    field in errors ? refusal(errors[field]!, field, REFUSALS, drafts[field].trim() === '') : undefined

  // Read-only, so refused only when the terms changed while the form was open.
  const termsError =
    'processor_terms' in errors ? refusal(errors.processor_terms!, 'processor_terms', REFUSALS, false) : undefined

  // The live check's problem until the form is sent; then the API's refusal, if any.
  const slugError =
    errorOf('slug') ?? (checked?.problem && drafts.slug !== '' ? copy.problems[checked.problem] : undefined)
  const slugHint =
    drafts.slug === '' ? copy.slugHint : checked && !checked.problem ? copy.willBe(checked.address) : copy.checking

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const optional = (value: string) => value.trim() || null
    save.mutate({
      slug: drafts.slug,
      name: drafts.name,
      timezone: drafts.timezone,
      owner_email: drafts.owner_email.trim(),
      owner_name: drafts.owner_name,
      owner_rut: optional(drafts.owner_rut),
      owner_phone: optional(drafts.owner_phone),
      grading: drafts.grading,
      processor_terms: choices.terms_version,
      signed_on: drafts.signed_on || null,
    })
  }

  const zones = choices.timezones.includes(DEFAULT_TIMEZONE)
    ? choices.timezones
    : [DEFAULT_TIMEZONE, ...choices.timezones]

  return (
    <form ref={formRef} className="platform-new" aria-label={copy.title} onSubmit={submit} noValidate>
      <fieldset className={cardClass({}, 'platform-new__card')}>
        <SectionTitle as="legend" className="platform-new__legend">
          {copy.gym}
        </SectionTitle>
        <Field label={copy.name} error={errorOf('name')}>
          {(props) => (
            <Input {...props} type="text" maxLength={200} value={drafts.name} onChange={(e) => set('name', e.target.value)} />
          )}
        </Field>
        <Field label={copy.slug} hint={slugError ? undefined : slugHint} error={slugError}>
          {(props) => (
            <Input
              {...props}
              type="text"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={63}
              value={drafts.slug}
              onChange={(e) => set('slug', e.target.value.trim().toLowerCase())}
            />
          )}
        </Field>
        <Field label={copy.timezone} error={errorOf('timezone')}>
          {(props) => (
            <Select {...props} value={drafts.timezone} onChange={(e) => set('timezone', e.target.value)}>
              {zones.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={copy.grading} hint={copy.gradingHint} error={errorOf('grading')}>
          {(props) => (
            <Select {...props} value={drafts.grading} onChange={(e) => set('grading', e.target.value)}>
              {choices.grading.map((preset) => (
                <option key={preset.key} value={preset.key}>
                  {preset.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </fieldset>

      <fieldset className={cardClass({}, 'platform-new__card')}>
        <SectionTitle as="legend" className="platform-new__legend">
          {copy.owner}
        </SectionTitle>
        <Field label={copy.ownerEmail} hint={copy.ownerEmailHint} error={errorOf('owner_email')}>
          {(props) => (
            <Input
              {...props}
              type="email"
              autoComplete="off"
              value={drafts.owner_email}
              onChange={(e) => set('owner_email', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.ownerName} error={errorOf('owner_name')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              autoComplete="off"
              value={drafts.owner_name}
              onChange={(e) => set('owner_name', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.ownerRut} error={errorOf('owner_rut')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              autoComplete="off"
              value={drafts.owner_rut}
              onChange={(e) => set('owner_rut', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.ownerPhone} error={errorOf('owner_phone')}>
          {(props) => (
            <Input
              {...props}
              type="tel"
              autoComplete="off"
              value={drafts.owner_phone}
              onChange={(e) => set('owner_phone', e.target.value)}
            />
          )}
        </Field>
      </fieldset>

      <fieldset className={cardClass({}, 'platform-new__card')}>
        <SectionTitle as="legend" className="platform-new__legend">
          {copy.terms}
        </SectionTitle>
        <Field label={copy.termsVersion} error={termsError}>
          {(props) => <Input {...props} type="text" value={choices.terms_version} readOnly />}
        </Field>
        <Field label={copy.signedOn} hint={copy.signedOnHint} error={errorOf('signed_on')}>
          {(props) => (
            <Input {...props} type="date" value={drafts.signed_on} onChange={(e) => set('signed_on', e.target.value)} />
          )}
        </Field>
      </fieldset>

      {save.error && <Banner tone="error">{Object.keys(errors).length > 0 ? copy.invalid : copy.failed}</Banner>}
      <div className="platform-new__actions">
        <Link to={PLATFORM_PATH} className="tap-link">
          {copy.back}
        </Link>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? copy.working : copy.submit}
        </Button>
      </div>
    </form>
  )
}

function Created({ gym, name, email, again }: { gym: CreatedGym; name: string; email: string; again: () => void }) {
  const [copied, setCopied] = useState(false)
  const copyAddress = async () => {
    await navigator.clipboard?.writeText(gym.address)
    setCopied(true)
  }
  return (
    <section className={cardClass({}, 'platform-new__card platform-new__done')} aria-label={copy.created}>
      <p>{copy.createdIntro(name)}</p>
      <p className="platform-new__address">
        <a href={gym.address} target="_blank" rel="noreferrer">
          {gym.address}
        </a>
        <Button onClick={() => void copyAddress()}>{copy.copy}</Button>
      </p>
      {copied && (
        <p className="platform-new__note" role="status">
          {copy.copied}
        </p>
      )}
      <Banner tone="done">{copy.linkSent(email)}</Banner>
      <div className="platform-new__actions">
        <Link to={PLATFORM_PATH} className="tap-link">
          {copy.toList}
        </Link>
        <Button onClick={again}>{copy.another}</Button>
      </div>
    </section>
  )
}
