import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useId } from 'react'
import { myAccessQuery, readsLedger } from '../api/me'
import { summaryQuery, type MonthSummary as Summary } from '../api/summary'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { PageContainer } from '../components/Layout'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
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
 * a percentage only from 5 up. Each line shows only when its figure exists. No names
 * behind any figure, and no comparison with other months.
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
  const monthId = useId()
  const shown = summary.data

  return (
    <PageContainer className="summary">
      <SubHeader title={copy.title} subtitle={copy.subtitle} />
      <label htmlFor={monthId} className="summary__month">
        {copy.month}
        <select
          id={monthId}
          className="summary__month-select"
          value={shown?.month ?? search.month ?? ''}
          disabled={!shown}
          onChange={(event) => void navigate({ search: { month: event.target.value }, replace: true })}
        >
          {(shown?.months ?? []).map((month) => (
            <option key={month} value={month}>
              {t.common.month(month, '')}
            </option>
          ))}
        </select>
      </label>
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

/** The month's sentences, each only when its figure exists, then how they are counted. */
function Figures({ summary }: { summary: Summary }) {
  const current = summary.months[0] === summary.month
  const paid = summary.after_reminders
  const percent = (n: number | null) => (n === null ? null : copy.percent(n))
  const reminded = summary.reminder_emails + summary.reminder_whatsapps > 0

  const money = [
    reminded ? copy.reminders(summary.reminder_emails, summary.reminder_whatsapps) : null,
    paid.total.payments > 0
      ? copy.paidAfter(
          paid.total.payments,
          clp(paid.total.amount_clp),
          percent(paid.income_percent),
          clp(summary.income_clp),
        )
      : null,
    paid.emails_only.payments > 0 ? copy.emailsOnly(paid.emails_only.payments) : null,
    paid.after_whatsapp.payments > 0 ? copy.afterWhatsapp(paid.after_whatsapp.payments) : null,
  ].filter((line) => line !== null)

  const nudges = summary.nudges
  const people = !summary.whatsapp
    ? [copy.whatsappOff]
    : nudges.nudged > 0
      ? [copy.nudged(nudges.nudged), copy.back(nudges.back, nudges.nudged, percent(nudges.percent))]
      : []

  const own = summary.own_payments
  const counts = [
    own.by_members > 0 ? copy.ownPayments(own.by_members, own.payments) : null,
    summary.proofs.median_minutes !== null
      ? copy.proofs(summary.proofs.reviewed, copy.duration(summary.proofs.median_minutes))
      : null,
    summary.emails_sent > 0 ? copy.emailsSent(summary.emails_sent) : null,
    summary.reactivated > 0 ? copy.reactivated(summary.reactivated) : null,
    summary.trials_converted > 0 ? copy.trialsConverted(summary.trials_converted) : null,
  ].filter((line) => line !== null)

  return (
    <>
      <Card className="summary__card" aria-labelledby="summary-month">
        <h2 id="summary-month" className="summary__heading">
          {t.common.month(summary.month, '')}
          {summary.since && <span className="summary__since">{copy.since(t.common.longDay(summary.since))}</span>}
        </h2>
        {reminded ? (
          <p className="summary__lines">{money.join(' ')}</p>
        ) : (
          <p className="summary__lines summary__empty">{current ? copy.noReminders : copy.noRemindersPast}</p>
        )}
        {people.length > 0 && <p className="summary__lines">{people.join(' ')}</p>}
        {counts.length > 0 && (
          <ul className="summary__counts">
            {counts.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </Card>
      <details className="summary__how">
        <summary>{copy.how.title}</summary>
        <p>{copy.how.paid}</p>
        <p>{copy.how.anyway}</p>
        <p>{copy.how.back}</p>
        <p>{copy.how.totals}</p>
      </details>
    </>
  )
}
