import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { VISIBLE_TO, type VisibleTo } from '../api/customFields'
import { holdsAccount, myAccessQuery } from '../api/me'
import {
  createRequirement,
  reorderRequirements,
  requirementsQuery,
  updateRequirement,
  type Requirement,
  type RequirementChanges,
} from '../api/requirements'
import { useSubmit } from '../api/submit'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Banner, Card, cardClass, CheckRow, PlainList, SectionTitle } from '../components/Card'
import { Input, Select } from '../components/Field'
import { Loading } from '../components/Loading'
import { t } from '../i18n/es'
import { EditRow, Field, LoadFailed, MoveButtons, refusal, SectionHead } from './settingsForm'

const copy = t.admin.settings.requirements
const form = copy.form

/** The list changed: it, and every member's ficha, which shows the active ones. */
async function refresh(queryClient: QueryClient) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: requirementsQuery.queryKey }),
    queryClient.invalidateQueries({ queryKey: ['people', 'requirements'] }),
  ])
}

function summary(requirement: Requirement, owner: boolean): string {
  const lasts = requirement.valid_months === null ? copy.once : copy.months(requirement.valid_months)
  // Who sees it is the owner's to set, and theirs to read.
  return owner ? copy.row(lasts, copy.visibleTo[requirement.visible_to]) : lasts
}

/**
 * "Requisitos" (#349): what the gym asks before someone trains, a waiver, an induction,
 * a medical certificate, in the order the ficha shows them, and the forms that add,
 * reorder and deactivate them. There is no delete: a deactivated requirement keeps its
 * records but is not shown. As in Campos, only the owner sees and sets whether one is
 * sensitive and who sees it.
 */
export function RequirementSettings() {
  const queryClient = useQueryClient()
  const requirements = useQuery(requirementsQuery)
  const owner = holdsAccount(useQuery(myAccessQuery()).data)
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reorder = useSubmit({
    mutationFn: reorderRequirements,
    onSuccess: async (answer) => {
      queryClient.setQueryData(requirementsQuery.queryKey, answer)
      await queryClient.invalidateQueries({ queryKey: ['people', 'requirements'] })
    },
    // Most likely someone added one meanwhile: show the list as it is.
    onError: () => refresh(queryClient),
  })

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (id: string | 'new') => {
    setNotice(null)
    setEditing(id)
  }

  if (requirements.isPending) return <Loading className="settings__note">{t.admin.settings.loading}</Loading>
  if (requirements.isError) {
    return <LoadFailed error={requirements.error} message={copy.error} retry={() => void requirements.refetch()} />
  }

  const list = requirements.data
  const move = (index: number, by: -1 | 1) => {
    const ids = list.map((r) => r.id)
    ;[ids[index], ids[index + by]] = [ids[index + by]!, ids[index]!]
    setNotice(null)
    reorder.mutate(ids)
  }

  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead
        intro={copy.intro}
        action={
          editing !== 'new' && (
            <Button variant="primary" onClick={() => open('new')}>
              {copy.add}
            </Button>
          )
        }
      />
      {notice && <Banner tone="done">{notice}</Banner>}
      {editing === 'new' && <RequirementForm owner={owner} onCancel={() => setEditing(null)} onDone={done} />}
      {reorder.isError && <Banner tone="error">{copy.reorderFailed}</Banner>}
      {list.length === 0 ? (
        <div className="settings__note">
          <p>{copy.empty}</p>
          <PlainList>
            {copy.examples.map((example) => (
              <li key={example}>{example}</li>
            ))}
          </PlainList>
        </div>
      ) : (
        <Card as="ul" flush className="settings__card settings__card--rows settings__menu">
          {list.map((requirement, index) =>
            editing === requirement.id ? (
              <li key={requirement.id}>
                <RequirementForm
                  requirement={requirement}
                  owner={owner}
                  onCancel={() => setEditing(null)}
                  onDone={done}
                />
              </li>
            ) : (
              <EditRow
                key={requirement.id}
                inactive={!requirement.active}
                title={
                  <>
                    {requirement.name}
                    {requirement.sensitive && <span className="settings__tag">{copy.sensitive}</span>}
                    {!requirement.active && <span className="settings__tag">{copy.archived}</span>}
                  </>
                }
                detail={summary(requirement, owner)}
                onOpen={() => open(requirement.id)}
                controls={
                  <MoveButtons
                    up={copy.up(requirement.name)}
                    down={copy.down(requirement.name)}
                    first={index === 0}
                    last={index === list.length - 1}
                    disabled={reorder.isPending}
                    onMove={(by) => move(index, by)}
                  />
                }
              />
            ),
          )}
        </Card>
      )}
    </section>
  )
}

type Drafts = { name: string; validMonths: string; sensitive: boolean; visible_to: VisibleTo }

function draftsOf(requirement: Requirement | undefined): Drafts {
  return {
    name: requirement?.name ?? '',
    validMonths: requirement?.valid_months == null ? '' : String(requirement.valid_months),
    sensitive: requirement?.sensitive ?? false,
    visible_to: requirement?.visible_to ?? 'staff',
  }
}

/** The months as typed: blank is one done once; anything else is sent for the API to judge. */
function monthsOf(draft: string): number | null {
  return draft.trim() === '' ? null : Number(draft)
}

function RequirementForm({
  requirement,
  owner,
  onCancel,
  onDone,
}: {
  requirement?: Requirement
  owner: boolean
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const toggle = useSubmit({
    mutationFn: () => updateRequirement(requirement!.id, { active: !requirement!.active }),
    onSuccess: async (answer) => {
      onDone(answer.active ? copy.restored(answer.name) : copy.archivedDone(answer.name))
      await refresh(queryClient)
    },
  })
  const [initial] = useState(() => draftsOf(requirement))
  const [drafts, setDrafts] = useState(initial)

  // An edit sends only what changed; an admin never sends what is the owner's to set.
  const changes = (): RequirementChanges => {
    const out: RequirementChanges = {}
    if (drafts.name.trim() !== initial.name.trim()) out.name = drafts.name.trim()
    if (monthsOf(drafts.validMonths) !== monthsOf(initial.validMonths)) out.valid_months = monthsOf(drafts.validMonths)
    if (owner && drafts.sensitive !== initial.sensitive) out.sensitive = drafts.sensitive
    if (owner && drafts.visible_to !== initial.visible_to) out.visible_to = drafts.visible_to
    return out
  }

  const save = useSubmit({
    mutationFn: () =>
      requirement
        ? updateRequirement(requirement.id, changes())
        : createRequirement({
            name: drafts.name,
            valid_months: monthsOf(drafts.validMonths),
            ...(owner && { sensitive: drafts.sensitive, visible_to: drafts.visible_to }),
          }),
    onSuccess: async (answer) => {
      onDone(requirement ? copy.saved(answer.name) : copy.created(answer.name))
      await refresh(queryClient)
    },
  })
  const errors = validationErrors(save.error)
  const nameError = 'name' in errors ? refusal(errors['name']!, 'name', form, drafts.name.trim() === '') : undefined
  const monthsError = 'valid_months' in errors ? refusal(errors['valid_months']!, 'valid_months', form, false) : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // An edit that changed nothing has nothing to send: the form just closes.
    if (requirement && Object.keys(changes()).length === 0) {
      onCancel()
      return
    }
    save.mutate()
  }

  const title = requirement ? form.edit(requirement.name) : form.create
  return (
    <form className={cardClass({}, 'settings__card settings__form')} aria-label={title} onSubmit={submit} noValidate>
      <SectionTitle className="settings__legend">{title}</SectionTitle>
      <Field label={form.name} error={nameError}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={80}
            value={drafts.name}
            onChange={(e) => setDrafts({ ...drafts, name: e.target.value })}
          />
        )}
      </Field>
      <Field label={form.validMonths} hint={form.validMonthsHint} error={monthsError}>
        {(props) => (
          <Input
            {...props}
            type="number"
            inputMode="numeric"
            min={1}
            max={120}
            value={drafts.validMonths}
            onChange={(e) => setDrafts({ ...drafts, validMonths: e.target.value })}
          />
        )}
      </Field>
      {owner && (
        <>
          <div className="settings__field">
            <CheckRow>
              <input
                type="checkbox"
                checked={drafts.sensitive}
                onChange={(e) =>
                  setDrafts({
                    ...drafts,
                    sensitive: e.target.checked,
                    // As the API does: one marked sensitive is narrowed to the owner unless told otherwise.
                    visible_to: e.target.checked && !drafts.sensitive ? 'owner' : drafts.visible_to,
                  })
                }
              />
              {form.sensitive}
            </CheckRow>
            <p className="settings__hint">{form.sensitiveHint}</p>
          </div>
          <Field label={form.visibleTo}>
            {(props) => (
              <Select
                {...props}
                value={drafts.visible_to}
                onChange={(e) => setDrafts({ ...drafts, visible_to: e.target.value as VisibleTo })}
              >
                {VISIBLE_TO.map((v) => (
                  <option key={v} value={v}>
                    {copy.visibleTo[v]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </>
      )}

      {save.error && (
        <Banner tone="error">{Object.keys(errors).length > 0 ? form.invalid : form.failed}</Banner>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
      {requirement && (
        <div className="settings__danger">
          {toggle.isError && <Banner tone="error">{copy.toggleFailed}</Banner>}
          <Button
            variant={requirement.active ? 'danger' : 'secondary'}
            disabled={save.isPending || toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {requirement.active ? copy.archive : copy.restore}
          </Button>
        </div>
      )}
    </form>
  )
}
