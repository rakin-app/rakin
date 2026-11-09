import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import {
  activeClassTypesQuery,
  startSession,
  todaySessionsQuery,
  type ClassSession,
  type ClassType,
} from '../api/sessions'
import { ChevronRightIcon } from '../components/icons'
import { PageHeader } from '../components/PageHeader'
import { clockTime, weekdayDay } from '../format'
import { t } from '../i18n/es'
import './Classes.css'

const copy = t.admin.classes

/**
 * "Clases": today's classes, and starting one. There is no timetable: the coach
 * starts a class as it begins, of one of the gym's class types, and lands on it to
 * write its topic and notes. Every staff role sees and starts them.
 *
 * Taking attendance on a class joins it with the roster (#44).
 */
export function Classes() {
  const today = useQuery(todaySessionsQuery())

  return (
    <div className="classes">
      <PageHeader title={copy.title} eyebrow={weekdayDay(new Date())} />
      <div className="classes__body">
        <StartSession />
        <section className="classes__section" aria-labelledby="classes-today">
          <div className="classes__section-head">
            <h2 id="classes-today" className="classes__section-title">
              {copy.today.title}
            </h2>
            {today.data && today.data.sessions.length > 0 && (
              <span className="classes__aside">{copy.today.count(today.data.sessions.length)}</span>
            )}
          </div>
          {today.isPending ? (
            <p className="classes__note">{copy.loading}</p>
          ) : today.isError ? (
            <Failed message={copy.today.error} retry={() => void today.refetch()} />
          ) : today.data.sessions.length === 0 ? (
            <p className="classes__note">{copy.today.empty}</p>
          ) : (
            <ul className="classes__list">
              {today.data.sessions.map((session) => (
                <SessionRow key={session.id} session={session} timeZone={today.data.timezone} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

function Failed({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="classes__error" role="alert">
      <p>{message}</p>
      <button type="button" className="classes__button" onClick={retry}>
        {copy.retry}
      </button>
    </div>
  )
}

function SessionRow({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  return (
    <li>
      <Link to="/admin/clases/$sessionId" params={{ sessionId: session.id }} className="classes__row">
        <span className="classes__row-text">
          <span className="classes__name">
            {copy.today.row(clockTime(session.starts_at, timeZone), session.class_type_name)}
          </span>
          <span className="classes__detail">{copy.today.detail(session.program_name, session.coach_name)}</span>
          <span className={session.topic ? 'classes__topic' : 'classes__topic classes__topic--none'}>
            {session.topic ?? copy.today.noTopic}
          </span>
        </span>
        <ChevronRightIcon />
      </Link>
    </li>
  )
}

/** "Iniciar clase": a class of the type chosen, now, by whoever starts it. */
function StartSession() {
  const classTypes = useQuery(activeClassTypesQuery())

  return (
    <section className="classes__card" aria-labelledby="classes-start">
      <h2 id="classes-start" className="classes__section-title">
        {copy.start.title}
      </h2>
      {classTypes.isPending ? (
        <p className="classes__note">{copy.loading}</p>
      ) : classTypes.isError ? (
        <Failed message={copy.start.error} retry={() => void classTypes.refetch()} />
      ) : classTypes.data.length === 0 ? (
        <p className="classes__note">{copy.start.noClassTypes}</p>
      ) : (
        <StartForm classTypes={classTypes.data} />
      )}
    </section>
  )
}

function StartForm({ classTypes }: { classTypes: ClassType[] }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const selectId = useId()
  const [classTypeId, setClassTypeId] = useState(classTypes[0]!.id)
  const start = useMutation({
    mutationFn: () => startSession({ class_type_id: classTypeId }),
    onSuccess: async (session) => {
      queryClient.setQueryData(['sessions', 'detail', session.id], session)
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
      await navigate({ to: '/admin/clases/$sessionId', params: { sessionId: session.id } })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    start.mutate()
  }

  return (
    <form className="classes__form" aria-label={copy.start.title} onSubmit={submit}>
      <label htmlFor={selectId} className="classes__label">
        {copy.start.classType}
      </label>
      <select
        id={selectId}
        className="classes__input"
        value={classTypeId}
        onChange={(e) => setClassTypeId(e.target.value)}
      >
        {programs(classTypes).map((types) => (
          <optgroup key={types[0]!.program_id} label={types[0]!.program_name}>
            {types.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {start.isError && (
        <p className="classes__error" role="alert">
          {copy.start.failed}
        </p>
      )}
      <button type="submit" className="classes__button classes__button--primary" disabled={start.isPending}>
        {start.isPending ? copy.start.working : copy.start.submit}
      </button>
    </form>
  )
}

/** Class types by program, in the order the API lists them (by program, then name). */
function programs(classTypes: ClassType[]): ClassType[][] {
  const groups = new Map<string, ClassType[]>()
  for (const type of classTypes) {
    groups.set(type.program_id, [...(groups.get(type.program_id) ?? []), type])
  }
  return [...groups.values()]
}
