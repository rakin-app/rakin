import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { rankLabel } from '../api/grading'
import { myPageQuery, myselfQuery, type BankAccount, type MyPage, type MyPayment } from '../api/me'
import { RankBelt } from '../components/Belt'
import { Button } from '../components/Button'
import { GymMark } from '../components/GymMark'
import { Grid, PageContainer } from '../components/Layout'
import { MyMatTime } from '../components/MatTime'
import { PageHeader } from '../components/PageHeader'
import { StatusPill } from '../components/StatusPill'
import { t } from '../i18n/es'
import './MeHome.css'
import { ProofUpload } from './ProofUpload'

const copy = t.me

/**
 * "Mi página", the student page: what is due next and where to transfer it,
 * the proof upload, their belt and classes, their time on the mat, and the payments
 * already sent with how each was reviewed. From 1024px it is two columns: the payment
 * and its upload, and beside them the rest.
 */
export function MeHome() {
  const page = useQuery(myPageQuery())
  // The shell asks for it on every visit; read here, not fetched again.
  const logo = useQuery(myselfQuery()).data?.gym_logo

  if (page.isPending || page.isError) {
    return (
      <PageContainer>
        <PageHeader title={copy.home.title} />
        {page.isPending ? (
          <p className="me-home__note">{copy.home.loading}</p>
        ) : (
          <div className="me-home__note" role="alert">
            <p>{copy.home.error}</p>
            <Button className="me-home__retry" onClick={() => void page.refetch()}>
              {copy.home.retry}
            </Button>
          </div>
        )}
      </PageContainer>
    )
  }

  const firstName = page.data.name.split(' ')[0]
  return (
    <PageContainer>
      <PageHeader
        mark={<GymMark name={page.data.gym_name} logo={logo} size="large" />}
        eyebrow={page.data.gym_name}
        title={firstName ? copy.home.hello(firstName) : copy.home.title}
      />
      <div className="me-home">
        <Grid>
          <div className="me-home__column">
            <NextPayment page={page.data} />
            <ExtraCharges page={page.data} />
          </div>
          <div className="me-home__column">
            <Training page={page.data} />
            <MyMatTime />
            <History page={page.data} />
          </div>
        </Grid>
        <p className="me-home__footnote">{copy.home.signedIn}</p>
      </div>
    </PageContainer>
  )
}

function NextPayment({ page }: { page: MyPage }) {
  const [uploading, setUploading] = useState(false)
  const uploadId = useId()
  const uploadRef = useRef<HTMLDivElement>(null)
  const next = page.next_payment

  useEffect(() => {
    if (uploading) uploadRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [uploading])

  if (next === null) {
    return (
      <section className="next" aria-label={copy.next.title}>
        <div className="next__top">
          <span className="next__eyebrow">{copy.next.title}</span>
          <StatusPill status="paid" inverse>
            {copy.next.status.paid}
          </StatusPill>
        </div>
        <p className="next__paid-up">{copy.next.paidUp}</p>
      </section>
    )
  }

  const { period, status } = next
  return (
    <>
      <section className="next" aria-label={copy.next.title}>
        <div className="next__top">
          <span className="next__eyebrow">{copy.next.title}</span>
          <StatusPill status={status} inverse>
            {copy.next.status[status]}
          </StatusPill>
        </div>
        <div className="next__amount">
          <span className="next__figure">{t.common.clp(period.outstanding_clp)}</span>
          <span className="next__due">
            {copy.next.due(t.common.longDay(period.due_date), period.person_id === page.person_id ? null : period.person_name)}
          </span>
        </div>
        {page.bank_account ? <Bank account={page.bank_account} /> : <p className="next__no-bank">{copy.next.noBank}</p>}
        <div className={page.bank_account ? 'next__actions' : 'next__actions next__actions--single'}>
          {page.bank_account && <CopyBank account={page.bank_account} />}
          <Button
            variant="primary" size="lg" inverse
            aria-expanded={uploading}
            aria-controls={uploadId}
            onClick={() => setUploading((open) => !open)}
          >
            {copy.next.upload}
          </Button>
        </div>
      </section>
      <div id={uploadId} ref={uploadRef} hidden={!uploading}>
        {uploading && <ProofUpload />}
      </div>
    </>
  )
}

/**
 * "Cobros extra" (#195): a rifa, a seminar or a shared cost, beside the plan's payment
 * and never part of it. Each opens the same "Subir comprobante", on that cobro.
 */
function ExtraCharges({ page }: { page: MyPage }) {
  const words = copy.extra
  const [uploading, setUploading] = useState<string | null>(null)
  const lines = page.extra_charges ?? []
  if (lines.length === 0) return null
  const today = zonedDay(new Date().toISOString(), page.timezone)
  return (
    <section className="extra-mine" aria-labelledby="extra-mine-title">
      <h2 id="extra-mine-title" className="history__title">
        {words.title}
      </h2>
      <ul className="extra-mine__list">
        {lines.map((line) => {
          const status = line.status === 'in_review' ? 'in_review' : line.due_date < today ? 'overdue' : 'open'
          return (
            <li key={line.id} className="extra-mine__row">
              <div className="extra-mine__top">
                <span className="extra-mine__title">{line.title}</span>
                <StatusPill status={status}>{words.status[status]}</StatusPill>
              </div>
              <span className="extra-mine__amount">{t.common.clp(line.outstanding_clp)}</span>
              <span className="extra-mine__detail">
                {words.due(t.common.longDay(line.due_date), line.person_id === page.person_id ? null : line.person_name)}
              </span>
              {line.message && <p className="extra-mine__message">{line.message}</p>}
              <Button
                aria-label={words.upload(line.title)}
                aria-expanded={uploading === line.id}
                onClick={() => setUploading(uploading === line.id ? null : line.id)}
              >
                {copy.next.upload}
              </Button>
              {uploading === line.id && <ProofUpload initial={line.id} />}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Bank({ account }: { account: BankAccount }) {
  const rows: [string, string][] = [
    [copy.next.bank, copy.next.bankName(account.bank, account.account_type)],
    [copy.next.holder, account.holder],
    // Masked on screen, as on a card; "Copiar datos" copies them whole.
    [copy.next.rut, t.common.rut(account.rut).replace(/(?<=\.)\d{3}/g, '•••')],
    [copy.next.number, `•••• ${account.number.replace(/\D/g, '').slice(-4)}`],
  ]
  return (
    <dl className="next__bank" aria-label={copy.next.bankLabel}>
      {rows.map(([label, value]) => (
        <div key={label} className="next__bank-row">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

type CopyState = 'idle' | 'copied' | 'failed'

function CopyBank({ account }: { account: BankAccount }) {
  const [state, setState] = useState<CopyState>('idle')

  useEffect(() => {
    if (state !== 'copied') return
    const timer = setTimeout(() => setState('idle'), 2500)
    return () => clearTimeout(timer)
  }, [state])

  const copyBank = async () => {
    try {
      await navigator.clipboard.writeText(copy.next.copyText({ ...account, rut: t.common.rut(account.rut) }))
      setState('copied')
    } catch {
      setState('failed')
    }
  }

  return (
    <>
      <Button size="lg" inverse onClick={() => void copyBank()}>
        {state === 'copied' ? copy.next.copied : copy.next.copy}
      </Button>
      <span className="visually-hidden" role="status">
        {state === 'copied' ? copy.next.copied : ''}
      </span>
      {state === 'failed' && (
        <p className="next__copy-failed" role="alert">
          {copy.next.copyFailed}
        </p>
      )}
    </>
  )
}

/** "Mi entrenamiento": the rank, once the gym has recorded one, and the classes attended. */
function Training({ page }: { page: MyPage }) {
  const words = copy.training
  return (
    <section className="training" aria-label={words.title}>
      {page.rank && (
        <div className="training__card">
          <span className="training__eyebrow">{page.rank.belt ? words.belt : words.rank}</span>
          <RankBelt rank={page.rank} />
          <span className="training__figure">{rankLabel(page.rank)}</span>
          <span className="training__detail">{words.since(t.common.dayYear(page.rank.awarded_on))}</span>
        </div>
      )}
      <div className="training__card">
        <span className="training__eyebrow">{words.month}</span>
        <span className="training__figure">{words.classes(page.attendance.this_month)}</span>
        <span className="training__detail">{words.total(page.attendance.total)}</span>
      </div>
    </section>
  )
}

function History({ page }: { page: MyPage }) {
  const year = zonedDay(new Date().toISOString(), page.timezone).slice(0, 4)
  return (
    <section className="history" aria-labelledby="history-title">
      <h2 id="history-title" className="history__title">
        {copy.history.title}
      </h2>
      {page.payments.length === 0 ? (
        <p className="me-home__note">{copy.history.empty}</p>
      ) : (
        <ul className="history__list">
          {page.payments.map((payment) => (
            <li key={payment.id} className={`history__row history__row--${payment.status}`}>
              <span className="history__dot" aria-hidden="true" />
              <span className="history__what">
                <span className="history__month">
                  {copy.history.month(
                    title(payment, year),
                    payment.person_id === page.person_id ? null : payment.person_name,
                  )}
                </span>
                <span className="history__detail">{detail(payment, page.timezone)}</span>
              </span>
              <span className="history__state">
                {payment.status === 'validated' ? amount(payment) : copy.history.status[payment.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** `Octubre` for a payment, or the cobro extra it pays; `Devolución octubre`, `Descuento
 * octubre`; `Saldo a favor`. */
function title(payment: MyPayment, year: string): string {
  const words = copy.history
  const month = payment.period_start ? t.common.month(payment.period_start, year) : null
  const what = payment.charge_title ?? month
  if (payment.kind === 'payment') return what ?? words.payment
  if (payment.kind === 'adjustment' && what === null) return words.credit
  const kind = payment.kind === 'refund' ? words.refund : payment.amount_clp > 0 ? words.discount : words.surcharge
  if (payment.charge_title) return `${kind} · ${payment.charge_title}`
  return month ? `${kind} ${month.toLowerCase()}` : kind
}

/** A payment as paid; a refund given back, `−$20.000`; an adjustment by what it does to
 * what is owed, a discount `−$5.000` and a surcharge `+$5.000`; a credit as held. */
function amount(payment: MyPayment): string {
  if (payment.kind === 'refund') return t.common.signedClp(-payment.amount_clp)
  if (payment.kind === 'adjustment' && payment.period_start) return t.common.adjustmentClp(payment.amount_clp)
  return t.common.clp(payment.amount_clp)
}

function detail(payment: MyPayment, timeZone: string): string {
  const words = copy.history
  const made = when(payment.validated_at ?? payment.created_at, timeZone)
  if (payment.kind === 'refund') return words.refunded(made)
  if (payment.kind === 'adjustment') {
    if (!payment.period_start) return [payment.note, made].filter(Boolean).join(' · ')
    return payment.amount_clp > 0 ? words.discounted(made) : words.surcharged(made)
  }
  if (payment.status === 'pending') return copy.history.sent(when(payment.claimed_at ?? payment.created_at, timeZone))
  const reviewed = when(payment.validated_at ?? payment.created_at, timeZone)
  return payment.status === 'validated' ? copy.history.validated(reviewed) : copy.history.rejected(reviewed, payment.note)
}

/** `hoy 14:12` today, else `8 oct`: in the gym's timezone, not the phone's. */
function when(timestamp: string, timeZone: string): string {
  const day = zonedDay(timestamp, timeZone)
  if (day !== zonedDay(new Date().toISOString(), timeZone)) return t.common.shortDay(day)
  const time = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone })
  return copy.history.today(time.format(new Date(timestamp)))
}

/** The ISO day `timestamp` falls on in `timeZone`. */
function zonedDay(timestamp: string, timeZone: string): string {
  // `en-CA` writes dates as ISO does, `2026-11-08`.
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date(timestamp))
}
