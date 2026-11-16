import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { hasTime, myTimeQuery, personTimeQuery, type PersonTime, type TimeTotals } from '../api/matTime'
import type { ReactNode } from 'react'
import { t } from '../i18n/es'
import { BarError, BarList, BarNote } from './BarList'
import { Card, Section, SectionHeader } from './Card'
import { SegmentedControl } from './Chip'
import './MatTime.css'

const copy = t.matTime

type Period = 'month' | 'allTime'

/** The student page's card, from `/api/me/time`. */
export function MyMatTime() {
  return <Loaded query={useQuery(myTimeQuery())} mine />
}

/** The ficha's card for the member, from `/api/people/{id}/time`. */
export function MemberMatTime({ personId }: { personId: string }) {
  return <Loaded query={useQuery(personTimeQuery(personId))} mine={false} headed />
}

function Loaded({
  query,
  mine,
  headed = false,
}: {
  query: { data?: PersonTime; isError: boolean }
  mine: boolean
  headed?: boolean
}) {
  if (query.isError) {
    return <BarError>{copy.error}</BarError>
  }
  if (query.data) return <MatTime time={query.data} mine={mine} headed={headed} />
  // While it loads, the card holds its place, so what is below it does not jump.
  return (
    <Card className="mat-time--loading" aria-busy="true" aria-label={mine ? copy.mine : copy.theirs}>
      <BarNote>{copy.loading}</BarNote>
    </Card>
  )
}

/**
 * "Tiempo de entrenamiento" (#141): the classes a person attended and the time each block
 * kind ran in them, this month or all time, as the API totals them. Each kind is a bar
 * whose text carries the figure, so the bars themselves are only decoration. Open mats
 * are a line of their own: their time is sparring too, as the API counts it.
 *
 * `mine` is the student page's wording; the ficha's speaks of the member. `headed` puts
 * the title over the card, as the ficha heads each of its sections (#360).
 */
export function MatTime({ time, mine, headed = false }: { time: PersonTime; mine: boolean; headed?: boolean }) {
  const [period, setPeriod] = useState<Period>('month')
  const titleId = useId()
  const title = mine ? copy.mine : copy.theirs

  if (!hasTime(time.all_time)) {
    return (
      <Frame titleId={titleId} title={title} headed={headed}>
        <BarNote>{mine ? copy.emptyMine : copy.emptyTheirs}</BarNote>
      </Frame>
    )
  }

  const totals = period === 'month' ? time.this_month : time.all_time
  return (
    <Frame
      titleId={titleId}
      title={title}
      headed={headed}
      control={
        <SegmentedControl
          label={copy.periods}
          options={[
            { value: 'month', label: copy.month },
            { value: 'allTime', label: copy.allTime },
          ]}
          value={period}
          onChange={setPeriod}
        />
      }
    >
      <Totals totals={totals} mine={mine} />
    </Frame>
  )
}

/** The card, its title and period control in its head, or over it when `headed`. */
function Frame({
  titleId,
  title,
  headed,
  control,
  children,
}: {
  titleId: string
  title: string
  headed: boolean
  control?: ReactNode
  children: ReactNode
}) {
  if (headed) {
    return (
      <Section id={titleId} title={title} trailing={control}>
        <Card as="div">{children}</Card>
      </Section>
    )
  }
  return (
    <Card aria-labelledby={titleId}>
      <SectionHeader id={titleId} title={title} trailing={control} />
      {children}
    </Card>
  )
}

function Totals({ totals, mine }: { totals: TimeTotals; mine: boolean }) {
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
            <BarList
              label={copy.byKind}
              bars={totals.by_kind.map((kind) => ({
                key: kind.block_kind_id,
                label: kind.name,
                figure: copy.duration(kind.seconds),
                value: kind.seconds,
                muted: !kind.is_sparring,
              }))}
            />
          )}
          {totals.open_mats > 0 && (
            <p className="mat-time__open-mat">
              <span>{copy.openMat(totals.open_mats, copy.duration(totals.open_mat_seconds))}</span>
              <span className="bar-note">{mine ? copy.openMatNoteMine : copy.openMatNoteTheirs}</span>
            </p>
          )}
        </>
      ) : (
        <BarNote>{copy.emptyMonth}</BarNote>
      )}
    </>
  )
}
