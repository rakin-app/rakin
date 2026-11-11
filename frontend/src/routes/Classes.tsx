import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { rosterQuery } from '../api/attendance'
import {
  activeClassTypesQuery,
  daySessionsQuery,
  startSession,
  todaySessionsQuery,
  useGymTimeZone,
  useGymToday,
  type ClassSession,
  type ClassType,
} from '../api/sessions'
import { Button, buttonClass } from '../components/Button'
import { Card, ListRowContent, listRowClass, SectionHeader } from '../components/Card'
import { Select } from '../components/Field'
import { ChevronRightIcon } from '../components/icons'
import { Grid, PageContainer, useWide } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { clockTime, isoDay, shiftDay, shortDay, timeRange, toDate, weekdayDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './Classes.css'
import { useSubmit } from '../api/submit'

const copy = t.admin.classes

/**
 * "Clases": a day's classes, today's first, and creating one. The weekly schedule
 * (Ajustes, Horario) makes most of them ahead, and the arrows walk to the days before
 * and after; a coach may also create a class as it begins, of one of the gym's class
 * types, and lands on it to take its attendance and write its topic and notes. Every
 * staff role sees and creates them.
 *
 * From 1024px the page has two columns (#178): "Crear clase" and the day on the left,
 * and on the right the week the day is in, with the class picked in it: who came, of
 * those who usually do. A phone keeps the one column, and never asks for the week.
 */
export function Classes() {
  usePageTitle(copy.title)
  const gymToday = useGymToday()
  const timeZone = useGymTimeZone()
  const wide = useWide()
  // The day shown, in the gym's timezone; null follows today.
  const [chosen, setChosen] = useState<string | null>(null)
  const shown = chosen ?? gymToday
  const isToday = shown === gymToday
  const day = useQuery(dayQuery(shown, gymToday))
  const go = (to: string) => setChosen(to === gymToday ? null : to)

  return (
    <div className="classes">
      <PageContainer className="classes__page">
        <PageHeader title={copy.title} eyebrow={weekdayDay(toDate(gymToday))} />
        <Grid>
          <div className="classes__column">
            <StartSession />
            <section className="classes__section" aria-labelledby="classes-day">
              <div className="classes__section-head">
                <h2 id="classes-day" className="classes__section-title">
                  {isToday ? copy.today.title : weekdayDay(toDate(shown))}
                </h2>
                {day.data && day.data.sessions.length > 0 && (
                  <span className="classes__aside">{copy.today.count(day.data.sessions.length)}</span>
                )}
              </div>
              <nav className="classes__days" aria-label={copy.days.label}>
                <Button onClick={() => go(shiftDay(shown, -1))}>{copy.days.previous}</Button>
                {!isToday && <Button onClick={() => go(gymToday)}>{copy.days.today}</Button>}
                <Button onClick={() => go(shiftDay(shown, 1))}>{copy.days.next}</Button>
              </nav>
              {day.isPending ? (
                <p className="classes__note">{copy.loading}</p>
              ) : day.isError ? (
                <Failed message={copy.today.error} retry={() => void day.refetch()} />
              ) : day.data.sessions.length === 0 ? (
                <p className="classes__note">{isToday ? copy.today.empty : copy.days.empty}</p>
              ) : (
                <ul className="classes__list">
                  {day.data.sessions.map((session) => (
                    <SessionRow key={session.id} session={session} timeZone={day.data.timezone} />
                  ))}
                </ul>
              )}
            </section>
          </div>
          {wide && <Week day={shown} today={gymToday} timeZone={timeZone} />}
        </Grid>
      </PageContainer>
    </div>
  )
}

/** A day's classes; today's under the key every change to a class refreshes. */
function dayQuery(day: string, today: string) {
  return day === today ? todaySessionsQuery() : daySessionsQuery(day)
}

/** The Monday of the week `day` is in, `2026-11-09` for `2026-11-10`. */
export function mondayOf(day: string): string {
  return shiftDay(day, -((toDate(day).getDay() + 6) % 7))
}

/**
 * "Semana": the seven days of the week `day` is in, Monday first, as the schedule made
 * them, and the class picked in it, today's last begun one until another is.
 */
function Week({ day, today, timeZone }: { day: string; today: string; timeZone: string }) {
  const words = copy.week
  const monday = mondayOf(day)
  const days = Array.from({ length: 7 }, (_, i) => shiftDay(monday, i))
  const answers = useQueries({ queries: days.map((d) => dayQuery(d, today)) })
  const [picked, setPicked] = useState<string | null>(null)
  const all = answers.flatMap((answer) => answer.data?.sessions ?? [])
  const now = new Date()
  const selected =
    all.find((session) => session.id === picked) ??
    all.filter((session) => isoDay(session.starts_at, timeZone) === today && new Date(session.starts_at) <= now).at(-1)

  return (
    <div className="classes__column">
      {selected ? (
        <Picked key={selected.id} session={selected} timeZone={timeZone} />
      ) : (
        <Card aria-label={words.picked}>
          <p className="classes__note">{words.pick}</p>
        </Card>
      )}
      <section className="classes__section" aria-labelledby="classes-week">
        <div className="classes__section-head">
          <h2 id="classes-week" className="classes__section-title">
            {words.title}
          </h2>
          <span className="classes__aside">{words.range(shortDay(monday), shortDay(shiftDay(monday, 6)))}</span>
        </div>
        <ol className="week">
          {days.map((d, i) => {
            const answer = answers[i]!
            const headingId = `week-${d}`
            return (
              <li key={d} className={d === today ? 'week__day week__day--today' : 'week__day'}>
                <h3 id={headingId} className="week__title">
                  {weekdayDay(toDate(d))}
                </h3>
                {answer.isPending ? (
                  <p className="classes__note">{copy.loading}</p>
                ) : answer.isError ? (
                  <Failed message={words.error} retry={() => void answer.refetch()} />
                ) : answer.data.sessions.length === 0 ? (
                  <p className="classes__note">{words.empty}</p>
                ) : (
                  <ul className="week__list" aria-labelledby={headingId}>
                    {answer.data.sessions.map((session) => (
                      <li key={session.id}>
                        <button
                          type="button"
                          className={listRowClass(true, 'week__class')}
                          aria-pressed={session.id === selected?.id}
                          onClick={() => setPicked(session.id)}
                        >
                          <ListRowContent
                            title={copy.today.row(clockTime(session.starts_at, timeZone), session.class_type_name)}
                            detail={session.coach_name}
                            trailing={<WeekCount session={session} />}
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ol>
      </section>
    </div>
  )
}

/** How many came, or why none did. */
function WeekCount({ session }: { session: ClassSession }) {
  if (session.cancelled_at !== null) {
    return <span className="classes__flag classes__flag--cancelled">{copy.today.cancelled}</span>
  }
  if (session.present > 0) return <span className="classes__aside">{copy.today.present(session.present)}</span>
  if (new Date(session.starts_at) <= new Date()) return <span className="classes__flag">{copy.today.unmarked}</span>
  return null
}

/** The class picked in the week: what it is, who came of those who usually do, and a tap to its attendance. */
function Picked({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  const words = copy.week
  const cancelled = session.cancelled_at !== null
  const begun = new Date(session.starts_at) <= new Date()
  const roster = useQuery({ ...rosterQuery(session.id), enabled: !cancelled && begun })
  const present = roster.data?.members.filter((m) => m.present) ?? []
  const regulars = roster.data?.members.filter((m) => m.regular).length ?? 0
  const name = copy.today.row(timeRange(session.starts_at, session.duration_minutes, timeZone), session.class_type_name)

  return (
    <Card aria-label={words.picked}>
      <SectionHeader title={weekdayDay(toDate(isoDay(session.starts_at, timeZone)))} trailing={session.program_name} />
      <div className="classes__row-text">
        <span className="classes__title">{name}</span>
        <span className="classes__detail">{session.coach_name}</span>
        <span className={session.topic ? 'classes__topic' : 'classes__topic classes__topic--none'}>
          {session.topic ?? copy.today.noTopic}
        </span>
      </div>
      {cancelled ? (
        <p className="classes__note">{words.cancelled}</p>
      ) : !begun ? (
        <p className="classes__note">{words.upcoming}</p>
      ) : roster.isPending ? (
        <p className="classes__note">{copy.loading}</p>
      ) : roster.isError ? (
        <Failed message={words.rosterError} retry={() => void roster.refetch()} />
      ) : (
        <>
          <p className="attendance__count">{words.present(present.length, regulars)}</p>
          {present.length > 0 && (
            <ul className="week__present" aria-label={words.presentLabel}>
              {present.map((member) => (
                <li key={member.membership_id}>{member.name}</li>
              ))}
            </ul>
          )}
        </>
      )}
      <Link
        to="/admin/clases/$sessionId"
        params={{ sessionId: session.id }}
        className={buttonClass()}
      >
        {cancelled ? words.open : words.take}
      </Link>
    </Card>
  )
}

function Failed({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="classes__error" role="alert">
      <p>{message}</p>
      <Button onClick={retry}>
        {copy.retry}
      </Button>
    </div>
  )
}

function SessionRow({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  // A class yet to start has no attendance to take: no flag until it has. A cancelled
  // one never has: it says so instead.
  const cancelled = session.cancelled_at !== null
  const unmarked = !cancelled && session.present === 0 && new Date(session.starts_at) <= new Date()
  return (
    <li>
      <Link
        to="/admin/clases/$sessionId"
        params={{ sessionId: session.id }}
        className={cancelled ? 'classes__row classes__row--cancelled' : 'classes__row'}
      >
        <span className="classes__row-text">
          <span className="classes__name">
            {copy.today.row(timeRange(session.starts_at, session.duration_minutes, timeZone), session.class_type_name)}
          </span>
          <span className="classes__detail">{copy.today.detail(session.program_name, session.coach_name)}</span>
          <span className={session.topic ? 'classes__topic' : 'classes__topic classes__topic--none'}>
            {session.topic ?? copy.today.noTopic}
          </span>
        </span>
        {!cancelled && session.present > 0 && (
          <span className="classes__count">{copy.today.present(session.present)}</span>
        )}
        {unmarked && <span className="classes__flag">{copy.today.unmarked}</span>}
        {cancelled && <span className="classes__flag classes__flag--cancelled">{copy.today.cancelled}</span>}
        <ChevronRightIcon />
      </Link>
    </li>
  )
}

/** "Crear clase": a class of the type chosen, now, taught by whoever creates it. */
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
  const start = useSubmit({
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
      <Select
        id={selectId}
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
      </Select>
      {start.isError && (
        <p className="classes__error" role="alert">
          {copy.start.failed}
        </p>
      )}
      <Button type="submit" variant="primary" disabled={start.isPending} busy={start.isPending}>
        {start.isPending ? copy.start.working : copy.start.submit}
      </Button>
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
