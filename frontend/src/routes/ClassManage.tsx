import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { sessionPlanQuery } from '../api/sessionBlocks'
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
import { clockTime, isoDay, zonedInstant } from '../format'
import { t } from '../i18n/es'

const copy = t.admin.session

/** Every list a class is on: the day's, the dashboard's unmarked, and its own. */
export function refreshSession(queryClient: QueryClient, session: ClassSession) {
  queryClient.setQueryData(['sessions', 'detail', session.id], session)
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
}

/** Whether the API refused the change for `type` (a 422 on one field). */
function refusedFor(error: unknown, type: string): boolean {
  if (!(error instanceof ApiError) || error.status !== 422) return false
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  return Array.isArray(detail) && detail.some((d: { type?: unknown }) => d?.type === type)
}

/**
 * "Editar clase", owner and admin: its day and time in the gym's timezone, its class
 * type and its coach. Only what changed is sent; attendance taken stays.
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
        <button
          type="button"
          className="classes__button"
          onClick={() => {
            setSaved(false)
            setOpen(true)
          }}
        >
          {words.open}
        </button>
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
  const ids = { day: useId(), time: useId(), type: useId(), coach: useId() }
  const classTypes = useQuery(activeClassTypesQuery())
  const staff = useQuery(staffQuery)
  const initial = {
    day: isoDay(session.starts_at, timeZone),
    time: clockTime(session.starts_at, timeZone),
  }
  const [day, setDay] = useState(initial.day)
  const [time, setTime] = useState(initial.time)
  const [classTypeId, setClassTypeId] = useState(session.class_type_id)
  const [coachId, setCoachId] = useState(session.coach_id)

  const save = useMutation({
    mutationFn: (changes: SessionChanges) => updateSession(session.id, changes),
    onSuccess: (updated) => {
      refreshSession(queryClient, updated)
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

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const changes: SessionChanges = {}
    if (day !== initial.day || time !== initial.time) changes.starts_at = zonedInstant(day, time, timeZone)
    if (classTypeId !== session.class_type_id) changes.class_type_id = classTypeId
    if (coachId !== session.coach_id) changes.coach_id = coachId
    if (Object.keys(changes).length === 0) {
      onClose(false)
      return
    }
    save.mutate(changes)
  }

  return (
    <form className="classes__card classes__form" aria-label={words.label} onSubmit={submit}>
      <div className="class-edit__when">
        <div className="class-edit__field">
          <label htmlFor={ids.day} className="classes__label">
            {words.day}
          </label>
          <input
            id={ids.day}
            className="classes__input"
            type="date"
            required
            value={day}
            onChange={(e) => setDay(e.target.value)}
          />
        </div>
        <div className="class-edit__field">
          <label htmlFor={ids.time} className="classes__label">
            {words.time}
          </label>
          <input
            id={ids.time}
            className="classes__input"
            type="time"
            required
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </div>
      </div>
      <label htmlFor={ids.type} className="classes__label">
        {words.classType}
      </label>
      <select
        id={ids.type}
        className="classes__input"
        value={classTypeId}
        onChange={(e) => setClassTypeId(e.target.value)}
      >
        {typeChoices.map((type) => (
          <option key={type.id} value={type.id}>
            {type.name}
          </option>
        ))}
      </select>
      <label htmlFor={ids.coach} className="classes__label">
        {words.coach}
      </label>
      <select id={ids.coach} className="classes__input" value={coachId} onChange={(e) => setCoachId(e.target.value)}>
        {coachChoices.map((person) => (
          <option key={person.person_id} value={person.person_id}>
            {person.name}
          </option>
        ))}
      </select>
      <p className="classes__note">{words.hint}</p>
      {save.isError && (
        <p className="classes__error" role="alert">
          {refusedFor(save.error, 'open_mat_plan') ? words.openMatPlan : words.failed}
        </p>
      )}
      <button
        type="submit"
        className="classes__button classes__button--primary"
        disabled={save.isPending || !day || !time}
      >
        {save.isPending ? words.working : words.submit}
      </button>
      <button type="button" className="classes__button" onClick={() => onClose(false)}>
        {words.close}
      </button>
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
  const navigate = useNavigate()
  const plan = useQuery(sessionPlanQuery(session.id))
  const [asking, setAsking] = useState<Asking>(null)

  const status = useMutation({
    mutationFn: (to: 'cancel' | 'reactivate') =>
      to === 'cancel' ? cancelSession(session.id) : reactivateSession(session.id),
    onSuccess: (updated) => {
      refreshSession(queryClient, updated)
      setAsking(null)
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteSession(session.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['sessions', 'detail', session.id] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
      // Credits given back, classes and time on the mat changed for whoever was marked.
      void queryClient.invalidateQueries({ queryKey: ['attendance'] })
      void queryClient.invalidateQueries({ queryKey: ['time'] })
      await navigate({ to: '/admin/clases' })
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
              <button
                type="button"
                className="classes__button class-actions__danger"
                disabled={working}
                onClick={() => status.mutate('cancel')}
              >
                {working ? words.working : words.cancelYes}
              </button>
            </>
          )}
          <button type="button" className="classes__button" onClick={() => ask(null)}>
            {words.back}
          </button>
        </div>
      ) : asking === 'delete' ? (
        <div className="classes__card class-actions__confirm" role="group" aria-label={words.delete}>
          <p className="classes__note">{words.deleteConfirm(session.present, (plan.data?.blocks.length ?? 0) > 0)}</p>
          {session.present > 0 && <p className="classes__note">{words.credits}</p>}
          <button
            type="button"
            className="classes__button class-actions__danger"
            disabled={working || plan.isPending}
            onClick={() => remove.mutate()}
          >
            {working ? words.working : words.deleteYes}
          </button>
          <button type="button" className="classes__button" onClick={() => ask(null)}>
            {words.back}
          </button>
        </div>
      ) : (
        <div className="class-actions__buttons">
          {session.cancelled_at ? (
            <button
              type="button"
              className="classes__button"
              disabled={working}
              onClick={() => {
                status.reset()
                status.mutate('reactivate')
              }}
            >
              {working ? words.working : words.reactivate}
            </button>
          ) : (
            <button type="button" className="classes__button" onClick={() => ask('cancel')}>
              {words.cancel}
            </button>
          )}
          <button type="button" className="classes__button class-actions__danger" onClick={() => ask('delete')}>
            {words.delete}
          </button>
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
