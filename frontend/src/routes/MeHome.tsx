import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { myClassesQuery, type PersonClasses } from '../api/classTags'
import { useGrades } from '../api/activities'
import { rankLabel } from '../api/grading'
import {
  myDependentsQuery,
  myPageQuery,
  myselfQuery,
  type BankAccount,
  type Dependent,
  type MyPage,
  type MyPayment,
} from '../api/me'
import { openPeriodsQuery } from '../api/proofs'
import type { Rank } from '../api/grading'
import { RankBelt } from '../components/Belt'
import { Button } from '../components/Button'
import { GymMark } from '../components/GymMark'
import { Grid, PageContainer } from '../components/Layout'
import { DependentMatTime, MyMatTime } from '../components/MatTime'
import { PageHeader } from '../components/PageHeader'
import { StatusPill } from '../components/StatusPill'
import { TagHoursNow } from '../components/TagHours'
import { TagList } from '../components/Tags'
import { monthName, monthYear } from '../format'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import './MeHome.css'
import { MyConsents } from './MyConsents'
import { MyMaterial } from './MyMaterial'
import { MyPlans } from './MyPlans'
import { MyRequirements } from './MyRequirements'
import { isFamily, payableTogether, ProofUpload } from './ProofUpload'
import { Loading } from '../components/Loading'
import { Card, PlainList, Section, SectionHeader } from '../components/Card'
import { scrollBehavior } from '../motion'

const copy = t.me

/**
 * "Mi página", the student page: what is due next and where to transfer it,
 * the proof upload, their belt and classes, their time on the mat, what their classes
 * were about and their hours per tag (theirs and each dependent's, #243), their plans
 * with "Pedir congelamiento" (#270), the payments already sent with how each was reviewed,
 * and for a guardian, their consent for each minor in their care (#370), what they and
 * their dependents owe in one transfer, and each dependent's rank, classes and time on
 * the mat (#66), and the study material their coaches shared with them (#537). Someone on two plans, a course beside a monthly one, reads the plan by
 * what is due next and by each payment (#354). From 1024px it is two columns: the
 * payment and its upload, and beside them the rest.
 */
export function MeHome() {
  const page = useQuery(myPageQuery())
  useDocumentTitle(copy.home.title, page.data?.gym_name)
  // The shell asks for it on every visit; read here, not fetched again.
  const logo = useQuery(myselfQuery()).data?.gym_logo

  if (page.isPending || page.isError) {
    return (
      <PageContainer>
        <PageHeader title={copy.home.title} />
        {page.isPending ? (
          <Loading className="me-home__note">{copy.home.loading}</Loading>
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
            <MyConsents />
            <NextPayment page={page.data} />
            <Together />
            <ExtraCharges page={page.data} />
            <MyPlans page={page.data} />
            <MyRequirements mine={page.data.person_id} />
          </div>
          <div className="me-home__column">
            <Training page={page.data} />
            <MyMaterial />
            <MyMatTime />
            <DependentsTraining />
            <MyClasses mine={page.data.person_id} />
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
    if (uploading) uploadRef.current?.scrollIntoView?.({ behavior: scrollBehavior(), block: 'start' })
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
        <p className="next__paid-up">
          {page.paid_through ? copy.next.paidThrough(t.common.longDay(page.paid_through)) : copy.next.paidUp}
        </p>
      </section>
    )
  }

  const { period, status } = next
  // A proof already sent (#362): the card says it waits on the gym, and sending another
  // is the quiet way, not the card's main action.
  const inReview = status === 'in_review'
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
            {withPlan(
              copy.next.due(t.common.longDay(period.due_date), period.person_id === page.person_id ? null : period.person_name),
              onTwoPlans(page).has(period.person_id) ? period.plan_name : null,
              copy.next.ofPlan,
            )}
          </span>
        </div>
        {inReview && <p className="next__review">{copy.next.inReview}</p>}
        {page.bank_account ? <Bank account={page.bank_account} /> : <p className="next__no-bank">{copy.next.noBank}</p>}
        <div className={page.bank_account ? 'next__actions' : 'next__actions next__actions--single'}>
          {page.bank_account && <CopyBank account={page.bank_account} />}
          <Button
            variant={inReview ? 'secondary' : 'primary'} size="lg" inverse
            aria-expanded={uploading}
            aria-controls={uploadId}
            onClick={() => setUploading((open) => !open)}
          >
            {inReview ? copy.next.uploadAnother : copy.next.upload}
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
 * "Pagar todo junto" (#66): with periods owed by more than one person, a guardian's and
 * their dependents', what they come to in one transfer, and the upload that pays them all.
 */
function Together() {
  const words = copy.together
  const periods = useQuery(openPeriodsQuery())
  const [uploading, setUploading] = useState(false)
  const uploadId = useId()
  const together = payableTogether(periods.data ?? [])
  if (!isFamily(together)) return null
  const total = together.reduce((sum, p) => sum + p.outstanding_clp, 0)
  const names = new Intl.ListFormat('es', { type: 'conjunction' }).format([
    ...new Set(together.map((p) => p.person_name)),
  ])
  return (
    <>
      <Card className="together" aria-labelledby="together-title">
        <SectionHeader id="together-title" title={words.title} />
        <span className="together__total">{t.common.clp(total)}</span>
        <p className="together__who">{words.who(names)}</p>
        <Button aria-expanded={uploading} aria-controls={uploadId} onClick={() => setUploading((open) => !open)}>
          {words.upload}
        </Button>
      </Card>
      <div id={uploadId} hidden={!uploading}>
        {uploading && <ProofUpload together />}
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
    <Section id="extra-mine-title" title={words.title} className="extra-mine">
      <PlainList className="extra-mine__list">
        {lines.map((line) => {
          const status = line.status === 'in_review' ? 'in_review' : line.due_date < today ? 'overdue' : 'open'
          return (
            <Card as="li" key={line.id} className="extra-mine__row">
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
            </Card>
          )
        })}
      </PlainList>
    </Section>
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

/** "Mi entrenamiento": the rank, once the gym has recorded one and while one of its
 * activities grades (#245), and the classes attended. */
function Training({ page }: { page: MyPage }) {
  return (
    <section className="training" aria-label={copy.training.title}>
      <TrainingCards rank={page.rank} attendance={page.attendance} memberSince={page.member_since} />
    </section>
  )
}

/** A rank and the classes attended, the student's own or a dependent's. */
function TrainingCards({
  rank,
  attendance,
  memberSince,
}: {
  rank: Rank | null
  attendance: MyPage['attendance']
  memberSince?: string
}) {
  const words = copy.training
  const grades = useGrades()
  return (
    <>
      {grades && rank && (
        <Card as="div" className="training__card">
          <span className="training__eyebrow">{rank.belt ? words.belt : words.rank}</span>
          <RankBelt rank={rank} />
          <span className="training__figure">{rankLabel(rank)}</span>
          <span className="training__detail">{words.since(t.common.dayYear(rank.awarded_on))}</span>
        </Card>
      )}
      <Card as="div" className="training__card">
        <span className="training__eyebrow">{words.month}</span>
        <span className="training__figure">{words.classes(attendance.this_month)}</span>
        <span className="training__detail">{words.total(attendance.total)}</span>
        {memberSince && <span className="training__detail">{words.memberSince(monthYear(memberSince))}</span>}
      </Card>
    </>
  )
}

/** For a guardian, each dependent's rank, classes and time on the mat (#66). Nothing
 * while they load or for someone who is nobody's guardian: the page's own come first. */
function DependentsTraining() {
  const dependents = useQuery(myDependentsQuery())
  return (
    <>
      {(dependents.data ?? []).map((dependent) => (
        <DependentTraining key={dependent.id} dependent={dependent} />
      ))}
    </>
  )
}

function DependentTraining({ dependent }: { dependent: Dependent }) {
  const titleId = useId()
  return (
    <Section id={titleId} title={copy.training.theirs(dependent.name)}>
      <div className="training">
        <TrainingCards rank={dependent.rank} attendance={dependent.attendance} />
      </div>
      <DependentMatTime personId={dependent.id} name={dependent.name} />
    </Section>
  )
}

// How many classes a person's list shows before "Ver más".
const CLASSES_FIRST = 5

/**
 * "Mis clases" (#243): each class attended, newest first, with its topic and tags, and
 * the hours per tag this month and this year; a guardian reads each dependent's too.
 * The coach's notes never reach this page: the API leaves them out.
 */
function MyClasses({ mine }: { mine: string }) {
  const classes = useQuery(myClassesQuery())
  if (classes.isError) {
    return (
      <p className="me-home__note" role="alert">
        {copy.classes.error}
      </p>
    )
  }
  if (!classes.data) return <Loading className="me-home__note">{copy.classes.loading}</Loading>
  return (
    <>
      {classes.data.people.map((person) => (
        <PersonClassList
          key={person.person_id}
          person={person}
          mine={person.person_id === mine}
          timeZone={classes.data.timezone}
        />
      ))}
    </>
  )
}

function PersonClassList({ person, mine, timeZone }: { person: PersonClasses; mine: boolean; timeZone: string }) {
  const words = copy.classes
  const titleId = useId()
  const [all, setAll] = useState(false)
  const shown = all ? person.classes : person.classes.slice(0, CLASSES_FIRST)
  return (
    <>
      <Section id={titleId} title={mine ? words.title : words.theirs(person.name)}>
        {person.classes.length === 0 ? (
          <p className="me-home__note">{words.empty}</p>
        ) : (
          <Card as="ul" flush>
            {shown.map((held) => (
              <li key={held.session_id} className="history__row my-class">
                <span className="history__what">
                  {/* The class is the row's title, its topic after the day when it has one (#362). */}
                  <span className="history__month">{held.class_type_name}</span>
                  <span className="history__detail">
                    {words.when(t.common.shortDay(zonedDay(held.starts_at, timeZone)), held.topic)}
                  </span>
                  <TagList tags={held.tags} label={words.tags} />
                </span>
              </li>
            ))}
          </Card>
        )}
        {!all && person.classes.length > CLASSES_FIRST && (
          <Button variant="ghost" onClick={() => setAll(true)}>
            {words.more(person.classes.length - CLASSES_FIRST)}
          </Button>
        )}
      </Section>
      {person.classes.length > 0 && (
        <TagHoursNow
          title={mine ? words.hours : words.theirHours(person.name)}
          month={person.this_month}
          year={person.this_year}
        />
      )}
    </>
  )
}

/** Who, the student or a dependent, is on more than one plan running here, a course
 * beside a monthly one (#354). Plans that ended do not count: someone who changed plan
 * is on one. */
function onTwoPlans(page: MyPage): Set<string> {
  const running = new Map<string, number>()
  for (const plan of page.plans ?? []) running.set(plan.person_id, (running.get(plan.person_id) ?? 0) + 1)
  return new Set([...running].filter(([, count]) => count > 1).map(([person]) => person))
}

/** `text` with the plan it is about, when there is one to name. */
function withPlan(text: string, plan: string | null | undefined, ofPlan: (text: string, plan: string) => string): string {
  return plan ? ofPlan(text, plan) : text
}

function History({ page }: { page: MyPage }) {
  const year = zonedDay(new Date().toISOString(), page.timezone).slice(0, 4)
  const named = onTwoPlans(page)
  return (
    <Section id="history-title" title={copy.history.title}>
      {page.payments.length === 0 ? (
        <p className="me-home__note">{copy.history.empty}</p>
      ) : (
        <Card as="ul" flush>
          {page.payments.map((payment) => (
            <li key={payment.id} className={`history__row history__row--${payment.status}`}>
              <span className="history__dot" aria-hidden="true" />
              <span className="history__what">
                <span className="history__month">
                  {copy.history.month(
                    withPlan(title(payment, year), named.has(payment.person_id) ? payment.plan_name : null, copy.history.ofPlan),
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
        </Card>
      )}
    </Section>
  )
}

/** `Octubre` for a payment, or the cobro extra it pays; `Devolución octubre`, `Descuento
 * octubre`; `Saldo a favor`. */
function title(payment: MyPayment, year: string): string {
  const words = copy.history
  const month = payment.period_start ? t.common.month(payment.period_start, year) : null
  const what = payment.charge_title ?? month
  if (payment.kind === 'payment') return what ?? words.payment
  // Moved to another month, plan or sibling (#280): from its month to the other's.
  if (payment.purpose === 'move') {
    const to = payment.moved_period_start ? monthName(payment.moved_period_start) : null
    return words.movedOut(payment.period_start ? monthName(payment.period_start) : words.payment.toLowerCase(), to)
  }
  // Undone as recorded by mistake (#281), and the credit it carried with it.
  if (payment.purpose === 'mistake') return words.paymentVoid
  if (payment.purpose === 'revert' && !payment.period_start) return words.creditReverted
  if (payment.kind === 'adjustment' && what === null) return words.credit
  const kind = payment.kind === 'refund' ? words.refund : payment.amount_clp > 0 ? words.discount : words.surcharge
  if (payment.charge_title) return `${kind} · ${payment.charge_title}`
  return month ? `${kind} ${month.toLowerCase()}` : kind
}

/** A payment as paid; a refund given back, `−$20.000`; an adjustment by what it does to
 * what is owed, a discount `−$5.000` and a surcharge `+$5.000`; a credit as held. */
function amount(payment: MyPayment): string {
  if (payment.kind === 'refund') return t.common.signedClp(-payment.amount_clp)
  // A credit taken back with its payment undone (#281): money no longer held.
  if (payment.purpose === 'revert' && !payment.period_start) return t.common.signedClp(payment.amount_clp)
  if (payment.kind === 'adjustment' && payment.period_start) return t.common.adjustmentClp(payment.amount_clp)
  return t.common.clp(payment.amount_clp)
}

function detail(payment: MyPayment, timeZone: string): string {
  const words = copy.history
  const made = when(payment.validated_at ?? payment.created_at, timeZone)
  if (payment.purpose === 'mistake' || payment.purpose === 'revert') return words.voided(made)
  // Either half of a payment moved (#280), never why: out, or in from the other month.
  if (payment.purpose === 'move') {
    if (payment.kind === 'refund' || !payment.moved_period_start) return words.movedOn(made)
    return `${words.movedFrom(monthName(payment.moved_period_start))} · ${made}`
  }
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
