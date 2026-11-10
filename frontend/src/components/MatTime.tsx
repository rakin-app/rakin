import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { hasTime, myTimeQuery, personTimeQuery, type PersonTime, type TimeTotals } from '../api/matTime'
import { t } from '../i18n/es'
import './MatTime.css'

const copy = t.matTime

type Period = 'month' | 'allTime'

/** The student page's card, from `/api/me/time`. */
export function MyMatTime() {
  return <Loaded query={useQuery(myTimeQuery())} mine />
}

/** The ficha's card for the member, from `/api/people/{id}/time`. */
export function MemberMatTime({ personId }: { personId: string }) {
  return <Loaded query={useQuery(personTimeQuery(personId))} mine={false} />
}

function Loaded({ query, mine }: { query: { data?: PersonTime; isError: boolean }; mine: boolean }) {
  if (query.isError) {
    return (
      <p className="mat-time__error" role="alert">
        {copy.error}
      </p>
    )
  }
  if (query.data) return <MatTime time={query.data} mine={mine} />
  // While it loads, the card holds its place, so what is below it does not jump.
  return (
    <section className="mat-time mat-time--loading" aria-busy="true" aria-label={mine ? copy.mine : copy.theirs}>
      <p className="mat-time__note">{copy.loading}</p>
    </section>
  )
}

/**
 * "Tiempo en el tatami" (#141): the classes a person attended and the time each block
 * kind ran in them, this month or all time, as the API totals them. Each kind is a bar
 * whose text carries the figure, so the bars themselves are only decoration. Open mats
 * are a line of their own: their time is sparring too, as the API counts it.
 *
 * `mine` is the student page's wording; the ficha's speaks of the member.
 */
export function MatTime({ time, mine }: { time: PersonTime; mine: boolean }) {
  const [period, setPeriod] = useState<Period>('month')
  const titleId = useId()
  const title = mine ? copy.mine : copy.theirs

  if (!hasTime(time.all_time)) {
    return (
      <section className="mat-time" aria-labelledby={titleId}>
        <h2 id={titleId} className="mat-time__title">
          {title}
        </h2>
        <p className="mat-time__note">{mine ? copy.emptyMine : copy.emptyTheirs}</p>
      </section>
    )
  }

  const totals = period === 'month' ? time.this_month : time.all_time
  return (
    <section className="mat-time" aria-labelledby={titleId}>
      <div className="mat-time__head">
        <h2 id={titleId} className="mat-time__title">
          {title}
        </h2>
        <div className="mat-time__periods" role="group" aria-label={copy.periods}>
          {(['month', 'allTime'] as const).map((p) => (
            <button
              key={p}
              type="button"
              className="mat-time__period"
              aria-pressed={period === p}
              onClick={() => setPeriod(p)}
            >
              {copy[p]}
            </button>
          ))}
        </div>
      </div>
      <Totals totals={totals} />
    </section>
  )
}

function Totals({ totals }: { totals: TimeTotals }) {
  const longest = Math.max(...totals.by_kind.map((kind) => kind.seconds), 1)
  return (
    <>
      <dl className="mat-time__figures">
        <div className="mat-time__figure">
          <dt>{copy.classes}</dt>
          <dd>{totals.classes.toLocaleString('es-CL')}</dd>
        </div>
        <div className="mat-time__figure">
          <dt>{copy.sparring}</dt>
          <dd>{copy.duration(totals.sparring_seconds)}</dd>
        </div>
      </dl>
      {hasTime(totals) ? (
        <>
          {totals.by_kind.length > 0 && (
            <ul className="mat-time__kinds" aria-label={copy.byKind}>
              {totals.by_kind.map((kind) => (
                <li key={kind.block_kind_id} className="mat-time__kind">
                  <span className="mat-time__kind-row">
                    <span>{kind.name}</span>
                    <span className="mat-time__kind-time">{copy.duration(kind.seconds)}</span>
                  </span>
                  <span className="mat-time__bar" aria-hidden="true">
                    <span
                      className={kind.is_sparring ? 'mat-time__fill mat-time__fill--sparring' : 'mat-time__fill'}
                      style={{ width: `${(kind.seconds / longest) * 100}%` }}
                    />
                  </span>
                </li>
              ))}
            </ul>
          )}
          {totals.open_mats > 0 && (
            <p className="mat-time__open-mat">
              <span>{copy.openMat(totals.open_mats, copy.duration(totals.open_mat_seconds))}</span>
              <span className="mat-time__note">{copy.openMatNote}</span>
            </p>
          )}
        </>
      ) : (
        <p className="mat-time__note">{copy.emptyMonth}</p>
      )}
    </>
  )
}
