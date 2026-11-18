import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import { rosterQuery } from '../api/attendance'
import { gymTagHoursQuery } from '../api/classTags'
import {
  activeClassTypesQuery,
  daySessionsQuery,
  defaultDurationQuery,
  isClass,
  rangeSessionsQuery,
  startSession,
  todaySessionsQuery,
  useGymTimeZone,
  useGymToday,
  type ClassSession,
  type ClassType,
  type Holiday,
} from '../api/sessions'
import { Button, buttonClass } from '../components/Button'
import { Banner, Card, listRowClass, ListRowContent, PlainList, SectionHeader, SectionTitle } from '../components/Card'
import { SegmentedControl } from '../components/Chip'
import { Input, Select } from '../components/Field'
import { EntradaCard } from '../components/EntradaCard'
import { ChevronRightIcon } from '../components/icons'
import { Grid, PageContainer, useWide } from '../components/Layout'
import { PageHeader, PageTitle } from '../components/PageHeader'
import { TagHoursCard } from '../components/TagHours'
import { clockTime, isoDay, shiftDay, shiftMonth, shortDay, timeRange, toDate, weekdayDay, zonedInstant } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './Classes.css'
import { useSubmit } from '../api/submit'
import { TimerLink } from './SessionDetail'
import { Loading } from '../components/Loading'

const copy = t.admin.classes

// The day shown and the month view live in the URL (#426), so a reload, the back button
// and coming back from a class find them as they were.
export type ClassesSearch = {
  // The day shown, `2026-11-04`; today when absent.
  day?: string
  // The month view, its first day `2026-11-01`; absent is the day (and, wide, its week).
  month?: string
}

/** Whether `value` is a real ISO day: `2026-02-30` is not. */
function isDay(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && shiftDay(value, 0) === value
}

export function validateClassesSearch(search: Record<string, unknown>): ClassesSearch {
  const day = isDay(search.day) ? search.day : undefined
  const month = isDay(search.month) && search.month.endsWith('-01') ? search.month : undefined
  return { day, month }
}

const route = getRouteApi('/admin/clases')

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
 * those who usually do. A phone keeps the one column, and never asks for the week. The
 * class now is on the page once (#416): picked on the right, it is the card there, "Ahora"
 * or "Siguiente", and the left drops its own.
 *
 * The day and the month live in the URL (#426): "Ir a fecha" jumps to any day, the week
 * has arrows of its own, and "Mes" shows the month the day is in as a calendar, each day
 * with its classes and those unmarked or cancelled. A phone shows the month in place of
 * the day; from 1024px it takes the week's place, beside the day.
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
  const search = route.useSearch()
  const navigate = route.useNavigate()
  // The day shown, in the gym's timezone; absent from the URL follows today.
  const shown = search.day ?? gymToday
  const isToday = shown === gymToday
  const month = search.month ?? null
  const day = useQuery(dayQuery(shown, gymToday))
  // Each a step back can undo: pushed, never replaced.
  const show = (next: ClassesSearch) => void navigate({ search: next })
  // To the day `to`, today written as no day; `keepMonth` stays in the month view.
  const go = (to: string, keepMonth = true) =>
    show({ day: to === gymToday ? undefined : to, month: keepMonth ? search.month : undefined })
  const home = () => show({})
  const setView = (view: 'day' | 'month') =>
    show({ day: search.day, month: view === 'month' ? `${shown.slice(0, 7)}-01` : undefined })
  // A phone shows the month in place of the day; wide, the day stays beside it.
  const pick = (to: string) => go(to, wide)
  const week = useWeek(wide && month === null ? shown : null, gymToday, timeZone)
  const now = useNow()
  const found = day.data && isToday ? nowOrNext(day.data.sessions, now) : null
  // Picked on the right, the class now is the card there.
  const nowPicked = found !== null && week.selected?.id === found.session.id

  return (
    <div className="classes">
      <PageContainer className="classes__page">
        <PageHeader title={copy.title} eyebrow={weekdayDay(toDate(gymToday))} />
        <Grid>
          <div className="classes__column">
            {found && !nowPicked && <NowCard found={found} timeZone={day.data!.timezone} />}
            <EntradaCard />
            <StartSession day={shown} today={gymToday} timeZone={timeZone} />
            {!wide && month !== null ? (
              <Month
                month={month}
                shown={shown}
                today={gymToday}
                timeZone={timeZone}
                showMonth={(to) => show({ day: search.day, month: to })}
                pick={pick}
                home={home}
                view={<ViewSwitch value="month" wide={false} onChange={setView} />}
                jump={<JumpTo day={shown} onJump={(to) => go(to, false)} />}
              />
            ) : (
            <section className="classes__section" aria-labelledby="classes-day">
              <div className="classes__section-head">
                <SectionTitle id="classes-day">
                  {withHoliday(isToday ? copy.today.title : weekdayDay(toDate(shown)), day.data?.holidays?.[0])}
                </SectionTitle>
                {day.data && day.data.sessions.length > 0 && (
                  <span className="classes__aside">{copy.today.count(day.data.sessions.length)}</span>
                )}
                {!wide && <ViewSwitch value="day" wide={false} onChange={setView} />}
              </div>
              <nav className="classes__days" aria-label={copy.days.label}>
                <Button onClick={() => go(shiftDay(shown, -1))}>{copy.days.previous}</Button>
                {(!isToday || month !== null) && <Button onClick={home}>{copy.days.today}</Button>}
                <Button onClick={() => go(shiftDay(shown, 1))}>{copy.days.next}</Button>
              </nav>
              <JumpTo day={shown} onJump={(to) => go(to, wide)} />
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
            )}
            <TagHoursCard
              title={t.tagHours.gym}
              note={t.tagHours.gymNote}
              today={gymToday}
              query={gymTagHoursQuery}
            />
          </div>
          {wide &&
            (month === null ? (
              <Week
                week={week}
                today={gymToday}
                timeZone={timeZone}
                now={nowPicked ? found : null}
                shift={(days) => go(shiftDay(shown, days))}
                view={<ViewSwitch value="day" wide onChange={setView} />}
              />
            ) : (
              <div className="classes__column">
                <Month
                  month={month}
                  shown={shown}
                  today={gymToday}
                  timeZone={timeZone}
                  showMonth={(to) => show({ day: search.day, month: to })}
                  pick={pick}
                  home={home}
                  view={<ViewSwitch value="month" wide onChange={setView} />}
                />
              </div>
            ))}
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

type NowOrNext = { session: ClassSession; on: boolean }

/**
 * The seven days of the week `day` is in, Monday first, as the schedule made them, in one
 * request (#426), and the class picked in it, today's last begun one until another is.
 * No `day`, no week: a phone never asks for it, nor a desktop showing the month.
 */
function useWeek(day: string | null, today: string, timeZone: string) {
  const monday = mondayOf(day ?? today)
  const days = Array.from({ length: 7 }, (_, i) => shiftDay(monday, i))
  const range = useQuery({ ...rangeSessionsQuery(monday, days[6]!), enabled: day !== null })
  const [picked, setPicked] = useState<string | null>(null)
  const all = range.data?.sessions ?? []
  const zone = range.data?.timezone ?? timeZone
  const onDay = (d: string) => all.filter((session) => isoDay(session.starts_at, zone) === d)
  const holidayOn = (d: string) => range.data?.holidays.find((holiday) => holiday.date === d)
  const now = new Date()
  const selected =
    all.find((session) => session.id === picked) ??
    all.filter((session) => isoDay(session.starts_at, zone) === today && new Date(session.starts_at) <= now).at(-1)
  return { monday, days, range, onDay, holidayOn, selected, setPicked }
}

/** "Semana": the week `useWeek` read, and the class picked in it; `now` when that is the class now. */
function Week({
  week,
  today,
  timeZone,
  now,
  shift,
  view,
}: {
  week: ReturnType<typeof useWeek>
  today: string
  timeZone: string
  now: NowOrNext | null
  // A week back (-7) or on (7): the day moves with it.
  shift: (days: number) => void
  view: ReactNode
}) {
  const words = copy.week
  const { days, range, onDay, holidayOn, selected, setPicked, monday } = week

  return (
    <div className="classes__column">
      {selected ? (
        <Picked key={selected.id} session={selected} timeZone={timeZone} now={now} />
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
          {view}
        </div>
        <nav className="classes__days" aria-label={words.label}>
          <Button onClick={() => shift(-7)}>{words.previous}</Button>
          <Button onClick={() => shift(7)}>{words.next}</Button>
        </nav>
        {range.isPending ? (
          <Loading className="classes__note">{copy.loading}</Loading>
        ) : range.isError ? (
          <Failed message={words.error} retry={() => void range.refetch()} />
        ) : (
        <PlainList ordered className="week">
          {days.map((d) => {
            const sessions = onDay(d)
            const headingId = `week-${d}`
            return (
              <li key={d} className={d === today ? 'week__day week__day--today' : 'week__day'}>
                <h3 id={headingId} className="week__title">
                  {withHoliday(weekdayDay(toDate(d)), holidayOn(d))}
                </h3>
                {sessions.length === 0 ? (
                  <p className="classes__note">{words.empty}</p>
                ) : (
                  <Card as="ul" flush className="week__list" aria-labelledby={headingId}>
                    {sessions.map((session) => (
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
        )}
      </section>
    </div>
  )
}

/** "Día" (a phone) or "Semana" (from 1024px), or "Mes". */
function ViewSwitch({ value, wide, onChange }: { value: 'day' | 'month'; wide: boolean; onChange: (view: 'day' | 'month') => void }) {
  const words = copy.view
  return (
    <SegmentedControl
      label={words.label}
      options={[
        { value: 'day', label: wide ? words.week : words.day },
        { value: 'month', label: words.month },
      ]}
      value={value}
      onChange={onChange}
    />
  )
}

/** A day's title, and the public holiday it is (#426): `lun 8 dic · La Inmaculada Concepción`. */
function withHoliday(title: string, holiday: Holiday | undefined): string {
  return holiday ? copy.days.holiday(title, holiday.name) : title
}

/** "Ir a fecha": straight to any day, past or to come. */
function JumpTo({ day, onJump }: { day: string; onJump: (day: string) => void }) {
  const id = useId()
  return (
    <div className="classes__jump">
      <label htmlFor={id} className="classes__label">
        {copy.days.jump}
      </label>
      <Input
        id={id}
        type="date"
        value={day}
        onChange={(event) => {
          if (isDay(event.target.value)) onJump(event.target.value)
        }}
      />
    </div>
  )
}

// A month's calendar is always six weeks, so it never changes height from month to month.
const MONTH_DAYS = 42

/** What a day of the month shows: its classes (never the door's day, nor a cancelled one),
 * those no one is marked at, and those cancelled. */
export function dayCounts(sessions: readonly ClassSession[], now: Date) {
  return {
    classes: sessions.filter((session) => session.cancelled_at === null && isClass(session.class_type_kind)).length,
    unmarked: sessions.filter((session) => isUnmarked(session, now)).length,
    cancelled: sessions.filter((session) => session.cancelled_at !== null).length,
  }
}

/** "Mes": the month as a calendar, Monday first, each day a tap to it (#426). */
function Month({
  month,
  shown,
  today,
  timeZone,
  showMonth,
  pick,
  home,
  view,
  jump,
}: {
  month: string
  shown: string
  today: string
  timeZone: string
  showMonth: (month: string) => void
  pick: (day: string) => void
  home: () => void
  view: ReactNode
  jump?: ReactNode
}) {
  const words = copy.month
  const first = mondayOf(month)
  const days = Array.from({ length: MONTH_DAYS }, (_, i) => shiftDay(first, i))
  const range = useQuery(rangeSessionsQuery(first, days[MONTH_DAYS - 1]!))
  const zone = range.data?.timezone ?? timeZone
  const now = new Date()
  const byDay = new Map<string, ClassSession[]>()
  for (const session of range.data?.sessions ?? []) {
    const d = isoDay(session.starts_at, zone)
    byDay.set(d, [...(byDay.get(d) ?? []), session])
  }
  const holidays = new Map((range.data?.holidays ?? []).map((holiday) => [holiday.date, holiday.name]))
  const weeks = Array.from({ length: MONTH_DAYS / 7 }, (_, i) => days.slice(i * 7, i * 7 + 7))
  const atHome = month === `${today.slice(0, 7)}-01` && shown === today

  return (
    <section className="classes__section" aria-labelledby="classes-month">
      <div className="classes__section-head">
        <SectionTitle id="classes-month">{words.title(month)}</SectionTitle>
        {view}
      </div>
      <nav className="classes__days" aria-label={words.label}>
        <Button onClick={() => showMonth(shiftMonth(month, -1))}>{words.previous}</Button>
        {!atHome && <Button onClick={home}>{copy.days.today}</Button>}
        <Button onClick={() => showMonth(shiftMonth(month, 1))}>{words.next}</Button>
      </nav>
      {jump}
      {range.isPending ? (
        <Loading className="classes__note">{copy.loading}</Loading>
      ) : range.isError ? (
        <Failed message={words.error} retry={() => void range.refetch()} />
      ) : (
        <table className="month">
          <thead>
            <tr>
              {words.weekdays.map((initial, i) => (
                <th key={initial + i} scope="col" className="month__weekday">
                  <abbr title={words.weekdayNames[i]}>{initial}</abbr>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeks.map((week) => (
              <tr key={week[0]}>
                {week.map((d, i) => {
                  const counts = dayCounts(byDay.get(d) ?? [], now)
                  const outside = d.slice(0, 7) !== month.slice(0, 7)
                  // A public holiday's number is red, its name in the title and the day's name only (#457).
                  const holiday = holidays.get(d) ?? null
                  return (
                    <td key={d} className="month__cell">
                      <button
                        type="button"
                        className={['month__day', outside && 'month__day--outside', holiday !== null && 'month__day--holiday']
                          .filter(Boolean)
                          .join(' ')}
                        aria-label={words.cell(
                          words.weekdayNames[i]!,
                          d,
                          counts.classes,
                          counts.unmarked,
                          counts.cancelled,
                          holiday,
                        )}
                        title={holiday ?? undefined}
                        aria-current={d === today ? 'date' : undefined}
                        aria-pressed={d === shown}
                        onClick={() => pick(d)}
                      >
                        <span className="month__number">{Number(d.slice(8, 10))}</span>
                        <span className="month__marks">
                          {counts.classes > 0 && (
                            <span className="month__count">
                              <span className="month__short">{counts.classes}</span>
                              <span className="month__long">{words.classes(counts.classes)}</span>
                            </span>
                          )}
                          {counts.unmarked > 0 && (
                            <span className="month__unmarked">
                              <span className="month__dot" />
                              <span className="month__narrow">{counts.unmarked}</span>
                              <span className="month__long">{words.unmarked(counts.unmarked)}</span>
                            </span>
                          )}
                          {counts.cancelled > 0 && (
                            <span className="month__cancelled">
                              <span className="month__short">{counts.cancelled}</span>
                              <span className="month__long">{words.cancelled(counts.cancelled)}</span>
                            </span>
                          )}
                        </span>
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/** How many came, or why none did. */
function WeekCount({ session }: { session: ClassSession }) {
  if (session.cancelled_at !== null) {
    return <span className="classes__flag classes__flag--cancelled">{copy.today.cancelled}</span>
  }
  if (session.present > 0) return <span className="classes__aside">{copy.today.present(session.present)}</span>
  if (isUnmarked(session, new Date())) return <span className="classes__flag">{copy.today.unmarked}</span>
  return null
}

/** A class that has begun with no one marked at it. A class yet to start has no attendance
 * to take, a cancelled one never has, and the door's day (#348) is no class. */
export function isUnmarked(session: ClassSession, now: Date): boolean {
  return (
    session.cancelled_at === null &&
    isClass(session.class_type_kind) &&
    session.present === 0 &&
    new Date(session.starts_at) <= now
  )
}

/** The class picked in the week: what it is, who came of those who usually do, and a tap to its attendance.
 * The class now (`now`) says so, as the left column's card would, with its timer. */
function Picked({ session, timeZone, now }: { session: ClassSession; timeZone: string; now: NowOrNext | null }) {
  const words = copy.week
  const cancelled = session.cancelled_at !== null
  const begun = new Date(session.starts_at) <= new Date()
  const roster = useQuery({ ...rosterQuery(session.id), enabled: !cancelled && begun })
  const present = roster.data?.members.filter((m) => m.present) ?? []
  const regulars = roster.data?.members.filter((m) => m.regular).length ?? 0
  const name = copy.today.row(timeRange(session.starts_at, session.duration_minutes, timeZone), session.class_type_name)

  return (
    <Card aria-label={words.picked}>
      {now && <span className="classes__eyebrow">{now.on ? copy.now.on : copy.now.next}</span>}
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
      {now ? (
        <div className="classes__now-actions">
          <Link
            to="/admin/clases/$sessionId"
            params={{ sessionId: session.id }}
            className={buttonClass({ variant: 'primary' })}
            aria-label={copy.now.takeLabel(name)}
          >
            {copy.now.take}
          </Link>
          <TimerLink session={session} />
        </div>
      ) : (
        <Link
          to="/admin/clases/$sessionId"
          params={{ sessionId: session.id }}
          className={buttonClass()}
        >
          {cancelled ? words.open : words.take}
        </Link>
      )}
    </Card>
  )
}

/** The class on now, else the next one today: neither cancelled, nor the open-access day.
 * Null once today's are over. */
export function nowOrNext(sessions: readonly ClassSession[], now: Date): NowOrNext | null {
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
function NowCard({ found, timeZone }: { found: NowOrNext; timeZone: string }) {
  const words = copy.now
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
  // A cancelled class says so instead of any flag.
  const cancelled = session.cancelled_at !== null
  const unmarked = isUnmarked(session, new Date())
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
  const timeNoteId = useId()
  const [classTypeId, setClassTypeId] = useState(classTypes[0]!.id)
  const [day, setDay] = useState(props.day > today ? today : props.day)
  // The time as the form opened; untouched on today, the class starts now.
  const [opened] = useState(() => clockTime(new Date().toISOString(), timeZone))
  const [time, setTime] = useState<string | null>(null)
  const future = day > today
  const past = day !== '' && day < today
  // An earlier day has no "now": its time is chosen, never the clock's by accident.
  const shownTime = time ?? (past ? '' : opened)
  const noTime = shownTime === ''
  // Today at the time it opened is today's class as it always was: now.
  const startsAt = !day || noTime || (day === today && time === null) ? null : zonedInstant(day, shownTime, timeZone)
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
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'range'] })
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
      await navigate({ to: '/admin/clases/$sessionId', params: { sessionId: session.id } })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (badDuration || future || !day || noTime) return
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
        aria-describedby={noTime ? timeNoteId : undefined}
        value={shownTime}
        onChange={(e) => setTime(e.target.value)}
      />
      {noTime && !future && (
        <p id={timeNoteId} className="classes__note">
          {copy.start.chooseTime}
        </p>
      )}
      {future ? (
        <Banner tone="error">
          {copy.start.futureDay}
        </Banner>
      ) : (
        past && <p className="classes__note">{copy.start.pastDay}</p>
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
        disabled={start.isPending || badDuration || future || !day || noTime}
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
