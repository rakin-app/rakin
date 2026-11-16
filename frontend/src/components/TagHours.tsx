import { useQuery, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'
import type { Stretch, TagHours as Hours } from '../api/classTags'
import { useGymTimeZone } from '../api/sessions'
import { isoDay, shortDay } from '../format'
import { t } from '../i18n/es'
import { BarError, BarList, BarNote } from './BarList'
import { Button } from './Button'
import { Card, PlainList, Section, SectionHeader } from './Card'
import { SegmentedControl } from './Chip'
import { ChevronLeftIcon, ChevronRightIcon } from './icons'
import './TagHours.css'
import { Loading } from './Loading'

const copy = t.tagHours

type Period = 'month' | 'year'

/**
 * "Horas por etiqueta" for a month or a year the reader walks to (#243): Clases' for
 * the gym's classes held, the ficha's for a member's attended ones. `today` is the
 * gym's, `2026-11-11`, where it opens. `headed` puts the title over the card, as the
 * ficha heads each of its sections (#360).
 */
export function TagHoursCard<Key extends QueryKey>({
  title,
  note,
  headed = false,
  today,
  query,
}: {
  title: string
  note?: string
  headed?: boolean
  today: string
  query: (stretch: Stretch) => UseQueryOptions<Hours, Error, Hours, Key>
}) {
  const titleId = useId()
  const [period, setPeriod] = useState<Period>('month')
  const [year, setYear] = useState(Number(today.slice(0, 4)))
  const [month, setMonth] = useState(Number(today.slice(5, 7)))
  // Back to today's month when it changes: the device's is today until the gym's
  // timezone is in, a month on in UTC on the gym's month's last evening (#330).
  const [opened, setOpened] = useState(today.slice(0, 7))
  if (opened !== today.slice(0, 7)) {
    setOpened(today.slice(0, 7))
    setYear(Number(today.slice(0, 4)))
    setMonth(Number(today.slice(5, 7)))
  }
  const stretch: Stretch = { year, month: period === 'month' ? month : null }
  const hours = useQuery(query(stretch))

  const step = (by: -1 | 1) => {
    if (period === 'year') {
      setYear(year + by)
      return
    }
    const next = month + by
    setYear(year + Math.floor((next - 1) / 12))
    setMonth(((next - 1 + 12) % 12) + 1)
  }
  const what = period === 'month' ? copy.month : copy.year

  const control = (
    <SegmentedControl
      label={copy.periods}
      options={[
        { value: 'month', label: copy.month },
        { value: 'year', label: copy.year },
      ]}
      value={period}
      onChange={setPeriod}
    />
  )
  const body = (
    <>
      <div className="tag-hours__stretch">
        <Button variant="ghost" icon aria-label={copy.previous(what)} onClick={() => step(-1)}>
          <ChevronLeftIcon />
        </Button>
        <span className="tag-hours__stretch-label" aria-live="polite">
          {copy.stretch(stretch.year, stretch.month)}
        </span>
        <Button variant="ghost" icon aria-label={copy.next(what)} onClick={() => step(1)}>
          <ChevronRightIcon />
        </Button>
      </div>
      {hours.isError ? (
        <BarError>{copy.error}</BarError>
      ) : hours.data ? (
        <>
          <TagHoursRows hours={hours.data} />
          <NoDuration hours={hours.data} linked />
        </>
      ) : (
        <Loading className="bar-note">{copy.loading}</Loading>
      )}
      {note && <BarNote>{note}</BarNote>}
    </>
  )

  if (headed) {
    return (
      <Section id={titleId} title={title} trailing={control}>
        <Card as="div">{body}</Card>
      </Section>
    )
  }
  return (
    <Card aria-labelledby={titleId}>
      <SectionHeader id={titleId} title={title} trailing={control} />
      {body}
    </Card>
  )
}

/** The student page's: this month or this year, as `/api/me/classes` gives them. */
export function TagHoursNow({ title, month, year }: { title: string; month: Hours; year: Hours }) {
  const titleId = useId()
  const [period, setPeriod] = useState<Period>('month')
  return (
    <Card aria-labelledby={titleId}>
      <SectionHeader
        id={titleId}
        title={title}
        trailing={
          <SegmentedControl
          label={copy.periods}
          options={[
            { value: 'month', label: copy.thisMonth },
            { value: 'year', label: copy.thisYear },
          ]}
          value={period}
          onChange={setPeriod}
          />
        }
      />
      <TagHoursRows hours={period === 'month' ? month : year} />
      <NoDuration hours={period === 'month' ? month : year} />
    </Card>
  )
}

/** The classes counted that have no duration, so add no minutes (#257): how many, and
 * on staff's cards each of the latest, to go set its duration. */
function NoDuration({ hours, linked = false }: { hours: Hours; linked?: boolean }) {
  if (hours.no_duration_classes === 0) return null
  return (
    <div className="tag-hours__missing">
      <BarNote>{copy.noDuration(hours.no_duration_classes)}</BarNote>
      {linked && <NoDurationLinks hours={hours} />}
    </div>
  )
}

/** Staff's only: the gym's timezone is read off its day of classes. */
function NoDurationLinks({ hours }: { hours: Hours }) {
  const timeZone = useGymTimeZone()
  return (
    <PlainList className="tag-hours__missing-list">
      {hours.no_duration.map((each) => (
        <li key={each.session_id}>
          <Link to="/admin/clases/$sessionId" params={{ sessionId: each.session_id }}>
            {copy.noDurationLink(shortDay(isoDay(each.starts_at, timeZone)), each.class_type_name)}
          </Link>
        </li>
      ))}
    </PlainList>
  )
}

/** Each tag as a bar whose text carries the figure, most hours first. */
function TagHoursRows({ hours }: { hours: Hours }) {
  if (hours.tags.length === 0) return <BarNote>{copy.empty}</BarNote>
  return (
    <>
      <BarList
        bars={hours.tags.map((row) => ({
          key: row.tag_id,
          label: (
            <>
              {row.name}
              {row.archived && <span className="bar-note">{copy.archivedSuffix}</span>}
            </>
          ),
          figure: copy.figure(row.minutes, row.classes),
          value: row.minutes,
          muted: row.archived,
        }))}
      />
      {hours.untagged_minutes > 0 && <BarNote>{copy.untagged(copy.hours(hours.untagged_minutes))}</BarNote>}
    </>
  )
}
