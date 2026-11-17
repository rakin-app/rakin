import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { holds, myAccessQuery, type Access, type Permission } from '../api/me'
import { duplicateOf } from '../api/people'
import {
  addPreset,
  appoint,
  archiveTitle,
  changeTitle,
  chooseSetup,
  correctAppointment,
  createTitle,
  endAppointment,
  IMPLIES,
  inviteStaff,
  PERMISSIONS,
  staffHistoryQuery,
  staffQuery,
  titlesQuery,
  withImplied,
  type PresetKey,
  type StaffAppointment,
  type StaffMember,
  type Title,
} from '../api/staff'
import { useSubmit } from '../api/submit'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import {
  Banner,
  Card,
  cardClass,
  CheckRow,
  ListRow,
  listRowClass,
  ListRowContent,
  PlainList,
  Section,
  SectionTitle,
} from '../components/Card'
import { ChevronRightIcon } from '../components/icons'
import { Input, Select } from '../components/Field'
import { Loading } from '../components/Loading'
import { formatPhone, isoDay, monthYear, shortDate } from '../format'
import { t } from '../i18n/es'
import { Field, LoadFailed, refusal, SectionHead } from './settingsForm'
import './StaffSettings.css'

const copy = t.admin.settings.staff
const PRESET_KEYS: readonly PresetKey[] = ['academia', 'club_federado']

/** Today, as the browser sees it: what "Desde" starts on. */
function today(): string {
  return isoDay(new Date().toISOString())
}

function statusOf(error: unknown): number | undefined {
  return error instanceof ApiError ? error.status : undefined
}

/** The permissions in words, in Ajustes' order, leaving out what another one says:
 * "Registrar pagos" is seeing them too. */
function inWords(permissions: readonly Permission[]): string[] {
  const held = new Set(permissions)
  return PERMISSIONS.filter((p) => held.has(p) && !PERMISSIONS.some((q) => held.has(q) && IMPLIES[q] === p)).map(
    (p) => copy.permissions[p]!,
  )
}

/** `a, b y c`. */
function joined(items: readonly string[]): string {
  return items.length > 1 ? `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}` : (items[0] ?? '')
}

/**
 * "Equipo": who is on the team and what they may do (#311,
 * docs/design/expenses-and-officers.md, section 8). A new gym first chooses how its team
 * is organised; then Personas, each with their roles and terms, opening in place for
 * whoever may change them; Cargos, the gym's roles and their permissions; and Historial,
 * every appointment as it was. What a row offers is what the API says the signed-in
 * person may do, by the strictly-fewer rule: the titular manages everyone but themselves.
 */
export function StaffSettings() {
  const staff = useQuery(staffQuery)
  const titles = useQuery(titlesQuery)
  const access = useQuery(myAccessQuery())
  const [inviting, setInviting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setInviting(false)
    setNotice(message)
  }

  if (staff.isPending || titles.isPending) return <Loading className="settings__note">{t.admin.settings.loading}</Loading>
  if (staff.isError) return <LoadFailed error={staff.error} message={copy.error} retry={() => void staff.refetch()} />
  if (titles.isError) return <LoadFailed error={titles.error} message={copy.error} retry={() => void titles.refetch()} />

  const live = titles.data.titles
  return (
    <section className="settings__section team" aria-label={copy.title}>
      <SectionHead
        intro={copy.intro}
        action={
          !inviting && (
            <Button
              variant="primary"
              onClick={() => {
                setNotice(null)
                setInviting(true)
              }}
            >
              {copy.add}
            </Button>
          )
        }
      />
      {notice && <Banner tone="done">{notice}</Banner>}
      {titles.data.setup_pending && <SetupCard onDone={done} />}
      {inviting && <InviteForm titles={live} onCancel={() => setInviting(false)} onDone={done} />}
      <People staff={staff.data} titles={live} onDone={done} />
      <Cargos titles={live} acting={access.data} onDone={done} />
      <History />
    </section>
  )
}

function useRefresh() {
  const queryClient = useQueryClient()
  // Every Equipo answer starts with `staff`: the list, its roles and its history.
  return () => queryClient.invalidateQueries({ queryKey: ['staff'] })
}

// --- first-run setup -------------------------------------------------------------------

/** A new gym's first choice of how its team is organised: a preset, or none. */
function SetupCard({ onDone }: { onDone: (message: string) => void }) {
  const refresh = useRefresh()
  const choose = useSubmit({
    mutationFn: (preset: PresetKey | null) => chooseSetup(preset),
    onSuccess: async () => {
      onDone(copy.setup.chosen)
      await refresh()
    },
  })
  return (
    <Section title={copy.setup.title} id="team-setup">
      <Card className="settings__card settings__form">
        <p className="settings__detail">{copy.setup.intro}</p>
        <PlainList className="team__choices">
          {PRESET_KEYS.map((preset) => (
            <li key={preset} className="team__choice">
              <span>
                <strong>{copy.presets[preset]}</strong>
                <span className="settings__detail">{copy.presetRoles[preset]}</span>
              </span>
              <Button disabled={choose.isPending} onClick={() => choose.mutate(preset)}>
                {copy.setup.choose(copy.presets[preset]!)}
              </Button>
            </li>
          ))}
          <li className="team__choice">
            <span>
              <strong>{copy.setup.none}</strong>
              <span className="settings__detail">{copy.setup.noneHint}</span>
            </span>
            <Button disabled={choose.isPending} onClick={() => choose.mutate(null)}>
              {copy.setup.none}
            </Button>
          </li>
        </PlainList>
        {choose.isError && <Banner tone="error">{copy.actionFailed}</Banner>}
      </Card>
    </Section>
  )
}

// --- Personas --------------------------------------------------------------------------

/** From the first current role's start to the last one's end: `mar 2025 – mar 2026`. */
function termOf(member: StaffMember): { short: string; wide: string } {
  if (member.account_holder || member.appointments.length === 0) return { short: '', wide: '—' }
  const day = today()
  const current = member.appointments.filter((a) => a.starts_on <= day)
  if (current.length === 0) {
    const first = member.appointments[0]!.starts_on
    return { short: copy.people.from(shortDate(first)), wide: copy.people.from(shortDate(first)) }
  }
  const from = monthYear(current.map((a) => a.starts_on).sort()[0]!)
  const ends = current.map((a) => a.ends_on)
  const until = ends.includes(null) ? null : ends.sort().reverse()[0]!
  return {
    short: until ? copy.people.until(monthYear(until)) : '',
    wide: `${from} – ${until ? monthYear(until) : copy.people.open}`,
  }
}

function People({
  staff,
  titles,
  onDone,
}: {
  staff: StaffMember[]
  titles: Title[]
  onDone: (message: string) => void
}) {
  // The one person open to act on (#177).
  const [opened, setOpened] = useState<string | null>(null)
  return (
    <Section title={copy.people.title} id="team-people">
      <div className="team__people-head team__wide" aria-hidden="true">
        <span>{copy.people.name}</span>
        <span>{copy.people.roles}</span>
        <span>{copy.people.term}</span>
        <span>{copy.people.can}</span>
      </div>
      <Card as="ul" flush className="settings__card settings__card--rows settings__menu team__people">
        {staff.map((member) =>
          opened === member.person_id ? (
            <li key={member.person_id} aria-label={member.name}>
              <PersonPanel
                member={member}
                titles={titles}
                onClose={() => setOpened(null)}
                onDone={(message) => {
                  setOpened(null)
                  onDone(message)
                }}
              />
            </li>
          ) : (
            <PersonRow key={member.person_id} member={member} onOpen={() => setOpened(member.person_id)} />
          ),
        )}
      </Card>
    </Section>
  )
}

/** A person: their roles and term and, from 1024px, what they may do. Opens only for
 * whoever may change them; the titular's row never does. */
function PersonRow({ member, onOpen }: { member: StaffMember; onOpen: () => void }) {
  const term = termOf(member)
  const tags = member.account_holder ? (
    <span className="settings__tag">{copy.people.titular}</span>
  ) : member.appointments.length === 0 ? (
    <span className="settings__tag">{copy.people.noRole}</span>
  ) : (
    member.appointments.map((a) => (
      <span key={a.id} className="settings__tag">
        {a.title_name}
      </span>
    ))
  )
  const can = member.account_holder ? copy.people.all : copy.people.count(member.permissions.length, PERMISSIONS.length)
  const detail = (
    <>
      <span className="team__roles">{tags}</span>
      <span className="team__term">
        <span className="team__narrow">{term.short}</span>
        <span className="team__wide">{term.wide}</span>
      </span>
      <span className="team__can team__wide">{can}</span>
    </>
  )
  return <OpenRow label={member.name} className="team__person" title={member.name} detail={detail} onOpen={member.manageable ? onOpen : undefined} />
}

/** A row named `label`: with `onOpen`, the whole row is the button that opens it, as
 * `EditRow`'s; without, the row and nothing more. */
function OpenRow({
  label,
  className,
  title,
  detail,
  onOpen,
}: {
  label: string
  className: string
  title: ReactNode
  detail: ReactNode
  onOpen?: () => void
}) {
  return (
    <li aria-label={label} className={`settings__row ${className}`}>
      {onOpen ? (
        <button type="button" className={listRowClass(true)} onClick={onOpen}>
          <ListRowContent title={title} detail={detail} trailing={<ChevronRightIcon />} />
        </button>
      ) : (
        // The chevron's room, kept so its cells line up with the rows that open.
        <ListRow title={title} detail={detail} trailing={<span className="team__no-chevron" aria-hidden="true" />} />
      )}
    </li>
  )
}

/** A person, open: each appointment's dates, "Terminar cargo", "Agregar cargo", and
 * "Puede:" in words. */
function PersonPanel({
  member,
  titles,
  onClose,
  onDone,
}: {
  member: StaffMember
  titles: Title[]
  onClose: () => void
  onDone: (message: string) => void
}) {
  const contact = [member.phone && formatPhone(member.phone), member.email].filter(Boolean).join(' · ')
  const can = inWords(member.permissions)
  return (
    <Card as="div" className="settings__card settings__form" role="group" aria-label={member.name}>
      <SectionTitle className="settings__legend">{member.name}</SectionTitle>
      {contact && <p className="settings__detail">{contact}</p>}
      <PlainList className="team__appointments">
        {member.appointments.map((appointment) => (
          <li key={appointment.id}>
            <AppointmentEditor member={member} appointment={appointment} onDone={onDone} />
          </li>
        ))}
      </PlainList>
      <AddAppointment member={member} titles={titles} onDone={onDone} />
      <div className="team__can-list">
        <p className="settings__legend">{copy.panel.can}</p>
        <p className="settings__detail">{can.length > 0 ? joined(can) : copy.panel.nothing}</p>
      </div>
      <div className="settings__actions">
        <Button onClick={onClose}>{copy.panel.close}</Button>
      </div>
    </Card>
  )
}

function AppointmentEditor({
  member,
  appointment,
  onDone,
}: {
  member: StaffMember
  appointment: StaffAppointment
  onDone: (message: string) => void
}) {
  const refresh = useRefresh()
  const [from, setFrom] = useState(appointment.starts_on)
  const [until, setUntil] = useState(appointment.ends_on ?? '')
  const [confirming, setConfirming] = useState(false)
  const role = appointment.title_name

  const correct = useSubmit({
    mutationFn: () => correctAppointment(member.person_id, appointment.id, { starts_on: from, ends_on: until || null }),
    onSuccess: async () => {
      onDone(copy.panel.datesSaved(role))
      await refresh()
    },
  })
  const end = useSubmit({
    mutationFn: () => endAppointment(member.person_id, appointment.id),
    onSuccess: async () => {
      onDone(copy.panel.ended(role, member.name))
      await refresh()
    },
  })
  const pending = correct.isPending || end.isPending
  const changed = from !== appointment.starts_on || until !== (appointment.ends_on ?? '')

  if (!appointment.manageable) {
    return (
      <p className="team__appointment">
        <strong>{role}</strong>{' '}
        <span className="settings__detail">
          {copy.history.term(shortDate(appointment.starts_on), appointment.ends_on && shortDate(appointment.ends_on))}
        </span>
      </p>
    )
  }
  const error =
    statusOf(correct.error) === 409 ? copy.panel.overlaps : statusOf(correct.error) === 422 ? copy.panel.badTerm : undefined
  return (
    <fieldset className="team__appointment">
      <legend className="settings__legend">{role}</legend>
      <div className="team__dates">
        <Field label={copy.panel.from}>
          {(props) => <Input {...props} type="date" required value={from} onChange={(e) => setFrom(e.target.value)} />}
        </Field>
        <Field label={copy.panel.until} hint={copy.panel.untilHint} error={error}>
          {(props) => <Input {...props} type="date" value={until} onChange={(e) => setUntil(e.target.value)} />}
        </Field>
      </div>
      {(correct.isError || end.isError) && !error && <Banner tone="error">{copy.actionFailed}</Banner>}
      <div className="settings__actions">
        {changed && (
          <Button disabled={pending || !from} busy={correct.isPending} onClick={() => correct.mutate()}>
            {copy.panel.saveDates}
          </Button>
        )}
        {confirming ? (
          <span className="team__confirm" role="group" aria-label={copy.panel.confirmEnd(role, member.name)}>
            <span className="settings__detail">{copy.panel.confirmEnd(role, member.name)}</span>
            <Button disabled={pending} onClick={() => setConfirming(false)}>
              {copy.cancel}
            </Button>
            <Button variant="danger" disabled={pending} busy={end.isPending} onClick={() => end.mutate()}>
              {copy.panel.confirm}
            </Button>
          </span>
        ) : (
          <Button variant="danger" disabled={pending} onClick={() => setConfirming(true)}>
            {copy.panel.end}
          </Button>
        )}
      </div>
    </fieldset>
  )
}

function AddAppointment({
  member,
  titles,
  onDone,
}: {
  member: StaffMember
  titles: Title[]
  onDone: (message: string) => void
}) {
  const refresh = useRefresh()
  const choices = titles.filter((title) => title.manageable)
  const [titleId, setTitleId] = useState(choices[0]?.id ?? '')
  const [from, setFrom] = useState(today())
  const [until, setUntil] = useState('')
  const save = useSubmit({
    mutationFn: () => appoint(member.person_id, { title_id: titleId, starts_on: from, ...(until ? { ends_on: until } : {}) }),
    onSuccess: async () => {
      const name = choices.find((title) => title.id === titleId)?.name ?? ''
      onDone(copy.panel.appointed(name, member.name))
      await refresh()
    },
  })
  if (choices.length === 0) return <p className="settings__detail">{copy.panel.noneToGive}</p>
  const error =
    statusOf(save.error) === 409 ? copy.panel.overlaps : statusOf(save.error) === 422 ? copy.panel.badTerm : undefined
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form className="team__add" aria-label={copy.panel.add} onSubmit={submit} noValidate>
      <p className="settings__legend">{copy.panel.add}</p>
      <Field label={copy.panel.role}>
        {(props) => (
          <Select {...props} value={titleId} onChange={(e) => setTitleId(e.target.value)}>
            {choices.map((title) => (
              <option key={title.id} value={title.id}>
                {title.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <div className="team__dates">
        <Field label={copy.panel.from}>
          {(props) => <Input {...props} type="date" required value={from} onChange={(e) => setFrom(e.target.value)} />}
        </Field>
        <Field label={copy.panel.until} hint={copy.panel.untilHint} error={error}>
          {(props) => <Input {...props} type="date" value={until} onChange={(e) => setUntil(e.target.value)} />}
        </Field>
      </div>
      {save.isError && !error && <Banner tone="error">{copy.actionFailed}</Banner>}
      <div className="settings__actions">
        <Button type="submit" disabled={save.isPending || !from} busy={save.isPending}>
          {copy.panel.appoint}
        </Button>
      </div>
    </form>
  )
}

// --- Cargos ----------------------------------------------------------------------------

function Cargos({
  titles,
  acting,
  onDone,
}: {
  titles: Title[]
  acting: Access | null | undefined
  onDone: (message: string) => void
}) {
  // The role open to edit, `new` for one being created.
  const [opened, setOpened] = useState<string | null>(null)
  const [presets, setPresets] = useState(false)
  const finish = (message: string) => {
    setOpened(null)
    setPresets(false)
    onDone(message)
  }
  return (
    <Section title={copy.titles.title} id="team-titles">
      {titles.length > 0 && (
        <div className="team__marks-head team__wide" aria-hidden="true">
          <span />
          {PERMISSIONS.map((p) => (
            <span key={p}>{copy.short[p]}</span>
          ))}
        </div>
      )}
      <Card as="ul" flush className="settings__card settings__card--rows settings__menu team__titles">
        {titles.length === 0 && opened !== 'new' && (
          <li>
            <ListRow title={copy.titles.empty} />
          </li>
        )}
        {titles.map((title) =>
          opened === title.id ? (
            <li key={title.id} aria-label={title.name}>
              <TitleForm title={title} acting={acting} onCancel={() => setOpened(null)} onDone={finish} />
            </li>
          ) : (
            <TitleRow key={title.id} title={title} onOpen={() => setOpened(title.id)} />
          ),
        )}
        {opened === 'new' && (
          <li aria-label={copy.titles.form.title}>
            <TitleForm acting={acting} onCancel={() => setOpened(null)} onDone={finish} />
          </li>
        )}
      </Card>
      {presets && <PresetPicker onCancel={() => setPresets(false)} onDone={finish} />}
      {opened !== 'new' && !presets && (
        <div className="settings__actions team__title-actions">
          <Button onClick={() => setOpened('new')}>{copy.titles.add}</Button>
          <Button onClick={() => setPresets(true)}>{copy.titles.addPreset}</Button>
        </div>
      )}
    </Section>
  )
}

/** A role: its permissions in words on a phone, a ✓ per permission from 1024px. */
function TitleRow({ title, onOpen }: { title: Title; onOpen: () => void }) {
  const words = inWords(title.permissions)
  const held = new Set(title.permissions)
  const detail = (
    <>
      {/* From 1024px read by a screen reader only: the marks show it. */}
      <span className="team__words">{words.length > 0 ? words.join(', ') : copy.titles.none}</span>
      <span className="team__marks team__wide" aria-hidden="true">
        {PERMISSIONS.map((p) => (
          <span key={p} className={held.has(p) ? 'team__mark team__mark--on' : 'team__mark'}>
            {held.has(p) ? '✓' : '–'}
          </span>
        ))}
      </span>
    </>
  )
  const name = (
    <>
      {title.name}
      {title.preset && <span className="settings__tag">{copy.presets[title.preset]}</span>}
    </>
  )
  return <OpenRow label={title.name} className="team__title" title={name} detail={detail} onOpen={title.manageable ? onOpen : undefined} />
}

/** A role, new or open: its name, whether students see it, and one checkbox per
 * permission with its help. A permission the signed-in person lacks is disabled, with
 * why. Saving what widens its current holders' access says so first. */
function TitleForm({
  title,
  acting,
  onCancel,
  onDone,
}: {
  title?: Title
  acting: Access | null | undefined
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const refresh = useRefresh()
  const [name, setName] = useState(title?.name ?? '')
  const [visible, setVisible] = useState(title?.public ?? false)
  const [permissions, setPermissions] = useState<Permission[]>(title?.permissions ?? [])
  const [warned, setWarned] = useState(false)
  const [archiving, setArchiving] = useState(false)

  const toggle = (permission: Permission, on: boolean) => {
    if (on) setPermissions(withImplied([...permissions, permission]))
    // Without it, nothing that implies it either.
    else setPermissions(permissions.filter((p) => p !== permission && IMPLIES[p] !== permission))
    setWarned(false)
  }
  const added = title ? permissions.filter((p) => !title.permissions.includes(p)) : []
  const widens = title !== undefined && title.holders > 0 && added.length > 0

  const save = useSubmit({
    mutationFn: () =>
      title
        ? changeTitle(title.id, { name, permissions, public: visible })
        : createTitle({ name, permissions, public: visible }),
    onSuccess: async (saved) => {
      onDone(title ? copy.titles.saved(saved.name) : copy.titles.created(saved.name))
      await refresh()
    },
  })
  const archive = useSubmit({
    mutationFn: () => archiveTitle(title!.id),
    onSuccess: async () => {
      onDone(copy.titles.archived(title!.name))
      await refresh()
    },
  })
  const pending = save.isPending || archive.isPending
  const errors = validationErrors(save.error)
  const nameError =
    statusOf(save.error) === 409
      ? copy.titles.nameTaken
      : 'name' in errors
        ? refusal(errors.name!, 'name', copy, name.trim() === '')
        : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (widens && !warned) {
      setWarned(true)
      return
    }
    save.mutate()
  }

  return (
    <form
      className={cardClass({}, 'settings__card settings__form')}
      aria-label={title?.name ?? copy.titles.form.title}
      onSubmit={submit}
      noValidate
    >
      <SectionTitle className="settings__legend">{title?.name ?? copy.titles.form.title}</SectionTitle>
      <Field label={copy.titles.form.name} hint={copy.titles.form.nameHint} error={nameError}>
        {(props) => (
          <Input {...props} type="text" maxLength={60} autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
        )}
      </Field>
      <CheckRow start>
        <input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
        <span>
          {copy.titles.form.public}
          <span className="settings__detail team__help">{copy.titles.form.publicHint}</span>
        </span>
      </CheckRow>
      <fieldset className="team__permissions">
        <legend className="settings__legend">{copy.titles.form.permissions}</legend>
        {PERMISSIONS.map((permission) => {
          const mine = holds(acting, permission)
          const implied = PERMISSIONS.find((p) => IMPLIES[p] === permission && permissions.includes(p))
          return (
            <CheckRow start key={permission}>
              <input
                type="checkbox"
                checked={permissions.includes(permission)}
                // Kept by what implies it, until that goes.
                disabled={!mine || implied !== undefined}
                onChange={(e) => toggle(permission, e.target.checked)}
              />
              <span>
                {copy.permissions[permission]}
                <span className="settings__detail team__help">
                  {!mine
                    ? copy.titles.form.notYours
                    : implied
                      ? copy.titles.form.implied(copy.permissions[implied]!)
                      : copy.help[permission]}
                </span>
              </span>
            </CheckRow>
          )
        })}
      </fieldset>
      {warned && (
        <Banner tone="warning">
          {copy.titles.widens(copy.titles.holders(title!.holders), joined(inWords(added)).toLowerCase())}
        </Banner>
      )}
      {save.isError && !nameError && (
        <Banner tone="error">{statusOf(save.error) === 403 ? copy.titles.notAllowed : copy.actionFailed}</Banner>
      )}
      <div className="settings__actions">
        <Button disabled={pending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={pending} busy={save.isPending}>
          {warned ? copy.titles.widensConfirm : copy.titles.save}
        </Button>
      </div>
      {title && (
        <div className="settings__danger">
          {archive.isError && (
            <Banner tone="error">{statusOf(archive.error) === 409 ? copy.titles.held : copy.actionFailed}</Banner>
          )}
          {archiving ? (
            <div className="settings__plan-text" role="group" aria-label={copy.titles.confirmArchive(title.name)}>
              <p className="settings__detail">{copy.titles.confirmArchive(title.name)}</p>
              <div className="settings__actions">
                <Button disabled={pending} onClick={() => setArchiving(false)}>
                  {copy.cancel}
                </Button>
                <Button variant="danger" disabled={pending} busy={archive.isPending} onClick={() => archive.mutate()}>
                  {copy.titles.confirm}
                </Button>
              </div>
            </div>
          ) : (
            <Button variant="danger" disabled={pending} onClick={() => setArchiving(true)}>
              {copy.titles.archive}
            </Button>
          )}
        </div>
      )}
    </form>
  )
}

/** "Agregar plantilla": one of the presets, its roles beside the gym's. */
function PresetPicker({ onCancel, onDone }: { onCancel: () => void; onDone: (message: string) => void }) {
  const refresh = useRefresh()
  const add = useSubmit({
    mutationFn: (preset: PresetKey) => addPreset(preset),
    onSuccess: async (added) => {
      onDone(copy.titles.presetAdded(added.length))
      await refresh()
    },
  })
  return (
    <Card className="settings__card settings__form" role="group" aria-label={copy.titles.addPreset}>
      <SectionTitle className="settings__legend">{copy.titles.addPreset}</SectionTitle>
      <PlainList className="team__choices">
        {PRESET_KEYS.map((preset) => (
          <li key={preset} className="team__choice">
            <span>
              <strong>{copy.presets[preset]}</strong>
              <span className="settings__detail">{copy.presetRoles[preset]}</span>
            </span>
            <Button disabled={add.isPending} onClick={() => add.mutate(preset)}>
              {copy.setup.choose(copy.presets[preset]!)}
            </Button>
          </li>
        ))}
      </PlainList>
      {add.isError && (
        <Banner tone="error">{statusOf(add.error) === 403 ? copy.titles.notAllowed : copy.actionFailed}</Banner>
      )}
      <div className="settings__actions">
        <Button disabled={add.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
      </div>
    </Card>
  )
}

// --- Historial -------------------------------------------------------------------------

/** Every appointment, newest first, under the name its role had then. Asked for only
 * once opened. */
function History() {
  const [open, setOpen] = useState(false)
  const history = useQuery({ ...staffHistoryQuery, enabled: open })
  return (
    <details className="team__history" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <SectionTitle as="summary">{copy.history.title}</SectionTitle>
      {history.isPending ? (
        open && <Loading className="settings__note">{t.admin.settings.loading}</Loading>
      ) : history.isError ? (
        <LoadFailed error={history.error} message={copy.error} retry={() => void history.refetch()} />
      ) : history.data.length === 0 ? (
        <p className="settings__note">{copy.history.empty}</p>
      ) : (
        <Card as="ul" flush className="settings__card settings__card--rows">
          {history.data.map((entry) => (
            <li key={entry.id}>
              <ListRow
                title={`${entry.person_name} · ${entry.title_name}`}
                detail={
                  entry.ends_on === entry.starts_on
                    ? `${shortDate(entry.starts_on)}, ${copy.history.never}`
                    : copy.history.term(shortDate(entry.starts_on), entry.ends_on && shortDate(entry.ends_on))
                }
              />
            </li>
          ))}
        </Card>
      )}
    </details>
  )
}

// --- Invitar ---------------------------------------------------------------------------

type Drafts = { name: string; rut: string; email: string; phone: string; from: string; until: string }

function InviteForm({
  titles,
  onCancel,
  onDone,
}: {
  titles: Title[]
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const refresh = useRefresh()
  const choices = titles.filter((title) => title.manageable)
  const [drafts, setDrafts] = useState<Drafts>({ name: '', rut: '', email: '', phone: '', from: today(), until: '' })
  const [roles, setRoles] = useState<string[]>([])
  const [rolesNeeded, setRolesNeeded] = useState(false)
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  const save = useSubmit({
    // The optional ones only when typed: an empty RUT or phone is none, not an invalid one.
    mutationFn: () =>
      inviteStaff({
        name: drafts.name,
        email: drafts.email,
        rut: drafts.rut.trim() || undefined,
        phone: drafts.phone.trim() || undefined,
        title_ids: roles,
        starts_on: drafts.from || undefined,
        ends_on: drafts.until || undefined,
      }),
    onSuccess: async (answer) => {
      onDone(copy.invited(answer.name, answer.email ?? drafts.email))
      await refresh()
    },
  })
  // A 409 is someone already on the staff, or an email another person here has.
  const taken = statusOf(save.error) === 409
  const emailTaken = duplicateOf(save.error)?.code === 'email_in_gym'
  const errors = validationErrors(save.error)
  const error = (field: 'name' | 'rut' | 'email' | 'phone') =>
    field === 'email' && taken
      ? emailTaken
        ? copy.emailTaken
        : copy.alreadyStaff
      : field in errors
        ? refusal(errors[field]!, field, copy, drafts[field].trim() === '')
        : undefined
  const termError = statusOf(save.error) === 422 && !Object.keys(errors).some((f) => f !== 'ends_on') ? copy.panel.badTerm : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (roles.length === 0) {
      setRolesNeeded(true)
      return
    }
    save.mutate()
  }

  return (
    <form className={cardClass({}, 'settings__card settings__form')} aria-label={copy.form.title} onSubmit={submit} noValidate>
      <SectionTitle className="settings__legend">{copy.form.title}</SectionTitle>
      <Field label={copy.form.name} error={error('name')}>
        {(props) => (
          <Input {...props} type="text" maxLength={200} autoComplete="off" value={drafts.name} onChange={(e) => set('name', e.target.value)} />
        )}
      </Field>
      <Field label={copy.form.rut} hint={copy.form.rutHint} error={error('rut')}>
        {(props) => <Input {...props} type="text" autoComplete="off" value={drafts.rut} onChange={(e) => set('rut', e.target.value)} />}
      </Field>
      <Field label={copy.form.phone} error={error('phone')}>
        {(props) => (
          <Input {...props} type="tel" inputMode="tel" autoComplete="off" value={drafts.phone} onChange={(e) => set('phone', e.target.value)} />
        )}
      </Field>
      <Field label={copy.form.email} hint={copy.form.emailHint} error={error('email')}>
        {(props) => (
          <Input
            {...props}
            type="email"
            inputMode="email"
            autoComplete="off"
            value={drafts.email}
            onChange={(e) => set('email', e.target.value)}
          />
        )}
      </Field>
      <fieldset className="team__permissions" aria-describedby="invite-roles-hint">
        <legend className="settings__legend">{copy.form.roles}</legend>
        <p className="settings__detail" id="invite-roles-hint">
          {choices.length > 0 ? copy.form.rolesHint : copy.panel.noneToGive}
        </p>
        {choices.map((title) => (
          <CheckRow key={title.id}>
            <input
              type="checkbox"
              checked={roles.includes(title.id)}
              onChange={(e) => {
                setRolesNeeded(false)
                setRoles(e.target.checked ? [...roles, title.id] : roles.filter((r) => r !== title.id))
              }}
            />
            <span>{title.name}</span>
          </CheckRow>
        ))}
        {rolesNeeded && (
          <p className="field__error" role="alert">
            {copy.form.rolesNeeded}
          </p>
        )}
      </fieldset>
      <div className="team__dates">
        <Field label={copy.form.from}>
          {(props) => <Input {...props} type="date" value={drafts.from} onChange={(e) => set('from', e.target.value)} />}
        </Field>
        <Field label={copy.form.until} hint={copy.panel.untilHint} error={termError}>
          {(props) => <Input {...props} type="date" value={drafts.until} onChange={(e) => set('until', e.target.value)} />}
        </Field>
      </div>
      {save.isError && !termError && (
        <Banner tone="error">{taken || Object.keys(errors).length > 0 ? copy.invalid : copy.failed}</Banner>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? copy.working : copy.submit}
        </Button>
      </div>
    </form>
  )
}
