import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useId, useRef, useState, type FormEvent } from 'react'
import {
  editGym,
  isHandover,
  needsReauth,
  PLATFORM_PATH,
  platformGymQuery,
  platformGymsQuery,
  recordTerms,
  renameCheckQuery,
  renameGym,
  type GymEdit,
  type PlatformGymDetail,
} from '../api/platform'
import { useSubmit } from '../api/submit'
import { validationErrors } from '../api/validation'
import { BackLink } from '../components/BackLink'
import { Button } from '../components/Button'
import { Banner, cardClass, PlainList, Section } from '../components/Card'
import { Input } from '../components/Field'
import { useFocusFirstInvalid } from '../components/focusInvalid'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { PlatformReauth } from '../components/PlatformReauth'
import { StatusPill } from '../components/StatusPill'
import { shortDate } from '../format'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import { SLUG_CHECK_DELAY_MS, useSettled } from './PlatformNewGym'
import { Field, LoadFailed, refusal } from './settingsForm'
import './PlatformGym.css'

const copy = t.platform.gym
const route = getRouteApi('/plataforma/$gymId')
const REFUSALS = { range: {}, value: copy.refusals as Record<string, string> }

/**
 * A gym's edit screen (#438), opened from the list: its name and its titular's contact,
 * a new signature of the Términos de encargo, and its address. The titular is never
 * changed here, and their email only before their first sign-in: after it, that is the
 * handover (#321). A new address asks the operator to confirm by typing it, and, if
 * they have not proved who they are in the last 10 minutes, for a code.
 */
export function PlatformGym() {
  const { gymId } = route.useParams()
  const gym = useQuery(platformGymQuery(gymId))
  useDocumentTitle(gym.data?.name ?? copy.tab, t.platform.tab)
  return (
    <>
      <PageHeader
        back={<BackLink to={PLATFORM_PATH} label={copy.back} />}
        eyebrow={gym.data && new URL(gym.data.address).host}
        title={gym.data?.name ?? copy.tab}
      />
      {gym.isPending ? (
        <Loading className="platform-gym__note" role="status">
          {copy.loading}
        </Loading>
      ) : gym.isError ? (
        <LoadFailed error={gym.error} message={copy.failed} retry={() => void gym.refetch()} />
      ) : (
        <div className="platform-gym">
          {/* Keyed by what they edit, so a change saved elsewhere resets their drafts. */}
          <Contact key={`${gym.data.name}|${gym.data.titular_name}|${gym.data.titular_phone}|${gym.data.titular_email}`} gym={gym.data} />
          <Terms gym={gym.data} />
          <Address key={gym.data.slug} gym={gym.data} />
        </div>
      )}
    </>
  )
}

/** Drops the gym and the list from the cache: both show what changed. */
function useRefresh(gymId: string) {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: platformGymQuery(gymId).queryKey }),
      queryClient.invalidateQueries({ queryKey: platformGymsQuery().queryKey, exact: true }),
    ])
}

type ContactDrafts = { name: string; owner_name: string; owner_phone: string; owner_email: string }

function Contact({ gym }: { gym: PlatformGymDetail }) {
  const refresh = useRefresh(gym.id)
  const first: ContactDrafts = {
    name: gym.name,
    owner_name: gym.titular_name ?? '',
    owner_phone: gym.titular_phone ?? '',
    owner_email: gym.titular_email ?? '',
  }
  const [drafts, setDrafts] = useState(first)
  const set = (field: keyof ContactDrafts, value: string) => setDrafts({ ...drafts, [field]: value })
  const save = useSubmit({
    offline: 'refuse',
    mutationFn: (edit: GymEdit) => editGym(gym.id, edit),
    onSuccess: () => refresh(),
  })
  const errors = validationErrors(save.error)
  const formRef = useRef<HTMLFormElement>(null)
  useFocusFirstInvalid(formRef, save.error)
  const errorOf = (field: keyof ContactDrafts) =>
    field in errors ? refusal(errors[field]!, field, REFUSALS, drafts[field].trim() === '') : undefined
  const hasTitular = gym.titular_name !== null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // Only what changed: the rest is left out, and stays.
    const edit: GymEdit = {}
    for (const field of Object.keys(drafts) as (keyof ContactDrafts)[]) {
      const value = drafts[field].trim()
      if (value !== first[field]) edit[field] = value
    }
    save.mutate(edit)
  }

  return (
    <Section id={useId()} title={copy.contact}>
      <form ref={formRef} className={cardClass({}, 'platform-gym__card')} onSubmit={submit} noValidate>
        <Field label={copy.name} error={errorOf('name')}>
          {(props) => (
            <Input {...props} type="text" maxLength={200} value={drafts.name} onChange={(e) => set('name', e.target.value)} />
          )}
        </Field>
        {hasTitular && (
          <>
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
            <Field
              label={copy.ownerEmail}
              hint={gym.titular_signed_in ? copy.ownerEmailLocked : copy.ownerEmailHint}
              error={errorOf('owner_email')}
            >
              {(props) => (
                <Input
                  {...props}
                  type="email"
                  autoComplete="off"
                  readOnly={gym.titular_signed_in}
                  value={drafts.owner_email}
                  onChange={(e) => set('owner_email', e.target.value)}
                />
              )}
            </Field>
          </>
        )}
        <p className="platform-gym__note">{copy.titularNote}</p>
        {save.isError ? (
          <Banner tone="error">
            {isHandover(save.error) ? copy.handover : Object.keys(errors).length > 0 ? copy.invalid : copy.saveFailed}
          </Banner>
        ) : (
          save.isSuccess && (
            <Banner tone="done">{save.data.fields.length > 0 ? copy.saved : copy.unchanged}</Banner>
          )
        )}
        <div className="platform-gym__actions">
          <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
            {save.isPending ? copy.saving : copy.save}
          </Button>
        </div>
      </form>
    </Section>
  )
}

function Terms({ gym }: { gym: PlatformGymDetail }) {
  const refresh = useRefresh(gym.id)
  const [signedOn, setSignedOn] = useState('')
  const record = useSubmit({
    offline: 'refuse',
    mutationFn: (date: string) => recordTerms(gym.id, date),
    onSuccess: () => refresh(),
  })
  const errors = validationErrors(record.error)
  const error = 'signed_on' in errors ? refusal(errors.signed_on!, 'signed_on', REFUSALS, signedOn === '') : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    record.mutate(signedOn)
  }

  return (
    <Section id={useId()} title={copy.terms}>
      <div className={cardClass({}, 'platform-gym__card')}>
        {gym.terms.length === 0 ? (
          <p className="platform-gym__note">{copy.noTerms}</p>
        ) : (
          <PlainList className="platform-gym__list">
            {gym.terms.map((signature) => (
              <li key={signature.version}>
                {copy.signature(signature.version, shortDate(signature.signed_on))}{' '}
                {signature.version === gym.terms_version && <StatusPill status="done">{copy.current}</StatusPill>}
              </li>
            ))}
          </PlainList>
        )}
        <form className="platform-gym__inline" onSubmit={submit} noValidate>
          <Field label={copy.signedOn} hint={copy.recordVersion(gym.terms_version)} error={error}>
            {(props) => <Input {...props} type="date" value={signedOn} onChange={(e) => setSignedOn(e.target.value)} />}
          </Field>
          <Button type="submit" disabled={record.isPending} busy={record.isPending}>
            {record.isPending ? copy.recording : copy.record}
          </Button>
        </form>
        {record.isError && error === undefined && <Banner tone="error">{copy.recordFailed}</Banner>}
        {record.isSuccess && (
          <Banner tone="done">{record.data.recorded ? copy.recorded : copy.alreadySigned}</Banner>
        )}
      </div>
    </Section>
  )
}

function Address({ gym }: { gym: PlatformGymDetail }) {
  const refresh = useRefresh(gym.id)
  const [slug, setSlug] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [typed, setTyped] = useState('')
  const [reauthing, setReauthing] = useState(false)
  const confirmId = useId()

  const settled = useSettled(slug, SLUG_CHECK_DELAY_MS)
  const check = useQuery({ ...renameCheckQuery(gym.id, settled), enabled: settled !== '' && settled !== gym.slug })
  const checked = settled === slug && check.data ? check.data : null

  const rename = useSubmit({
    offline: 'refuse',
    mutationFn: (to: string) => renameGym(gym.id, to),
    onError: (error) => {
      if (needsReauth(error)) setReauthing(true)
    },
    onSuccess: () => {
      setConfirming(false)
      setTyped('')
      return refresh()
    },
  })
  const errors = validationErrors(rename.error)
  const refused = 'slug' in errors ? refusal(errors.slug!, 'slug', REFUSALS, false) : undefined
  const slugError = refused ?? (checked?.problem && slug !== '' ? copy.problems[checked.problem] : undefined)
  const slugHint = slug === '' ? copy.newSlugHint : checked && !checked.problem ? copy.willBe(checked.address) : copy.checking
  const ready = slug !== '' && slug !== gym.slug && checked !== null && checked.problem === null

  const open = (event: FormEvent) => {
    event.preventDefault()
    rename.reset()
    if (ready) setConfirming(true)
  }
  const close = () => {
    setConfirming(false)
    setReauthing(false)
    setTyped('')
    rename.reset()
  }
  const go = (event: FormEvent) => {
    event.preventDefault()
    if (typed === slug) rename.mutate(slug)
  }

  const oldHost = new URL(gym.address).host
  const newHost = checked ? new URL(checked.address).host : slug

  return (
    <Section id={useId()} title={copy.address}>
      <div className={cardClass({}, 'platform-gym__card')}>
        <p className="platform-gym__address">
          <span className="field__label">{copy.currentAddress}</span>{' '}
          <a href={gym.address} target="_blank" rel="noreferrer">
            {oldHost}
          </a>
        </p>
        {gym.aliases.map((alias) => (
          <p key={alias.slug} className="platform-gym__note">
            {copy.redirects(new URL(alias.address).host, shortDate(alias.until))}
          </p>
        ))}
        {rename.isSuccess && rename.data.until !== null && (
          <Banner tone="done">{copy.renamed(new URL(rename.data.address).host)}</Banner>
        )}
        <form className="platform-gym__inline" onSubmit={open} noValidate>
          <Field label={copy.newSlug} hint={slugError ? undefined : slugHint} error={slugError}>
            {(props) => (
              <Input
                {...props}
                type="text"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={63}
                value={slug}
                readOnly={confirming}
                onChange={(e) => setSlug(e.target.value.trim().toLowerCase())}
              />
            )}
          </Field>
          {!confirming && (
            <Button type="submit" disabled={!ready}>
              {copy.rename}
            </Button>
          )}
        </form>
        {confirming && (
          <section role="dialog" aria-labelledby={confirmId} className="platform-gym__confirm">
            <h3 id={confirmId} className="section-header__title">
              {copy.confirmTitle}
            </h3>
            <p>{copy.confirmMove(oldHost, newHost)}</p>
            <p>{copy.confirmRedirect(oldHost)}</p>
            <p>{copy.confirmSessions}</p>
            {reauthing ? (
              <PlatformReauth
                onFresh={() => {
                  setReauthing(false)
                  rename.mutate(slug)
                }}
                onCancel={close}
              />
            ) : (
              <form className="platform-gym__inline" onSubmit={go} noValidate>
                <Field label={copy.confirmType}>
                  {(props) => (
                    <Input
                      {...props}
                      type="text"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      value={typed}
                      onChange={(e) => setTyped(e.target.value.trim().toLowerCase())}
                    />
                  )}
                </Field>
                {rename.isError && !needsReauth(rename.error) && refused === undefined && (
                  <Banner tone="error">{copy.renameFailed}</Banner>
                )}
                <div className="platform-gym__actions">
                  <Button onClick={close}>{copy.cancel}</Button>
                  <Button
                    type="submit"
                    variant="danger"
                    disabled={typed !== slug || rename.isPending}
                    busy={rename.isPending}
                  >
                    {rename.isPending ? copy.renaming : copy.confirm}
                  </Button>
                </div>
              </form>
            )}
          </section>
        )}
      </div>
    </Section>
  )
}
