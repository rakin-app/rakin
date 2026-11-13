import { useQuery, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'
import type { Stretch, TagHours as Hours } from '../api/classTags'
import { useGymTimeZone } from '../api/sessions'
import { isoDay, shortDay } from '../format'
import { t } from '../i18n/es'
import { Button } from './Button'
import { SegmentedControl } from './Chip'
import { ChevronLeftIcon, ChevronRightIcon } from './icons'
import './TagHours.css'

const copy = t.tagHours

type Period = 'month' | 'year'

/**
 * "Horas por etiqueta" for a month or a year the reader walks to (#243): Clases' for
 * the gym's classes held, the ficha's for a member's attended ones. `today` is the
 * gym's, `2026-11-11`, where it opens.
 */
export function TagHoursCard<Key extends QueryKey>({
  title,
  note,
  today,
  query,
}: {
  title: string
  note?: string
  today: string
  query: (stretch: Stretch) => UseQueryOptions<Hours, Error, Hours, Key>
}) {
  const titleId = useId()
  const [period, setPeriod] = useState<Period>('month')
  const [year, setYear] = useState(Number(today.slice(0, 4)))
  const [month, setMonth] = useState(Number(today.slice(5, 7)))
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

  return (
    <section className="tag-hours" aria-labelledby={titleId}>
      <div className="tag-hours__head">
        <h2 id={titleId} className="tag-hours__title">
          {title}
        </h2>
        <SegmentedControl
          label={copy.periods}
          options={[
            { value: 'month', label: copy.month },
            { value: 'year', label: copy.year },
          ]}
          value={period}
          onChange={setPeriod}
        />
      </div>
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
        <p className="tag-hours__error" role="alert">
          {copy.error}
        </p>
      ) : hours.data ? (
        <>
          <TagHoursRows hours={hours.data} />
          <NoDuration hours={hours.data} linked />
        </>
      ) : (
        <p className="tag-hours__note">{copy.loading}</p>
      )}
      {note && <p className="tag-hours__note">{note}</p>}
    </section>
  )
}

/** The student page's: this month or this year, as `/api/me/classes` gives them. */
export function TagHoursNow({ title, month, year }: { title: string; month: Hours; year: Hours }) {
  const titleId = useId()
  const [period, setPeriod] = useState<Period>('month')
  return (
    <section className="tag-hours" aria-labelledby={titleId}>
      <div className="tag-hours__head">
        <h2 id={titleId} className="tag-hours__title">
          {title}
        </h2>
        <SegmentedControl
          label={copy.periods}
          options={[
            { value: 'month', label: copy.thisMonth },
            { value: 'year', label: copy.thisYear },
          ]}
          value={period}
          onChange={setPeriod}
        />
      </div>
      <TagHoursRows hours={period === 'month' ? month : year} />
      <NoDuration hours={period === 'month' ? month : year} />
    </section>
  )
}

/** The classes counted that have no duration, so add no minutes (#257): how many, and
 * on staff's cards each of the latest, to go set its duration. */
function NoDuration({ hours, linked = false }: { hours: Hours; linked?: boolean }) {
  if (hours.no_duration_classes === 0) return null
  return (
    <div className="tag-hours__missing">
      <p className="tag-hours__note">{copy.noDuration(hours.no_duration_classes)}</p>
      {linked && <NoDurationLinks hours={hours} />}
    </div>
  )
}

/** Staff's only: the gym's timezone is read off its day of classes. */
function NoDurationLinks({ hours }: { hours: Hours }) {
  const timeZone = useGymTimeZone()
  return (
    <ul className="tag-hours__missing-list">
      {hours.no_duration.map((each) => (
        <li key={each.session_id}>
          <Link to="/admin/clases/$sessionId" params={{ sessionId: each.session_id }}>
            {copy.noDurationLink(shortDay(isoDay(each.starts_at, timeZone)), each.class_type_name)}
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** Each tag as a bar whose text carries the figure, most hours first. */
function TagHoursRows({ hours }: { hours: Hours }) {
  if (hours.tags.length === 0) return <p className="tag-hours__note">{copy.empty}</p>
  const most = Math.max(...hours.tags.map((row) => row.minutes), 1)
  return (
    <>
      <ul className="tag-hours__rows">
        {hours.tags.map((row) => (
          <li key={row.tag_id} className="tag-hours__row">
            <span className="tag-hours__line">
              <span>
                {row.name}
                {row.archived && <span className="tag-hours__note">{copy.archivedSuffix}</span>}
              </span>
              <span className="tag-hours__figure">
                {copy.figure(row.minutes, row.classes)}
              </span>
            </span>
            <span className="tag-hours__bar" aria-hidden="true">
              <span
                className={row.archived ? 'tag-hours__fill tag-hours__fill--archived' : 'tag-hours__fill'}
                style={{ width: `${(row.minutes / most) * 100}%` }}
              />
            </span>
          </li>
        ))}
      </ul>
      {hours.untagged_minutes > 0 && (
        <p className="tag-hours__note">{copy.untagged(copy.hours(hours.untagged_minutes))}</p>
      )}
    </>
  )
}
