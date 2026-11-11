import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { rankLabel } from '../api/grading'
import { myPageQuery, type BankAccount, type MyPage, type MyPayment } from '../api/me'
import { RankBelt } from '../components/Belt'
import { Button } from '../components/Button'
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
 * already sent with how each was reviewed.
 */
export function MeHome() {
  const page = useQuery(myPageQuery())

  if (page.isPending || page.isError) {
    return (
      <>
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
      </>
    )
  }

  const firstName = page.data.name.split(' ')[0]
  return (
    <>
      <PageHeader eyebrow={page.data.gym_name} title={firstName ? copy.home.hello(firstName) : copy.home.title} />
      <div className="me-home">
        <NextPayment page={page.data} />
        <Training page={page.data} />
        <MyMatTime />
        <History page={page.data} />
        <p className="me-home__footnote">{copy.home.signedIn}</p>
      </div>
    </>
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

/** "Mi entrenamiento": the belt, once the gym has recorded one, and the classes attended. */
function Training({ page }: { page: MyPage }) {
  const words = copy.training
  return (
    <section className="training" aria-label={words.title}>
      {page.rank && (
        <div className="training__card">
          <span className="training__eyebrow">{words.belt}</span>
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
                    payment.period_start ? t.common.month(payment.period_start, year) : copy.history.payment,
                    payment.person_id === page.person_id ? null : payment.person_name,
                  )}
                </span>
                <span className="history__detail">{detail(payment, page.timezone)}</span>
              </span>
              <span className="history__state">
                {payment.status === 'validated' ? t.common.clp(payment.amount_clp) : copy.history.status[payment.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function detail(payment: MyPayment, timeZone: string): string {
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
