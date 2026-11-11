import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { gymSettingsQuery } from '../api/gym'
import {
  changeJoinLink,
  generateJoinLink,
  isPrivacyIncomplete,
  joinLinkQuery,
  revokeJoinLink,
  whatsappShareUrl,
  type JoinLink,
  type JoinLinkOptions,
} from '../api/join'
import { programsQuery } from '../api/people'
import { validationErrors } from '../api/validation'
import { Button, buttonClass } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import { Field, LoadFailed, refusal, SectionHead } from './settingsForm'
import { useSubmit } from '../api/submit'

const copy = t.admin.settings.joinLink

type Drafts = { program_id: string; expires_on: string }

function draftsOf(link: JoinLink | null): Drafts {
  return { program_id: link?.program_id ?? '', expires_on: link?.expires_on ?? '' }
}

function optionsOf(drafts: Drafts): JoinLinkOptions {
  return { program_id: drafts.program_id || null, expires_on: drafts.expires_on || null }
}

/**
 * "Inscripción": the gym's join link (#154), which people open to fill in their own
 * details. Generate it, copy it or share it by WhatsApp, change the program it
 * pre-selects and the last day it works, generate another (the old one stops working)
 * or turn it off. What people send waits in "Solicitudes" on Hoy and in Alumnos.
 *
 * The form asks for consent to the gym's privacy notice (#168), so until the privacy
 * details are filled in under Gimnasio the link cannot be generated, and one made
 * before does not work: the section says so and links there.
 */
export function JoinLinkSettings() {
  const link = useQuery(joinLinkQuery)
  const none = link.error instanceof ApiError && link.error.status === 404
  // Here, not in the section, so it outlives the reload after a revoke.
  const [notice, setNotice] = useState<string | null>(null)

  if (link.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (link.isError && !none) {
    return <LoadFailed error={link.error} message={copy.error} retry={() => void link.refetch()} />
  }
  return <JoinLinkSection link={none ? null : (link.data ?? null)} notice={notice} setNotice={setNotice} />
}

function JoinLinkSection({
  link,
  notice,
  setNotice,
}: {
  link: JoinLink | null
  notice: string | null
  setNotice: (notice: string | null) => void
}) {
  const queryClient = useQueryClient()
  const programs = useQuery(programsQuery)
  const gym = useQuery(gymSettingsQuery())
  const [drafts, setDrafts] = useState<Drafts>(draftsOf(link))
  const [confirming, setConfirming] = useState<'regenerate' | 'revoke' | null>(null)
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  const answered = (message: string | null) => async (answer: JoinLink | void) => {
    setConfirming(null)
    setNotice(message)
    setDrafts(draftsOf(answer ?? null))
    if (answer) queryClient.setQueryData(joinLinkQuery.queryKey, answer)
    else await queryClient.invalidateQueries({ queryKey: joinLinkQuery.queryKey })
  }
  const generate = useSubmit({
    mutationFn: () => generateJoinLink(optionsOf(drafts)),
    onSuccess: answered(link ? copy.regenerated : null),
  })
  const change = useSubmit({ mutationFn: () => changeJoinLink(optionsOf(drafts)), onSuccess: answered(copy.saved) })
  const revoke = useSubmit({ mutationFn: revokeJoinLink, onSuccess: answered(copy.revoked) })
  const pending = generate.isPending || change.isPending || revoke.isPending
  const failed = generate.error ?? change.error ?? revoke.error
  const errors = validationErrors(failed)
  // Known unset, or refused for it: a link made meanwhile elsewhere is the API's to refuse.
  const needsPrivacy =
    (gym.isSuccess && gym.data.privacy === null) ||
    isPrivacyIncomplete(failed)
  const error = (field: keyof Drafts) => (field in errors ? refusal(errors[field]!, field, copy, false) : undefined)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setNotice(null)
    if (link) change.mutate()
    else generate.mutate()
  }
  const copyLink = async () => {
    if (!link) return
    await navigator.clipboard?.writeText(link.url)
    setNotice(copy.copied)
  }
  const active = (programs.data ?? []).filter((p) => p.active || p.id === drafts.program_id)

  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead intro={copy.intro} />
      {needsPrivacy && (
        <div className="settings__card settings__plan-text" role="alert">
          <p className="settings__detail">{copy.needsPrivacy}</p>
          <Link to="/admin/ajustes/gimnasio" hash="privacidad" className={buttonClass()}>
            {copy.needsPrivacyLink}
          </Link>
        </div>
      )}
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      {link ? (
        <div className="settings__card settings__plan-text">
          <Field label={copy.linkLabel}>
            {(props) => <Input {...props} type="url" readOnly value={link.url} />}
          </Field>
          {link.expires_on && (
            <p className="settings__detail">
              {link.expired ? copy.expired(t.common.day(link.expires_on)) : copy.validUntil(t.common.day(link.expires_on))}
            </p>
          )}
          <div className="settings__actions">
            <Button onClick={() => void copyLink()}>
              {copy.copy}
            </Button>
            <a
              className={buttonClass({ variant: 'primary' })}
              href={whatsappShareUrl(copy.shareText(gym.data?.name ?? '', link.url))}
              target="_blank"
              rel="noreferrer"
            >
              {copy.share}
            </a>
          </div>
        </div>
      ) : (
        <p className="settings__note">{copy.none}</p>
      )}
      <form className="settings__card settings__form" aria-label={copy.title} onSubmit={submit} noValidate>
        <Field label={copy.program} hint={copy.programHint} error={error('program_id')}>
          {(props) => (
            <Select
              {...props}
              value={drafts.program_id}
              onChange={(e) => set('program_id', e.target.value)}
            >
              <option value="">{copy.anyProgram}</option>
              {active.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={copy.expiresOn} hint={copy.expiresOnHint} error={error('expires_on')}>
          {(props) => (
            <Input
              {...props}
              type="date"
              value={drafts.expires_on}
              onChange={(e) => set('expires_on', e.target.value)}
            />
          )}
        </Field>
        {failed && !needsPrivacy && (
          <p className="settings__error" role="alert">
            {Object.keys(errors).length > 0 ? copy.invalid : copy.failed}
          </p>
        )}
        <div className="settings__actions">
          <Button
            type="submit"
            variant="primary"
            disabled={pending || (needsPrivacy && !link)} busy={pending}
          >
            {pending ? copy.working : link ? copy.save : copy.generate}
          </Button>
        </div>
      </form>
      {link &&
        (confirming ? (
          <div className="settings__card settings__plan-text" role="group" aria-label={copy[confirming]}>
            <p className="settings__detail">
              {confirming === 'regenerate' ? copy.confirmRegenerate : copy.confirmRevoke}
            </p>
            <div className="settings__actions">
              <Button disabled={pending} onClick={() => setConfirming(null)}>
                {copy.cancel}
              </Button>
              <Button
                variant={confirming === 'revoke' ? 'danger' : 'primary'}
                disabled={pending}
                onClick={() => (confirming === 'regenerate' ? generate.mutate() : revoke.mutate())}
              >
                {copy.confirm}
              </Button>
            </div>
          </div>
        ) : (
          <div className="settings__actions">
            <Button
              onClick={() => {
                setNotice(null)
                setConfirming('regenerate')
              }}
            >
              {copy.regenerate}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setNotice(null)
                setConfirming('revoke')
              }}
            >
              {copy.revoke}
            </Button>
          </div>
        ))}
    </section>
  )
}
