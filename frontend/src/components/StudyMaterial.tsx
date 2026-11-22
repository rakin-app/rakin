import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { plansQuery } from '../api/plans'
import {
  AUDIENCES,
  changeMaterial,
  isHttpsLink,
  linkHost,
  linksOf,
  materialQuery,
  MAX_BODY,
  MAX_LINKS,
  MAX_TITLE,
  refreshMaterial,
  removeMaterial,
  shareMaterial,
  type Audience,
  type Material,
  type MaterialHost,
} from '../api/studyMaterial'
import { useSubmit } from '../api/submit'
import { t } from '../i18n/es'
import { Button } from './Button'
import { Banner, Card, CheckRow, PlainList, Section } from './Card'
import { Field, FieldError, Input, Textarea } from './Field'
import { Loading } from './Loading'
import './StudyMaterial.css'

const copy = t.admin.material

/** A material's text, its line breaks kept, and its links as plain links with their host:
 * nothing embedded, nothing fetched (#537). Staff's and the student page's alike. */
export function MaterialContent({ body, links }: { body: string | null; links: string[] }) {
  return (
    <>
      {body && <p className="material__body">{body}</p>}
      {links.length > 0 && (
        <PlainList className="material__links" aria-label={copy.form.links}>
          {links.map((link) => (
            <li key={link}>
              <a href={link} target="_blank" rel="noopener noreferrer" className="material__link">
                <span className="material__host">{linkHost(link)}</span>
                <span className="material__url">{link}</span>
              </a>
            </li>
          ))}
        </PlainList>
      )}
    </>
  )
}

/** Where a class of the schedule may put new material: on itself, or on its recurring
 * class from its date on. */
export type Recurring = { slotDate: string }

/**
 * "Material de estudio" on a class or in Horario: what shows there, newest first, who it
 * is for and who shared it; with `canShare` (its coach, or whoever manages the classes),
 * add, edit and remove. Nothing reaches a member until its audience is chosen.
 */
export function StudyMaterial({
  host,
  canShare,
  recurring,
  today,
}: {
  host: MaterialHost
  canShare: boolean
  // A class of the schedule, which may share on its recurring class too.
  recurring?: Recurring
  // The gym's today, a recurring class's first day by default.
  today: string
}) {
  const list = useQuery(materialQuery(host))
  const titleId = useId()
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }

  let content
  if (list.isPending) content = <Loading className="material__note">{copy.loading}</Loading>
  else if (list.isError) {
    content = (
      <Banner tone="error" as="div">
        <p>{copy.error}</p>
        <Button onClick={() => void list.refetch()}>{copy.retry}</Button>
      </Banner>
    )
  } else if (list.data.length === 0 && editing !== 'new') {
    content = <p className="material__note">{host.kind === 'slot' ? copy.emptySlot : copy.empty}</p>
  } else {
    content = (
      <PlainList className="material__list">
        {list.data.map((material) =>
          editing === material.id ? (
            <li key={material.id}>
              <MaterialForm
                host={host}
                material={material}
                today={today}
                onDone={() => done(copy.saved)}
                onCancel={() => setEditing(null)}
              />
            </li>
          ) : (
            <MaterialRow
              key={material.id}
              material={material}
              canShare={canShare}
              onEdit={() => {
                setNotice(null)
                setEditing(material.id)
              }}
              onRemoved={() => done(copy.removed)}
            />
          ),
        )}
      </PlainList>
    )
  }

  return (
    <Section id={titleId} title={copy.title} className="material">
      {canShare && <p className="material__note">{copy.intro}</p>}
      {notice && <Banner tone="done">{notice}</Banner>}
      {content}
      {canShare &&
        (editing === 'new' ? (
          <MaterialForm
            host={host}
            recurring={recurring}
            today={today}
            onDone={() => done(copy.shared)}
            onCancel={() => setEditing(null)}
          />
        ) : (
          <Button
            className="material__add"
            onClick={() => {
              setNotice(null)
              setEditing('new')
            }}
          >
            {copy.add}
          </Button>
        ))}
    </Section>
  )
}

function audienceLine(material: Material): string {
  const who =
    material.audience === 'plans' && material.plans.length > 0
      ? `${copy.audience.plans} (${material.plans.map((plan) => plan.name).join(', ')})`
      : copy.audience[material.audience]
  return copy.shownTo(who)
}

function MaterialRow({
  material,
  canShare,
  onEdit,
  onRemoved,
}: {
  material: Material
  canShare: boolean
  onEdit: () => void
  onRemoved: () => void
}) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const remove = useSubmit({
    mutationFn: () => removeMaterial(material.id),
    onSuccess: () => {
      refreshMaterial(queryClient)
      onRemoved()
    },
  })
  const words = copy.removeConfirm
  return (
    <Card as="li" className="material__row">
      <span className="material__title">{material.title}</span>
      <span className="material__detail">{audienceLine(material)}</span>
      {material.starts_on && (
        <span className="material__detail">{copy.recurring(t.common.shortDay(material.starts_on))}</span>
      )}
      {material.shared_by_name && <span className="material__detail">{copy.sharedBy(material.shared_by_name)}</span>}
      <MaterialContent body={material.body} links={material.links} />
      {canShare && !confirming && (
        <div className="material__actions">
          <Button variant="ghost" onClick={onEdit}>
            {copy.edit}
          </Button>
          <Button variant="ghost" onClick={() => setConfirming(true)}>
            {copy.remove}
          </Button>
        </div>
      )}
      {confirming && (
        <Banner tone="warning" as="div" role="alert">
          <p>
            <strong>{words.question(material.title)}</strong> {words.note}
          </p>
          {remove.isError && <p>{words.failed}</p>}
          <div className="material__actions">
            <Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending} busy={remove.isPending}>
              {remove.isPending ? words.working : words.confirm}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)} disabled={remove.isPending}>
              {copy.cancel}
            </Button>
          </div>
        </Banner>
      )}
    </Card>
  )
}

function MaterialForm({
  host,
  material,
  recurring,
  today,
  onDone,
  onCancel,
}: {
  host: MaterialHost
  // The one being edited; none for new material.
  material?: Material
  recurring?: Recurring
  today: string
  onDone: () => void
  onCancel: () => void
}) {
  const words = copy.form
  const queryClient = useQueryClient()
  const plans = useQuery(plansQuery)
  const audienceName = useId()
  const whereName = useId()
  const [title, setTitle] = useState(material?.title ?? '')
  const [body, setBody] = useState(material?.body ?? '')
  const [linkText, setLinkText] = useState((material?.links ?? []).join('\n'))
  const [audience, setAudience] = useState<Audience | null>(material?.audience ?? null)
  const [planIds, setPlanIds] = useState<string[]>(material?.plans.map((plan) => plan.id) ?? [])
  // New material on a class of the schedule: this class alone, or its recurring class too.
  const [everyClass, setEveryClass] = useState(false)
  const firstDay = material?.starts_on ?? (host.kind === 'slot' ? today : (recurring?.slotDate ?? today))
  const [from, setFrom] = useState(firstDay)
  const [tried, setTried] = useState(false)

  const links = linksOf(linkText)
  const badLinks = links.filter((link) => !isHttpsLink(link)).length
  const linkError =
    badLinks > 0 ? words.badLinks(badLinks) : links.length > MAX_LINKS ? words.tooManyLinks(MAX_LINKS) : null
  const plansError = audience === 'plans' && planIds.length === 0 ? words.noPlans : null
  const dated = material ? material.starts_on !== null : host.kind === 'slot' || everyClass
  // Plans to pick from: the active ones, and any it already names.
  const pickable = (plans.data ?? []).filter((plan) => plan.active || planIds.includes(plan.id))

  const save = useSubmit({
    mutationFn: () => {
      const fields = {
        title: title.trim(),
        body: body.trim() === '' ? null : body,
        links,
        audience: audience!,
        plan_ids: audience === 'plans' ? planIds : [],
      }
      if (material) return changeMaterial(material.id, dated ? { ...fields, starts_on: from } : fields)
      if (host.kind === 'slot') return shareMaterial(host, { ...fields, starts_on: from })
      return shareMaterial(host, everyClass ? { ...fields, recurring: true, starts_on: from } : fields)
    },
    onSuccess: () => {
      refreshMaterial(queryClient)
      onDone()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setTried(true)
    if (title.trim() === '' || audience === null || linkError || plansError || (dated && from === '')) return
    save.mutate()
  }
  const togglePlan = (id: string) =>
    setPlanIds((ids) => (ids.includes(id) ? ids.filter((other) => other !== id) : [...ids, id]))

  return (
    <form className="material__form" aria-label={material ? words.editTitle : words.newTitle} onSubmit={submit} noValidate>
      <Field label={words.title} error={tried && title.trim() === '' ? words.titleMissing : undefined}>
        {(props) => (
          <Input
            {...props}
            value={title}
            maxLength={MAX_TITLE}
            placeholder={words.titlePlaceholder}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        )}
      </Field>
      <Field label={words.body} hint={words.bodyHint}>
        {(props) => (
          <Textarea {...props} value={body} maxLength={MAX_BODY} rows={4} onChange={(e) => setBody(e.target.value)} />
        )}
      </Field>
      <Field label={words.links} hint={words.linksHint} error={linkError ?? undefined}>
        {(props) => (
          <Textarea
            {...props}
            value={linkText}
            rows={3}
            inputMode="url"
            autoCapitalize="off"
            spellCheck={false}
            placeholder={words.linksPlaceholder}
            onChange={(e) => setLinkText(e.target.value)}
          />
        )}
      </Field>
      <fieldset className="material__fieldset">
        <legend className="field__label">{words.audience}</legend>
        {AUDIENCES.map((option) => (
          <CheckRow key={option} start>
            <input
              type="radio"
              name={audienceName}
              value={option}
              checked={audience === option}
              onChange={() => setAudience(option)}
            />
            <span className="material__choice">
              <span>{copy.audience[option]}</span>
              <span className="material__detail">{copy.audienceHint[option]}</span>
            </span>
          </CheckRow>
        ))}
        {tried && audience === null && <FieldError>{words.audienceMissing}</FieldError>}
      </fieldset>
      {audience === 'plans' && (
        <fieldset className="material__fieldset">
          <legend className="field__label">{words.plans}</legend>
          {pickable.map((plan) => (
            <CheckRow key={plan.id}>
              <input type="checkbox" checked={planIds.includes(plan.id)} onChange={() => togglePlan(plan.id)} />
              <span>{plan.name}</span>
            </CheckRow>
          ))}
          {tried && plansError && <FieldError>{plansError}</FieldError>}
        </fieldset>
      )}
      {!material && host.kind === 'session' && recurring && (
        <fieldset className="material__fieldset">
          <legend className="field__label">{words.where}</legend>
          <CheckRow>
            <input type="radio" name={whereName} checked={!everyClass} onChange={() => setEveryClass(false)} />
            <span>{words.thisClass}</span>
          </CheckRow>
          <CheckRow>
            <input type="radio" name={whereName} checked={everyClass} onChange={() => setEveryClass(true)} />
            <span>{words.everyClass}</span>
          </CheckRow>
        </fieldset>
      )}
      {dated && (
        <Field label={words.from}>
          {(props) => <Input {...props} type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />}
        </Field>
      )}
      {save.isError && <Banner tone="error">{words.failed}</Banner>}
      <div className="material__actions">
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? words.working : material ? words.save : words.submit}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={save.isPending}>
          {copy.cancel}
        </Button>
      </div>
    </form>
  )
}
