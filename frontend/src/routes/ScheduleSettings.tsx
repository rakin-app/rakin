import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  closeDay,
  closedDaysQuery,
  createSlot,
  deleteSlot,
  reopenDay,
  scheduleQuery,
  updateSlot,
  type ScheduleSlot,
  type SlotChanges,
  type SlotFields,
} from '../api/schedule'
import { activeClassTypesQuery, useGymToday } from '../api/sessions'
import { staffQuery } from '../api/staff'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { FieldError, Input, Select } from '../components/Field'
import { shortDay, weekdayDay, toDate } from '../format'
import { t } from '../i18n/es'
import { Field, LoadFailed } from './settingsForm'

const copy = t.admin.settings.schedule
const form = copy.form

const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const

/** `19:00`, from the API's `19:00:00`. */
function hhmm(time: string): string {
  return time.slice(0, 5)
}

/** `19:00–20:30`: a wall time and the one `minutes` later, past midnight included. */
function slotRange(start: string, minutes: number): string {
  const [h, m] = start.split(':').map(Number) as [number, number]
  const end = (h * 60 + m + minutes) % (24 * 60)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${hhmm(start)}–${pad(Math.floor(end / 60))}:${pad(end % 60)}`
}

/** Every class this section changes is listed elsewhere too: the day's, and the slots. */
function refresh(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ['schedule'] })
  void queryClient.invalidateQueries({ queryKey: ['sessions'] })
}

/**
 * "Horario": the gym's weekly timetable, owner and admin. Each class of it (a slot) is
 * a class type on some weekdays, at a time, for a duration, with a default coach and
 * topic, from a date and, if set, until one; Rakin makes its classes for the next two
 * weeks, so Clases shows them before they start. Editing one changes it from a date on
 * ("a partir de"); the classes before that date, and those already held or with
 * attendance, stay as they were. Below, the days the gym is closed ("Cerrado"), which
 * have no classes.
 */
export function ScheduleSettings() {
  const slots = useQuery(scheduleQuery)
  const today = useGymToday()
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (id: string | 'new') => {
    setNotice(null)
    setEditing(id)
  }

  if (slots.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (slots.isError) {
    return <LoadFailed error={slots.error} message={copy.error} retry={() => void slots.refetch()} />
  }
  // Ended slots are the timetable as it was: only those still running, or yet to, show.
  const current = slots.data.filter((slot) => slot.valid_to === null || slot.valid_to >= today)

  return (
    <>
      <section className="settings__section" aria-label={copy.title}>
        <p className="settings__note">{copy.intro}</p>
        {notice && (
          <p className="settings__done" role="status">
            {notice}
          </p>
        )}
        {editing === 'new' ? (
          <SlotForm today={today} onCancel={() => setEditing(null)} onDone={done} />
        ) : (
          <Button variant="primary" onClick={() => open('new')}>
            {copy.add}
          </Button>
        )}
        {current.length === 0 ? (
          <p className="settings__note">{copy.empty}</p>
        ) : (
          <ul className="settings__list">
            {current.map((slot) =>
              editing === slot.id ? (
                <li key={slot.id}>
                  <SlotForm slot={slot} today={today} onCancel={() => setEditing(null)} onDone={done} />
                </li>
              ) : (
                <SlotRow key={slot.id} slot={slot} today={today} onEdit={() => open(slot.id)} onDone={done} />
              ),
            )}
          </ul>
        )}
      </section>
      <ClosedDays today={today} />
    </>
  )
}

function SlotRow({
  slot,
  today,
  onEdit,
  onDone,
}: {
  slot: ScheduleSlot
  today: string
  onEdit: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const remove = useMutation({
    mutationFn: () => deleteSlot(slot.id),
    onSuccess: () => {
      refresh(queryClient)
      onDone(copy.deleted(slot.class_type_name))
    },
  })
  const days = slot.weekdays.map((d) => copy.weekdays[d - 1]).join(' · ')
  return (
    <li className={slot.class_type_active ? 'settings__card settings__plan' : 'settings__card settings__plan settings__plan--inactive'}>
      <div className="settings__plan-text">
        <span className="settings__plan-name">
          {copy.row(days, slotRange(slot.start_time, slot.duration_minutes), slot.class_type_name)}
          {!slot.class_type_active && <span className="settings__tag">{copy.inactive}</span>}
        </span>
        <span className="settings__detail">{copy.detail(slot.program_name, slot.coach_name, slot.topic)}</span>
        <span className="settings__detail">
          {copy.validity(
            slot.valid_from > today ? shortDay(slot.valid_from) : null,
            slot.valid_to ? shortDay(slot.valid_to) : null,
          )}
        </span>
      </div>
      {asking ? (
        <div className="settings__subcard" role="group" aria-label={copy.delete}>
          <p className="settings__note">{copy.deleteConfirm}</p>
          {remove.isError && (
            <p className="settings__error" role="alert">
              {copy.deleteFailed}
            </p>
          )}
          <div className="settings__actions">
            <Button disabled={remove.isPending} onClick={() => setAsking(false)}>
              {form.cancel}
            </Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending ? form.working : copy.deleteYes}
            </Button>
          </div>
        </div>
      ) : (
        <div className="settings__actions">
          <Button onClick={onEdit}>
            {copy.edit}
          </Button>
          <Button variant="danger" onClick={() => setAsking(true)}>
            {copy.delete}
          </Button>
        </div>
      )}
    </li>
  )
}

function SlotForm({
  slot,
  today,
  onCancel,
  onDone,
}: {
  slot?: ScheduleSlot
  today: string
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const classTypes = useQuery(activeClassTypesQuery())
  const staff = useQuery(staffQuery)
  const types = classTypes.data ?? []
  const people = staff.data ?? []

  const [classTypeId, setClassTypeId] = useState(slot?.class_type_id ?? '')
  const [weekdays, setWeekdays] = useState<number[]>(slot?.weekdays ?? [])
  const [time, setTime] = useState(slot ? hhmm(slot.start_time) : '19:00')
  const [duration, setDuration] = useState(String(slot?.duration_minutes ?? 60))
  const [coachId, setCoachId] = useState(slot?.coach_id ?? '')
  const [topic, setTopic] = useState(slot?.topic ?? '')
  // A new slot runs from; a change applies from.
  const [from, setFrom] = useState(slot && slot.valid_from > today ? slot.valid_from : today)
  const [until, setUntil] = useState(slot?.valid_to ?? '')

  // The slot's own type and coach stay choosable though deactivated or gone from staff.
  const typeChoices =
    slot && !types.some((c) => c.id === slot.class_type_id)
      ? [{ id: slot.class_type_id, name: form.inactiveType(slot.class_type_name) }, ...types]
      : types
  const coachChoices =
    slot && !people.some((p) => p.person_id === slot.coach_id)
      ? [{ person_id: slot.coach_id, name: slot.coach_name }, ...people]
      : people
  const chosenType = classTypeId || types[0]?.id || ''
  const chosenCoach = coachId || people[0]?.person_id || ''

  const minutes = Number(duration)
  const fields = (): SlotFields => ({
    class_type_id: chosenType,
    weekdays,
    start_time: time,
    duration_minutes: minutes,
    coach_id: chosenCoach,
    topic: topic.trim() || null,
    valid_to: until || null,
  })
  // A change sends what differs from the slot; the API ignores the rest anyway.
  const changes = (): SlotChanges => {
    const all = fields()
    const out: SlotChanges = {}
    if (all.class_type_id !== slot!.class_type_id) out.class_type_id = all.class_type_id
    if (all.weekdays.join() !== slot!.weekdays.join()) out.weekdays = all.weekdays
    if (all.start_time !== hhmm(slot!.start_time)) out.start_time = all.start_time
    if (all.duration_minutes !== slot!.duration_minutes) out.duration_minutes = all.duration_minutes
    if (all.coach_id !== slot!.coach_id) out.coach_id = all.coach_id
    if (all.topic !== slot!.topic) out.topic = all.topic
    if (all.valid_to !== slot!.valid_to) out.valid_to = all.valid_to
    return out
  }

  const save = useMutation({
    mutationFn: () =>
      slot ? updateSlot(slot.id, { ...changes(), from_date: from }) : createSlot({ ...fields(), valid_from: from }),
    onSuccess: (answer) => {
      refresh(queryClient)
      onDone(slot ? copy.saved(answer.class_type_name) : copy.created(answer.class_type_name))
    },
  })
  const errors = validationErrors(save.error)
  const badDuration = !(Number.isInteger(minutes) && minutes >= 1 && minutes <= 1440)
  const noDays = weekdays.length === 0
  const endsTooSoon = until !== '' && until < from

  const toggleDay = (day: number) =>
    setWeekdays((days) => (days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort()))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (badDuration || noDays || endsTooSoon || !chosenType || !chosenCoach) return
    if (slot && Object.keys(changes()).length === 0) {
      onCancel()
      return
    }
    save.mutate()
  }

  const label = slot ? form.edit(slot.class_type_name) : form.create
  if (classTypes.isSuccess && types.length === 0 && !slot) {
    return (
      <div className="settings__card settings__form">
        <p className="settings__note">{form.noClassTypes}</p>
        <div className="settings__actions">
          <Button onClick={onCancel}>
            {form.cancel}
          </Button>
        </div>
      </div>
    )
  }
  return (
    <form className="settings__card settings__form" aria-label={label} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{label}</h2>
      <Field label={form.classType}>
        {(props) => (
          <Select {...props} value={chosenType} onChange={(e) => setClassTypeId(e.target.value)}>
            {typeChoices.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <fieldset className="settings__field schedule__days">
        <legend className="settings__label">{form.weekdays}</legend>
        <div className="schedule__day-list">
          {WEEKDAYS.map((day) => (
            <label key={day} className="settings__check schedule__day">
              <input type="checkbox" checked={weekdays.includes(day)} onChange={() => toggleDay(day)} />
              {copy.weekdays[day - 1]}
            </label>
          ))}
        </div>
        {noDays && <FieldError>{form.noDays}</FieldError>}
      </fieldset>
      <div className="schedule__pair">
        <Field label={form.time}>
          {(props) => (
            <Input
              {...props}
              type="time"
              required
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
          )}
        </Field>
        <Field label={form.duration} error={badDuration ? form.badDuration : undefined}>
          {(props) => (
            <Input
              {...props}
              type="number"
              inputMode="numeric"
              min={1}
              max={1440}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          )}
        </Field>
      </div>
      <Field label={form.coach}>
        {(props) => (
          <Select {...props} value={chosenCoach} onChange={(e) => setCoachId(e.target.value)}>
            {coachChoices.map((person) => (
              <option key={person.person_id} value={person.person_id}>
                {person.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={form.topic} hint={form.topicHint}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={200}
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
        )}
      </Field>
      <div className="schedule__pair">
        <Field label={slot ? form.fromDate : form.validFrom} hint={slot ? form.fromHint : undefined}>
          {(props) => (
            <Input
              {...props}
              type="date"
              required
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          )}
        </Field>
        <Field label={form.validTo} hint={form.validToHint} error={endsTooSoon ? form.endsTooSoon : undefined}>
          {(props) => (
            <Input
              {...props}
              type="date"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          )}
        </Field>
      </div>
      {save.error && (
        <p className="settings__error" role="alert">
          {'class_type_id' in errors && errors['class_type_id'] === 'open_mat_plan'
            ? form.openMatPlan
            : 'from_date' in errors
              ? form.afterEnd
              : Object.keys(errors).length > 0
                ? form.invalid
                : form.failed}
        </p>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

/** "Días cerrados": a date with no classes, a holiday say. Closing one takes its classes
 * of the schedule off; reopening it puts them back. */
function ClosedDays({ today }: { today: string }) {
  const words = copy.closed
  const queryClient = useQueryClient()
  const days = useQuery(closedDaysQuery)
  const [day, setDay] = useState('')
  const [label, setLabel] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const close = useMutation({
    mutationFn: () => closeDay(day, label),
    onSuccess: (answer) => {
      refresh(queryClient)
      setDay('')
      setLabel('')
      setNotice(words.closedDone(weekdayDay(toDate(answer.day))))
    },
  })
  const reopen = useMutation({
    mutationFn: reopenDay,
    onSuccess: (_, reopened) => {
      refresh(queryClient)
      setNotice(words.reopened(weekdayDay(toDate(reopened))))
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!day || day < today) return
    setNotice(null)
    close.mutate()
  }

  return (
    <section className="settings__section" aria-labelledby="closed-days">
      <h2 id="closed-days" className="settings__legend">
        {words.title}
      </h2>
      <p className="settings__note">{words.intro}</p>
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      <form className="settings__card settings__form" aria-label={words.add} onSubmit={submit} noValidate>
        <div className="schedule__pair">
          <Field label={words.day} error={day && day < today ? words.past : undefined}>
            {(props) => (
              <Input
                {...props}
                type="date"
                min={today}
                value={day}
                onChange={(e) => setDay(e.target.value)}
              />
            )}
          </Field>
          <Field label={words.label}>
            {(props) => (
              <Input
                {...props}
                type="text"
                maxLength={100}
                placeholder={words.labelPlaceholder}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            )}
          </Field>
        </div>
        {close.isError && (
          <p className="settings__error" role="alert">
            {words.failed}
          </p>
        )}
        <div className="settings__actions">
          <Button type="submit" disabled={close.isPending || !day || day < today}>
            {close.isPending ? form.working : words.add}
          </Button>
        </div>
      </form>
      {days.isPending ? (
        <p className="settings__note">{t.admin.settings.loading}</p>
      ) : days.isError ? (
        <LoadFailed error={days.error} message={words.error} retry={() => void days.refetch()} />
      ) : days.data.length === 0 ? (
        <p className="settings__note">{words.empty}</p>
      ) : (
        <ul className="settings__list">
          {days.data.map((closed) => (
            <li key={closed.day} className="settings__card settings__plan">
              <div className="settings__plan-text">
                <span className="settings__plan-name">{weekdayDay(toDate(closed.day))}</span>
                {closed.label && <span className="settings__detail">{closed.label}</span>}
              </div>
              <div className="settings__actions">
                <Button
                  disabled={reopen.isPending}
                  onClick={() => {
                    setNotice(null)
                    reopen.mutate(closed.day)
                  }}
                >
                  {words.reopen}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {reopen.isError && (
        <p className="settings__error" role="alert">
          {words.failed}
        </p>
      )}
    </section>
  )
}
