import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { myAccessQuery, readsLedger } from '../api/me'
import { summaryQuery, type MonthSummary as Summary } from '../api/summary'
import { Button } from '../components/Button'
import { type Bar, BarList, Meter } from '../components/BarList'
import { Card, PlainList } from '../components/Card'
import { cx } from '../components/classNames'
import { PageContainer } from '../components/Layout'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { monthNeighbours, PeriodStepper } from '../components/PeriodStepper'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { SubHeader } from './ExtraCharges'
import './MonthSummary.css'

const copy = t.admin.summary
const clp = t.common.clp

export type MonthSummarySearch = {
  // The first day of the month shown, `2026-10-01`; the current month when absent.
  month?: string
}

export function validateMonthSummarySearch(search: Record<string, unknown>): MonthSummarySearch {
  const month = typeof search.month === 'string' && /^\d{4}-\d{2}-01$/.test(search.month) ? search.month : undefined
  return { month }
}

const route = getRouteApi('/admin/pagos/resumen')

/**
 * Pagos › Resumen del mes (#505): what happened in a month after Rakin's reminders and
 * the team's nudges, from the counts `GET /api/summary` makes of rows already there
 * (docs/design/value-summary.md, section 4).
 *
 * It says what came *after*, never what Rakin caused: "después de", not "gracias a";
 * every money figure as part of the month's "Cobrado", every people figure as "N de M",
 * a percentage only from 5 up. Never a zero (#516): a tile, a row, a line or a part of
 * one shows only when its number is above zero, and no sentence says nothing happened;
 * a month with nothing above zero says so in one neutral line. No names behind any
 * figure, and no comparison with other months.
 *
 * A closed month is the one kept on the 1st (#506), with the debt it closed with; one
 * counted under older rules says so under "Cómo contamos esto".
 *
 * Owner and admin only, as the rest of Pagos; a coach is told so and nothing is asked
 * of the API.
 */
export function MonthSummary() {
  usePageTitle(copy.title)
  const access = useQuery(myAccessQuery())
  if (readsLedger(access.data)) return <SummaryPage />
  return (
    <PageContainer>
      <PageHeader title={copy.title} />
      {access.isSuccess && <p className="summary__note">{t.admin.payments.coachesOnly}</p>}
    </PageContainer>
  )
}

function SummaryPage() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const summary = useQuery({ ...summaryQuery(search.month), placeholderData: keepPreviousData })
  const shown = summary.data

  return (
    <PageContainer className="summary">
      <SubHeader title={copy.title} subtitle={copy.subtitle} />
      <MonthStepper
        months={shown?.months ?? []}
        month={shown?.month ?? search.month}
        onMonth={(month) => void navigate({ search: { month }, replace: true })}
      />
      {summary.isPending ? (
        <Loading className="summary__note">{copy.loading}</Loading>
      ) : summary.isError && !shown ? (
        <div className="summary__note" role="alert">
          <p>{copy.error}</p>
          <Button onClick={() => void summary.refetch()}>{copy.retry}</Button>
        </div>
      ) : (
        shown && <Figures summary={shown} />
      )}
    </PageContainer>
  )
}

/** The months the API lists, newest first, a step at a time: ‹ Noviembre 2026 ›. */
function MonthStepper({
  months,
  month,
  onMonth,
}: {
  months: readonly string[]
  month: string | undefined
  onMonth: (month: string) => void
}) {
  const { older, newer } = monthNeighbours(months, month)
  return (
    <PeriodStepper
      label={copy.month}
      previous={copy.previous}
      next={copy.next}
      onPrevious={older ? () => onMonth(older) : undefined}
      onNext={newer ? () => onMonth(newer) : undefined}
    >
      {month ? t.common.month(month, '') : ''}
    </PeriodStepper>
  )
}

/** The month's figures, each only when it is above zero, then how they are counted. */
function Figures({ summary }: { summary: Summary }) {
  const paid = summary.after_reminders
  const percent = (n: number | null) => (n === null ? null : copy.percent(n))
  const reminders = summary.reminder_emails + summary.reminder_whatsapps
  const nudges = summary.nudges
  const own = summary.own_payments
  const overdue = summary.overdue_clp ?? 0

  const tiles: TileProps[] = [
    paid.total.payments > 0 && {
      key: 'paid',
      label: copy.paidLabel,
      figure: clp(paid.total.amount_clp),
      detail: `${copy.paidCount(paid.total.payments)} · ${copy.ofIncome(percent(paid.income_percent), clp(summary.income_clp), summary.month)}`,
      share: { value: paid.total.amount_clp, of: summary.income_clp },
    },
    summary.whatsapp &&
      nudges.back > 0 && {
        key: 'back',
        label: copy.backLabel,
        figure: copy.backFigure(nudges.back, nudges.nudged),
        detail: copy.backDetail(percent(nudges.percent)),
        share: { value: nudges.back, of: nudges.nudged },
      },
    reminders > 0 && {
      key: 'reminders',
      label: copy.remindersLabel,
      figure: String(reminders),
      detail: copy.remindersDetail(summary.reminder_emails, summary.reminder_whatsapps),
      small: true,
    },
  ].filter((tile) => tile !== false)

  const split: Bar[] = [
    { key: 'emails', label: copy.emailsOnly, paid: paid.emails_only },
    { key: 'whatsapp', label: copy.afterWhatsapp, paid: paid.after_whatsapp },
  ]
    .filter((row) => row.paid.payments > 0)
    .map((row) => ({
      key: row.key,
      label: row.label,
      figure: copy.splitFigure(row.paid.payments, clp(row.paid.amount_clp)),
      value: row.paid.amount_clp,
    }))

  const counts = [
    own.by_members > 0 && { key: 'own', label: copy.ownPayments, figure: copy.ofTotal(own.by_members, own.payments) },
    summary.proofs.reviewed > 0 &&
      summary.proofs.median_minutes !== null && {
        key: 'proofs',
        label: copy.proofs,
        figure: copy.proofsFigure(summary.proofs.reviewed, copy.duration(summary.proofs.median_minutes)),
      },
    summary.emails_sent > 0 && { key: 'emails', label: copy.emailsSent, figure: String(summary.emails_sent) },
    summary.reactivated > 0 && { key: 'reactivated', label: copy.reactivated, figure: String(summary.reactivated) },
    summary.trials_converted > 0 && {
      key: 'trials',
      label: copy.trialsConverted,
      figure: String(summary.trials_converted),
    },
    overdue > 0 && { key: 'overdue', label: copy.overdue, figure: clp(overdue) },
  ].filter((count) => count !== false)
  const nothing = tiles.length === 0 && split.length === 0 && counts.length === 0

  return (
    <>
      {/* The month is the stepper's, above: the card does not say it again (#567). */}
      <Card className="summary__card" aria-label={copy.cardLabel(t.common.month(summary.month, ''))}>
        {summary.since && <p className="summary__since">{copy.since(t.common.longDay(summary.since))}</p>}
        {tiles.length > 0 && (
          <PlainList className="summary__tiles" aria-label={copy.tiles}>
            {tiles.map((tile) => (
              <Tile {...tile} key={tile.key} />
            ))}
          </PlainList>
        )}
        {nothing && <p className="summary__empty">{copy.nothing}</p>}
        {!summary.whatsapp && <p className="summary__empty">{copy.whatsappOff}</p>}
        {split.length > 0 && (
          <section className="summary__section" aria-labelledby="summary-split">
            <h2 id="summary-split" className="summary__subheading">
              {copy.split}
            </h2>
            <BarList bars={split} />
          </section>
        )}
        {counts.length > 0 && (
          <section className="summary__section" aria-labelledby="summary-counts">
            <h2 id="summary-counts" className="summary__subheading">
              {tiles.length === 0 && split.length === 0 ? copy.countsAlone : copy.counts}
            </h2>
            <dl className="summary__counts">
              {counts.map((count) => (
                <div key={count.key} className="summary__count">
                  <dt>{count.label}</dt>
                  <dd>{count.figure}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </Card>
      <details className="summary__how">
        <summary>{copy.how.title}</summary>
        <p>{copy.how.paid}</p>
        <p>{copy.how.anyway}</p>
        <p>{copy.how.back}</p>
        <p>{copy.how.totals}</p>
        {overdue > 0 && <p>{copy.how.overdue}</p>}
        {summary.kept && <p>{summary.kept.older_rules ? copy.how.olderRules : copy.how.kept}</p>}
      </details>
    </>
  )
}

type TileProps = {
  key: string
  label: string
  figure: string
  detail: string
  /** The figure as part of a whole, drawn as a meter under it. */
  share?: { value: number; of: number }
  /** A figure that counts for less: the reminders sent. */
  small?: boolean
}

/** A headline figure: what it is, the figure big, a meter for a share, and its detail. */
function Tile({ label, figure, detail, share, small = false }: Omit<TileProps, 'key'>) {
  return (
    <li className={cx('summary__tile', small && 'summary__tile--small')}>
      <span className="summary__tile-label">{label}</span>
      <span className="summary__tile-figure">{figure}</span>
      {share && <Meter value={share.value} of={share.of} />}
      <span className="summary__tile-detail">{detail}</span>
    </li>
  )
}
