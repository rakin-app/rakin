import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { sessionPlanQuery } from '../api/sessionBlocks'
import { updateSlot, type SlotChanges } from '../api/schedule'
import {
  activeClassTypesQuery,
  cancelSession,
  deleteSession,
  reactivateSession,
  updateSession,
  type ClassSession,
  type SessionChanges,
} from '../api/sessions'
import { staffQuery } from '../api/staff'
import { Button } from '../components/Button'
import { useLeaveTo } from '../components/BackLink'
import { Input, Select } from '../components/Field'
import { clockTime, isoDay, zonedInstant } from '../format'
import { t } from '../i18n/es'
import { useSubmit } from '../api/submit'

const copy = t.admin.session

/** Every list a class is on: the day's, the dashboard's unmarked, and its own. */
export function refreshSession(queryClient: QueryClient, session: ClassSession) {
  queryClient.setQueryData(['sessions', 'detail', session.id], session)
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'day'] })
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
}

/** Whether the API refused the change for `type` (a 422 on one field). */
function refusedFor(error: unknown, type: string): boolean {
  if (!(error instanceof ApiError) || error.status !== 422) return false
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  return Array.isArray(detail) && detail.some((d: { type?: unknown }) => d?.type === type)
}

/**
 * "Editar clase", owner and admin: its day and time in the gym's timezone, its
 * duration, its class type and its coach. Only what changed is sent; attendance taken
 * stays. A class of the weekly schedule asks first whether the change is for this
 * class alone or for it and the ones after it, which changes its slot from its date
 * on: the time, duration, type and coach then, but not the day, which is the slot's
 * weekdays (Ajustes, Horario).
 */
export function ClassEdit({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  const words = copy.edit
  const [open, setOpen] = useState(false)
  const [saved, setSaved] = useState(false)
  if (!open) {
    return (
      <>
        {saved && (
          <p className="classes__done" role="status">
            {words.saved}
          </p>
        )}
        <Button
          onClick={() => {
            setSaved(false)
            setOpen(true)
          }}
        >
          {words.open}
        </Button>
      </>
    )
  }
  return (
    <EditForm
      session={session}
      timeZone={timeZone}
      onClose={(done) => {
        setSaved(done)
        setOpen(false)
      }}
    />
  )
}

function EditForm({
  session,
  timeZone,
  onClose,
}: {
  session: ClassSession
  timeZone: string
  onClose: (saved: boolean) => void
}) {
  const words = copy.edit
  const queryClient = useQueryClient()
  const ids = { day: useId(), time: useId(), duration: useId(), type: useId(), coach: useId() }
  const classTypes = useQuery(activeClassTypesQuery())
  const staff = useQuery(staffQuery)
  const initial = {
    day: isoDay(session.starts_at, timeZone),
    time: clockTime(session.starts_at, timeZone),
  }
  const [day, setDay] = useState(initial.day)
  const [time, setTime] = useState(initial.time)
  const [duration, setDuration] = useState(session.duration_minutes?.toString() ?? '')
  const [classTypeId, setClassTypeId] = useState(session.class_type_id)
  const [coachId, setCoachId] = useState(session.coach_id)
  const [scope, setScope] = useState<'one' | 'series'>('one')
  const series = scope === 'series' && session.slot_id !== null && session.slot_date !== null

  const save = useSubmit({
    mutationFn: async (change: { one: SessionChanges } | { series: SlotChanges }) => {
      if ('one' in change) return updateSession(session.id, change.one)
      await updateSlot(session.slot_id!, { ...change.series, from_date: session.slot_date! })
      return null
    },
    onSuccess: (updated) => {
      if (updated) {
        refreshSession(queryClient, updated)
      } else {
        // This class and the ones after it, wherever they are listed.
        void queryClient.invalidateQueries({ queryKey: ['sessions'] })
        void queryClient.invalidateQueries({ queryKey: ['schedule'] })
      }
      // Its type may now be an open mat, or count otherwise: the timer and the roster follow.
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'blocks', session.id] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'roster', session.id] })
      onClose(true)
    },
  })

  // The class's own type and coach stay choosable though deactivated or gone from staff.
  const types = classTypes.data ?? []
  const typeChoices = types.some((c) => c.id === session.class_type_id)
    ? types
    : [{ id: session.class_type_id, name: words.inactive(session.class_type_name) }, ...types]
  const people = staff.data ?? []
  const coachChoices = people.some((p) => p.person_id === session.coach_id)
    ? people
    : [{ person_id: session.coach_id, name: session.coach_name }, ...people]

  const minutes = duration.trim() === '' ? null : Number(duration)
  const badDuration = minutes !== null && !(Number.isInteger(minutes) && minutes >= 1 && minutes <= 1440)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (badDuration || (series && minutes === null)) return
    if (series) {
      // Only what was changed here: what this class alone differs in (a substitute coach,
      // a moved time) stays its own, and never spreads to the classes after it.
      const slotChanges: SlotChanges = {}
      if (time !== initial.time) slotChanges.start_time = time
      if (minutes !== session.duration_minutes) slotChanges.duration_minutes = minutes!
      if (classTypeId !== session.class_type_id) slotChanges.class_type_id = classTypeId
      if (coachId !== session.coach_id) slotChanges.coach_id = coachId
      if (Object.keys(slotChanges).length === 0) {
        onClose(false)
        return
      }
      save.mutate({ series: slotChanges })
      return
    }
    const changes: SessionChanges = {}
    if (day !== initial.day || time !== initial.time) changes.starts_at = zonedInstant(day, time, timeZone)
    if (minutes !== session.duration_minutes) changes.duration_minutes = minutes
    if (classTypeId !== session.class_type_id) changes.class_type_id = classTypeId
    if (coachId !== session.coach_id) changes.coach_id = coachId
    if (Object.keys(changes).length === 0) {
      onClose(false)
      return
    }
    save.mutate({ one: changes })
  }

  return (
    <form className="classes__card classes__form" aria-label={words.label} onSubmit={submit}>
      {session.slot_id !== null && (
        <fieldset className="class-edit__scope">
          <legend className="classes__label">{words.scope.label}</legend>
          <label className="class-edit__choice">
            <input type="radio" name="scope" checked={scope === 'one'} onChange={() => setScope('one')} />
            {words.scope.one}
          </label>
          <label className="class-edit__choice">
            <input type="radio" name="scope" checked={scope === 'series'} onChange={() => setScope('series')} />
            {words.scope.series}
          </label>
          {series && <p className="classes__note">{words.scope.seriesHint}</p>}
        </fieldset>
      )}
      <div className="class-edit__when">
        {!series && (
          <div className="class-edit__field">
            <label htmlFor={ids.day} className="classes__label">
              {words.day}
            </label>
            <Input
              id={ids.day}
              type="date"
              required
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
          </div>
        )}
        <div className="class-edit__field">
          <label htmlFor={ids.time} className="classes__label">
            {words.time}
          </label>
          <Input
            id={ids.time}
            type="time"
            required
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </div>
        <div className="class-edit__field">
          <label htmlFor={ids.duration} className="classes__label">
            {words.duration}
          </label>
          <Input
            id={ids.duration}
            type="number"
            inputMode="numeric"
            min={1}
            max={1440}
            required={series}
            aria-invalid={badDuration}
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
          />
        </div>
      </div>
      {badDuration && (
        <p className="classes__error" role="alert">
          {words.badDuration}
        </p>
      )}
      <label htmlFor={ids.type} className="classes__label">
        {words.classType}
      </label>
      <Select
        id={ids.type}
        value={classTypeId}
        onChange={(e) => setClassTypeId(e.target.value)}
      >
        {typeChoices.map((type) => (
          <option key={type.id} value={type.id}>
            {type.name}
          </option>
        ))}
      </Select>
      <label htmlFor={ids.coach} className="classes__label">
        {words.coach}
      </label>
      <Select id={ids.coach} value={coachId} onChange={(e) => setCoachId(e.target.value)}>
        {coachChoices.map((person) => (
          <option key={person.person_id} value={person.person_id}>
            {person.name}
          </option>
        ))}
      </Select>
      <p className="classes__note">{words.hint}</p>
      {save.isError && (
        <p className="classes__error" role="alert">
          {refusedFor(save.error, 'open_mat_plan') ? words.openMatPlan : words.failed}
        </p>
      )}
      <Button
        type="submit"
        variant="primary"
        disabled={save.isPending || !day || !time || badDuration || (series && minutes === null)} busy={save.isPending}
      >
        {save.isPending ? words.working : words.submit}
      </Button>
      <Button onClick={() => onClose(false)}>
        {words.close}
      </Button>
    </form>
  )
}

type Asking = 'cancel' | 'delete' | null

/**
 * "Opciones de la clase", owner and admin: cancel a class that won't happen (or
 * reactivate it), or delete one made by mistake. Each asks first, and says what goes.
 */
export function ClassActions({ session }: { session: ClassSession }) {
  const words = copy.manage
  const queryClient = useQueryClient()
  // To Clases, and not back to the gone class (#250).
  const leave = useLeaveTo('/admin/clases')
  const plan = useQuery(sessionPlanQuery(session.id))
  const [asking, setAsking] = useState<Asking>(null)

  const status = useSubmit({
    mutationFn: (to: 'cancel' | 'reactivate') =>
      to === 'cancel' ? cancelSession(session.id) : reactivateSession(session.id),
    onSuccess: (updated) => {
      refreshSession(queryClient, updated)
      setAsking(null)
    },
  })
  const remove = useSubmit({
    mutationFn: () => deleteSession(session.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['sessions', 'detail', session.id] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'day'] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
      // Credits given back, classes and time on the mat changed for whoever was marked.
      void queryClient.invalidateQueries({ queryKey: ['attendance'] })
      void queryClient.invalidateQueries({ queryKey: ['time'] })
      leave()
    },
  })
  const failed = status.isError || remove.isError
  const working = status.isPending || remove.isPending
  const ask = (what: Asking) => {
    status.reset()
    remove.reset()
    setAsking(what)
  }

  return (
    <section className="classes__section" aria-labelledby="class-actions">
      <h2 id="class-actions" className="classes__section-title">
        {words.title}
      </h2>
      {asking === 'cancel' ? (
        <div className="classes__card class-actions__confirm" role="group" aria-label={words.cancel}>
          {session.present > 0 ? (
            <p className="classes__note">{words.hasAttendance}</p>
          ) : (
            <>
              <p className="classes__note">{words.cancelConfirm}</p>
              <Button
                variant="danger"
                disabled={working}
                onClick={() => status.mutate('cancel')}
              >
                {working ? words.working : words.cancelYes}
              </Button>
            </>
          )}
          <Button onClick={() => ask(null)}>
            {words.back}
          </Button>
        </div>
      ) : asking === 'delete' ? (
        <div className="classes__card class-actions__confirm" role="group" aria-label={words.delete}>
          <p className="classes__note">{words.deleteConfirm(session.present, (plan.data?.blocks.length ?? 0) > 0)}</p>
          {session.present > 0 && <p className="classes__note">{words.credits}</p>}
          <Button
            variant="danger"
            disabled={working || plan.isPending}
            onClick={() => remove.mutate()}
          >
            {working ? words.working : words.deleteYes}
          </Button>
          <Button onClick={() => ask(null)}>
            {words.back}
          </Button>
        </div>
      ) : (
        <div className="class-actions__buttons">
          {session.cancelled_at ? (
            <Button
              disabled={working}
              onClick={() => {
                status.reset()
                status.mutate('reactivate')
              }}
            >
              {working ? words.working : words.reactivate}
            </Button>
          ) : (
            <Button variant="danger" onClick={() => ask('cancel')}>
              {words.cancel}
            </Button>
          )}
          <Button variant="danger" onClick={() => ask('delete')}>
            {words.delete}
          </Button>
        </div>
      )}
      {failed && (
        <p className="classes__error" role="alert">
          {words.failed}
        </p>
      )}
    </section>
  )
}
