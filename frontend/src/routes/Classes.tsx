import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useId, useState, type FormEvent } from 'react'
import { rosterQuery } from '../api/attendance'
import { gymTagHoursQuery } from '../api/classTags'
import {
  activeClassTypesQuery,
  daySessionsQuery,
  defaultDurationQuery,
  isClass,
  startSession,
  todaySessionsQuery,
  useGymTimeZone,
  useGymToday,
  type ClassSession,
  type ClassType,
} from '../api/sessions'
import { Button, buttonClass } from '../components/Button'
import { Banner, Card, listRowClass, ListRowContent, PlainList, SectionHeader, SectionTitle } from '../components/Card'
import { Input, Select } from '../components/Field'
import { EntradaCard } from '../components/EntradaCard'
import { ChevronRightIcon } from '../components/icons'
import { Grid, PageContainer, useWide } from '../components/Layout'
import { PageHeader, PageTitle } from '../components/PageHeader'
import { TagHoursCard } from '../components/TagHours'
import { clockTime, isoDay, shiftDay, shortDay, timeRange, toDate, weekdayDay, zonedInstant } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './Classes.css'
import { useSubmit } from '../api/submit'
import { TimerLink } from './SessionDetail'
import { Loading } from '../components/Loading'

const copy = t.admin.classes

/**
 * "Clases": the class on now or next, a day's classes, today's first, and creating one. The weekly schedule
 * (Ajustes, Horario) makes most of them ahead, and the arrows walk to the days before
 * and after; a coach may also create a class as it begins, of one of the gym's class
 * types, and lands on it to take its attendance and write its topic and notes. Every
 * staff role sees and creates them. A class that already happened is created on its own
 * day and time (#407): the form starts on the day shown, so walking back to a day and
 * creating one there registers it on that day, marked like any other.
 *
 * The class on now, else the next one today, comes first at every width, a tap from its
 * attendance and its timer (#358): a coach opens Clases at the mat. "Crear clase", an
 * occasional action, is a button that opens its form.
 *
 * From 1024px the page has two columns (#178): the class now, "Crear clase" and the day on the left,
 * and on the right the week the day is in, with the class picked in it: who came, of
 * those who usually do. A phone keeps the one column, and never asks for the week.
 *
 * Under the day, "Horas por etiqueta" (#243): the gym's classes held in a month or a
 * year, hours per tag.
 *
 * A gym with open access (#348) has "Entrada" under the class now: the door, where
 * people are checked in with no class. Its day's session is on the day's list, but is
 * never the class now, never created here and never flagged as unmarked.
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
            {day.data && isToday && <NowCard sessions={day.data.sessions} timeZone={day.data.timezone} />}
            <EntradaCard />
            <StartSession day={shown} today={gymToday} timeZone={timeZone} />
            <section className="classes__section" aria-labelledby="classes-day">
              <div className="classes__section-head">
                <SectionTitle id="classes-day">
                  {isToday ? copy.today.title : weekdayDay(toDate(shown))}
                </SectionTitle>
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
                <Loading className="classes__note">{copy.loading}</Loading>
              ) : day.isError ? (
                <Failed message={copy.today.error} retry={() => void day.refetch()} />
              ) : day.data.sessions.length === 0 ? (
                <p className="classes__note">{isToday ? copy.today.empty : copy.days.empty}</p>
              ) : (
                <PlainList className="classes__list">
                  {day.data.sessions.map((session) => (
                    <SessionRow key={session.id} session={session} timeZone={day.data.timezone} />
                  ))}
                </PlainList>
              )}
            </section>
            <TagHoursCard
              title={t.tagHours.gym}
              note={t.tagHours.gymNote}
              today={gymToday}
              query={gymTagHoursQuery}
            />
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
          <SectionTitle id="classes-week">
            {words.title}
          </SectionTitle>
          <span className="classes__aside">{words.range(shortDay(monday), shortDay(shiftDay(monday, 6)))}</span>
        </div>
        <PlainList ordered className="week">
          {days.map((d, i) => {
            const answer = answers[i]!
            const headingId = `week-${d}`
            return (
              <li key={d} className={d === today ? 'week__day week__day--today' : 'week__day'}>
                <h3 id={headingId} className="week__title">
                  {weekdayDay(toDate(d))}
                </h3>
                {answer.isPending ? (
                  <Loading className="classes__note">{copy.loading}</Loading>
                ) : answer.isError ? (
                  <Failed message={words.error} retry={() => void answer.refetch()} />
                ) : answer.data.sessions.length === 0 ? (
                  <p className="classes__note">{words.empty}</p>
                ) : (
                  <Card as="ul" flush className="week__list" aria-labelledby={headingId}>
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
                  </Card>
                )}
              </li>
            )
          })}
        </PlainList>
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
  if (isClass(session.class_type_kind) && new Date(session.starts_at) <= new Date()) return <span className="classes__flag">{copy.today.unmarked}</span>
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
        <PageTitle as="span" tight>
          {name}
        </PageTitle>
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
        <Loading className="classes__note">{copy.loading}</Loading>
      ) : roster.isError ? (
        <Failed message={words.rosterError} retry={() => void roster.refetch()} />
      ) : (
        <>
          <p className="attendance__count">{words.present(present.length, regulars)}</p>
          {present.length > 0 && (
            <PlainList className="week__present" aria-label={words.presentLabel}>
              {present.map((member) => (
                <li key={member.membership_id}>{member.name}</li>
              ))}
            </PlainList>
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

/** The class on now, else the next one today: neither cancelled, nor the open-access day.
 * Null once today's are over. */
export function nowOrNext(sessions: readonly ClassSession[], now: Date): { session: ClassSession; on: boolean } | null {
  const standing = sessions.filter((session) => session.cancelled_at === null && isClass(session.class_type_kind))
  const on = standing.find((session) => {
    const start = new Date(session.starts_at).getTime()
    // A class with no duration counts as on for its first hour.
    const end = start + (session.duration_minutes ?? 60) * 60_000
    return start <= now.getTime() && now.getTime() < end
  })
  if (on) return { session: on, on: true }
  const next = standing
    .filter((session) => new Date(session.starts_at) > now)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0]
  return next ? { session: next, on: false } : null
}

// How often the card looks at the clock again: a class starts or ends on the minute.
const NOW_TICK_MS = 60_000

/** The time, again every minute, so a page left open moves on with it. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), NOW_TICK_MS)
    return () => clearInterval(timer)
  }, [])
  return now
}

/** "Ahora" or "Siguiente": the class a coach at the mat came for, its attendance and timer.
 * Clases left open on the mat moves from one class to the next as the minutes pass. */
function NowCard({ sessions, timeZone }: { sessions: readonly ClassSession[]; timeZone: string }) {
  const words = copy.now
  const found = nowOrNext(sessions, useNow())
  if (!found) return null
  const { session, on } = found
  const name = copy.today.row(timeRange(session.starts_at, session.duration_minutes, timeZone), session.class_type_name)
  return (
    <Card className="classes__now" aria-labelledby="classes-now">
      <span className="classes__eyebrow">{on ? words.on : words.next}</span>
      <SectionTitle id="classes-now">
        {name}
      </SectionTitle>
      <span className="classes__detail">{copy.today.detail(session.program_name, session.coach_name)}</span>
      <div className="classes__now-actions">
        <Link
          to="/admin/clases/$sessionId"
          params={{ sessionId: session.id }}
          className={buttonClass({ variant: 'primary' })}
          aria-label={words.takeLabel(name)}
        >
          {words.take}
        </Link>
        <TimerLink session={session} />
      </div>
    </Card>
  )
}

function Failed({ message, retry }: { message: string; retry: () => void }) {
  return (
    <Banner tone="error" as="div">
      <p>{message}</p>
      <Button onClick={retry}>
        {copy.retry}
      </Button>
    </Banner>
  )
}

function SessionRow({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  // A class yet to start has no attendance to take: no flag until it has. A cancelled
  // one never has: it says so instead.
  const cancelled = session.cancelled_at !== null
  const unmarked =
    !cancelled && isClass(session.class_type_kind) && session.present === 0 && new Date(session.starts_at) <= new Date()
  const name = copy.today.row(timeRange(session.starts_at, session.duration_minutes, timeZone), session.class_type_name)
  const detail = copy.today.detail(session.program_name, session.coach_name)
  const topic = session.topic ?? copy.today.noTopic
  return (
    <li>
      <Link
        to="/admin/clases/$sessionId"
        params={{ sessionId: session.id }}
        className={cancelled ? 'classes__row classes__row--cancelled' : 'classes__row'}
        // From 1024px each line of a row may be cut short: in full here.
        title={[name, detail, topic].join(' · ')}
      >
        <span className="classes__row-text">
          <span className="classes__name">{name}</span>
          <span className="classes__detail">{detail}</span>
          <span className={session.topic ? 'classes__topic' : 'classes__topic classes__topic--none'}>{topic}</span>
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

/** "Crear clase": a class of the type chosen, now, taught by whoever creates it, for the
 * minutes given, prefilled with the type's default (#257). An occasional action, so a
 * button until it is wanted (#358). Its day and time start as the day shown and now; an
 * earlier day registers a class that already happened (#407), a later one is refused. */
type StartProps = { day: string; today: string; timeZone: string }

function StartSession(props: StartProps) {
  const [open, setOpen] = useState(false)
  const formId = useId()

  if (!open) {
    return (
      // No `aria-controls` while closed: the form it would name is not there yet.
      <Button className="classes__start" aria-expanded={false} onClick={() => setOpen(true)}>
        {copy.start.title}
      </Button>
    )
  }
  return (
    <Card id={formId} aria-labelledby="classes-start">
      <div className="classes__section-head">
        <SectionTitle id="classes-start">
          {copy.start.title}
        </SectionTitle>
        <Button variant="ghost" aria-expanded={true} aria-controls={formId} onClick={() => setOpen(false)}>
          {copy.start.close}
        </Button>
      </div>
      <StartBody {...props} />
    </Card>
  )
}

function StartBody(props: StartProps) {
  // Open access is checked in at Entrada, never created as a class.
  const classTypes = useQuery({
    ...activeClassTypesQuery(),
    select: (types) => types.filter((type) => isClass(type.kind)),
  })
  return classTypes.isPending ? (
    <Loading className="classes__note">{copy.loading}</Loading>
  ) : classTypes.isError ? (
    <Failed message={copy.start.error} retry={() => void classTypes.refetch()} />
  ) : classTypes.data.length === 0 ? (
    <p className="classes__note">{copy.start.noClassTypes}</p>
  ) : (
    <StartForm classTypes={classTypes.data} {...props} />
  )
}

function StartForm({ classTypes, ...props }: { classTypes: ClassType[] } & StartProps) {
  const { today, timeZone } = props
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const selectId = useId()
  const durationId = useId()
  const dayId = useId()
  const timeId = useId()
  const [classTypeId, setClassTypeId] = useState(classTypes[0]!.id)
  const [day, setDay] = useState(props.day > today ? today : props.day)
  // The time as the form opened; untouched on today, the class starts now.
  const [opened] = useState(() => clockTime(new Date().toISOString(), timeZone))
  const [time, setTime] = useState<string | null>(null)
  const future = day > today
  // Today at the time it opened is today's class as it always was: now.
  const startsAt = !day || (day === today && time === null) ? null : zonedInstant(day, time || opened, timeZone)
  // What was typed for the type chosen; another type starts again from its default.
  const [typed, setTyped] = useState<{ classTypeId: string; value: string } | null>(null)
  const fallback = useQuery(defaultDurationQuery(classTypeId, future || !day ? today : day))
  const duration =
    typed?.classTypeId === classTypeId ? typed.value : (fallback.data?.duration_minutes.toString() ?? '')
  const minutes = duration.trim() === '' ? null : Number(duration)
  const badDuration = minutes !== null && !(Number.isInteger(minutes) && minutes >= 1 && minutes <= 1440)
  const start = useSubmit({
    // Left empty, the class still gets the type's default.
    mutationFn: () =>
      startSession({
        class_type_id: classTypeId,
        ...(minutes === null ? {} : { duration_minutes: minutes }),
        ...(startsAt === null ? {} : { starts_at: startsAt }),
      }),
    onSuccess: async (session) => {
      queryClient.setQueryData(['sessions', 'detail', session.id], session)
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'day', isoDay(session.starts_at, timeZone)] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
      await navigate({ to: '/admin/clases/$sessionId', params: { sessionId: session.id } })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (badDuration || future || !day) return
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
      <label htmlFor={durationId} className="classes__label">
        {copy.start.duration}
      </label>
      <Input
        id={durationId}
        type="number"
        inputMode="numeric"
        min={1}
        max={1440}
        aria-invalid={badDuration}
        value={duration}
        onChange={(e) => setTyped({ classTypeId, value: e.target.value })}
      />
      <label htmlFor={dayId} className="classes__label">
        {copy.start.day}
      </label>
      <Input
        id={dayId}
        type="date"
        max={today}
        required
        aria-invalid={future}
        value={day}
        onChange={(e) => setDay(e.target.value)}
      />
      <label htmlFor={timeId} className="classes__label">
        {copy.start.time}
      </label>
      <Input
        id={timeId}
        type="time"
        required
        value={time ?? opened}
        onChange={(e) => setTime(e.target.value)}
      />
      {future ? (
        <Banner tone="error">
          {copy.start.futureDay}
        </Banner>
      ) : (
        day && day < today && <p className="classes__note">{copy.start.pastDay}</p>
      )}
      {badDuration && (
        <Banner tone="error">
          {copy.start.badDuration}
        </Banner>
      )}
      {start.isError && (
        <Banner tone="error">
          {copy.start.failed}
        </Banner>
      )}
      <Button
        type="submit"
        variant="primary"
        disabled={start.isPending || badDuration || future || !day}
        busy={start.isPending}
      >
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
