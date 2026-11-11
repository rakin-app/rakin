import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import {
  amountMatch,
  isImage,
  owed,
  proofQueueQuery,
  rejectProof,
  validateProof,
  type ProofReview,
  type Validated,
} from '../api/review'
import { remindersQuery, type PaymentReminder } from '../api/reminders'
import { Button, buttonClass } from '../components/Button'
import { Input } from '../components/Field'
import { ChevronLeftIcon, ChevronRightIcon } from '../components/icons'
import { ReminderLink } from '../components/ReminderLink'
import { monthName, shortDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './ValidateProof.css'

const copy = t.admin.review
const clp = t.common.clp

/**
 * "Validar comprobante": one pending proof at a time, the claimed amount beside
 * what the period owes, the proof itself and the member's recent history, and
 * one tap to confirm it or, with a note the student is emailed, reject it. The
 * pager walks the queue, oldest first.
 *
 * A rejection also offers its follow-up by WhatsApp, the note prefilled, to the
 * student or their guardian (#55).
 */
export function ValidateProof() {
  usePageTitle(copy.title)
  const queue = useQuery(proofQueueQuery())
  const [index, setIndex] = useState(0)
  const [done, setDone] = useState<Done | null>(null)

  if (queue.isPending) return <p className="review__note">{copy.loading}</p>
  if (queue.isError) {
    return (
      <div className="review__note" role="alert">
        <p>{copy.error}</p>
        <Button size="lg" onClick={() => void queue.refetch()}>
          {copy.retry}
        </Button>
      </div>
    )
  }

  const items = queue.data
  // A review removes its proof from the queue, so the same index shows the next one.
  const at = Math.min(index, Math.max(items.length - 1, 0))
  const item = items[at]

  return (
    <div className="review">
      <header className="review__header">
        <Link to="/admin" className={buttonClass({ icon: true })} aria-label={copy.back}>
          <ChevronLeftIcon />
        </Link>
        <div className="review__heading">
          <span className="review__eyebrow">{item ? copy.position(at + 1, items.length) : copy.title}</span>
          <h1 className="review__title">{item ? item.person_name : copy.title}</h1>
        </div>
        {items.length > 1 && (
          <div className="review__pager">
            <Button
              icon
              aria-label={copy.previous}
              disabled={at === 0}
              onClick={() => {
                setIndex(at - 1)
                setDone(null)
              }}
            >
              <ChevronLeftIcon />
            </Button>
            <Button
              icon
              aria-label={copy.next}
              disabled={at === items.length - 1}
              onClick={() => {
                setIndex(at + 1)
                setDone(null)
              }}
            >
              <ChevronRightIcon />
            </Button>
          </div>
        )}
      </header>

      {done && (
        <div className="review__done" role="status">
          <p>{done.message}</p>
          {done.followUp && (
            <ReminderLink reminder={done.followUp} label={t.admin.reminders.followUp(done.followUp.contact_name)} />
          )}
        </div>
      )}

      {item ? (
        // Keyed, so the note and any error start afresh for each proof.
        <Review key={item.id} review={item} onDone={setDone} />
      ) : (
        <p className="review__note">{copy.empty}</p>
      )}
    </div>
  )
}

/** What the last review did, and the WhatsApp follow-up to a rejection, if there is one. */
type Done = { message: string; followUp?: PaymentReminder }

function Review({ review, onDone }: { review: ProofReview; onDone: (done: Done) => void }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState('')
  const [noteNeeded, setNoteNeeded] = useState(false)
  const noteRef = useRef<HTMLInputElement>(null)
  const ids = { note: useId(), noteError: useId() }

  const settle = () => queryClient.invalidateQueries({ queryKey: ['ledger'] })
  const validate = useMutation({
    mutationFn: () => validateProof(review.id),
    onSuccess: async (result: Validated) => {
      const credit = result.credit ? copy.credit(clp(result.credit.amount_clp)) : ''
      onDone({ message: copy.validated(review.person_name, clp(review.amount_clp)) + credit })
      await settle()
    },
  })
  const reject = useMutation({
    mutationFn: (text: string) => rejectProof(review.id, text),
    onSuccess: async () => {
      const message = copy.rejected(review.claimed_by_name ?? review.person_name)
      onDone({ message })
      await settle()
      // The follow-up is the period's reminder now; failing to find it leaves the email.
      const reminders = await queryClient
        .fetchQuery(remindersQuery(review.person_id))
        .catch((): PaymentReminder[] => [])
      // A cobro extra's proof has no period, and so no period's follow-up (#195).
      const period = review.period
      const followUp = period
        ? reminders.find((r) => r.billing_period_id === period.id && r.kind === 'proof_rejected_followup')
        : undefined
      if (followUp?.whatsapp_url) onDone({ message, followUp })
    },
  })
  const busy = validate.isPending || reject.isPending
  const error = validate.error ?? reject.error

  const tryReject = () => {
    const text = note.trim()
    if (!text) {
      setNoteNeeded(true)
      noteRef.current?.focus()
      return
    }
    validate.reset()
    reject.mutate(text)
  }

  const match = amountMatch(review)
  const { period, extra_line: line } = review

  return (
    <>
      <div className="review__body">
        <section className="review__figures" aria-label={copy.claimLabel}>
          <div className="review__figure">
            <span className="review__figure-label">{copy.claimed}</span>
            <span className="review__figure-amount">{clp(review.amount_clp)}</span>
            <span className="review__figure-detail">
              {copy.claimedAt(
                review.claimed_at ? when(review.claimed_at) : '',
                copy.method[review.method ?? 'transfer'],
              )}
            </span>
          </div>
          <div className="review__figure">
            <span className="review__figure-label">{copy.owes}</span>
            <span className="review__figure-amount">{clp(owed(review))}</span>
            <span className="review__figure-detail">
              {period
                ? copy.periodDue(monthName(period.period_start), shortDay(period.due_date))
                : line && copy.extraDue(t.admin.extra.category[line.category], shortDay(line.due_date))}
            </span>
          </div>
        </section>

        <p className={`review__match review__match--${match.kind}`}>
          {match.kind === 'matches'
            ? copy.match.matches
            : copy.match[match.kind](clp(match.difference))}
        </p>

        <Proof review={review} />

        <dl className="review__details">
          {line ? (
            // A cobro extra has no plan, prior balance or history of its own (#195).
            <div>
              <dt>{copy.extra}</dt>
              <dd>{line.title}</dd>
            </div>
          ) : (
            <>
              <div>
                <dt>{copy.plan}</dt>
                <dd>
                  {review.anchor_day && review.plan_name
                    ? copy.planDay(review.plan_name, review.anchor_day)
                    : review.plan_name}
                </dd>
              </div>
              <div>
                <dt>{copy.priorBalance}</dt>
                <dd>{clp(review.prior_balance_clp)}</dd>
              </div>
              <div>
                <dt>{copy.lastPayments}</dt>
                <dd>
                  {review.last_payments.length
                    ? review.last_payments.map((p) => shortDay(p.paid_at)).join(' · ')
                    : copy.noPayments}
                </dd>
              </div>
            </>
          )}
          <div>
            <dt>{copy.attendance}</dt>
            <dd>{copy.attendanceCount(review.attendance_30d)}</dd>
          </div>
        </dl>

        <label htmlFor={ids.note} className="review__label">
          {copy.noteLabel}
        </label>
        <Input
          ref={noteRef}
          id={ids.note}
          type="text"
          maxLength={500}
          placeholder={copy.notePlaceholder}
          value={note}
          aria-invalid={noteNeeded && !note.trim()}
          aria-describedby={noteNeeded ? ids.noteError : undefined}
          onChange={(e) => setNote(e.target.value)}
        />
        {noteNeeded && !note.trim() && (
          <p id={ids.noteError} className="review__error" role="alert">
            {copy.noteNeeded}
          </p>
        )}
        {error && (
          <p className="review__error" role="alert">
            {refusal(error)}
          </p>
        )}
      </div>

      <div className="review__actions">
        <Button variant="danger" size="lg" disabled={busy} onClick={tryReject}>
          {reject.isPending ? copy.working : copy.reject}
        </Button>
        <Button
          variant="primary" size="lg"
          disabled={busy}
          onClick={() => {
            reject.reset()
            validate.mutate()
          }}
        >
          {validate.isPending ? copy.working : copy.confirm(clp(review.amount_clp))}
        </Button>
      </div>
    </>
  )
}

/** The proof, tap to zoom; a PDF, or an image the browser cannot show, opens instead. */
function Proof({ review }: { review: ProofReview }) {
  const [zoomed, setZoomed] = useState(false)
  const [broken, setBroken] = useState(false)
  const close = useCallback(() => setZoomed(false), [])
  const label = copy.proofLabel(review.person_name)
  const caption =
    review.claimed_by_name && review.claimed_by_name !== review.person_name
      ? copy.sentBy(review.claimed_by_name)
      : copy.sentByStudent

  let body
  if (!review.proof_url) {
    body = <p className="review__proof review__proof--empty">{copy.missing}</p>
  } else if (isImage(review) && !broken) {
    body = (
      <button type="button" className="review__proof" aria-label={copy.zoomLabel} onClick={() => setZoomed(true)}>
        <img src={review.proof_url} alt={label} onError={() => setBroken(true)} />
        <span className="review__proof-hint">{copy.zoom}</span>
      </button>
    )
  } else {
    body = (
      <a className="review__proof review__proof--file" href={review.proof_url} target="_blank" rel="noreferrer">
        {isImage(review) ? copy.openFile : copy.openPdf}
      </a>
    )
  }

  return (
    <figure className="review__figure-proof">
      {body}
      <figcaption className="review__caption">{caption}</figcaption>
      {zoomed && review.proof_url && (
        <Zoom src={review.proof_url} alt={label} onClose={close} />
      )}
    </figure>
  )
}

function Zoom({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  // Focus moves to the close button once, on open, not on every render of the page.
  useEffect(() => {
    closeRef.current?.focus()
  }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="review__zoom" role="dialog" aria-modal="true" aria-label={alt} onClick={onClose}>
      <Button ref={closeRef} inverse className="review__zoom-close" onClick={onClose}>
        {copy.close}
      </Button>
      <img src={src} alt={alt} />
    </div>
  )
}

function refusal(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail
    return detail === 'billing period is already paid in full' || detail === 'the line is already paid in full'
      ? copy.refused.paid
      : copy.refused.reviewed
  }
  return copy.refused.failed
}

/** `hoy 14:12`, or `8 nov 14:12` on another day. */
function when(iso: string): string {
  const at = new Date(iso)
  const time = at.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  const today = at.toDateString() === new Date().toDateString()
  return `${today ? t.common.today : shortDay(iso)} ${time}`
}
