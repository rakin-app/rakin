import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  approveFreezeRequest,
  freezeRequestsQuery,
  rejectFreezeRequest,
  type FreezeRequest,
} from '../api/freezeRequests'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { addDays, shortDay } from '../format'
import { t } from '../i18n/es'
import { Button } from './Button'
import { Input, Textarea } from './Field'
// The same card as the join requests', a queue beside it on Hoy.
import './JoinRequests.css'
import './FreezeRequests.css'

const copy = t.admin.freezeRequests

/**
 * "Solicitudes de congelamiento (N)" on Hoy (#270): the freezes students asked for from
 * their page, waiting for the owner or an admin, each with its dates and reason.
 * "Aprobar" freezes the plan as "Congelar" does, on the dates asked or others;
 * "Rechazar" answers no, with a note for the student. Nothing shows while none wait,
 * nor when the list fails to load. The caller shows it to the owner and admins only.
 */
export function FreezeRequests() {
  const requests = useQuery(freezeRequestsQuery)
  const [notice, setNotice] = useState<string | null>(null)
  const titleId = useId()

  if (!requests.data || (requests.data.length === 0 && notice === null)) return null
  return (
    <section className="join-requests" aria-labelledby={titleId}>
      <h2 id={titleId} className="join-requests__title">
        {copy.title(requests.data.length)}
      </h2>
      {notice && (
        <p className="join-requests__done" role="status">
          {notice}
        </p>
      )}
      {requests.data.length > 0 && (
        <ul className="join-requests__list">
          {requests.data.map((request) => (
            <li key={request.id} className="join-requests__row" aria-label={request.person_name}>
              <FreezeRequestRow request={request} onDone={setNotice} linked />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/**
 * One request and its answer: on Hoy with the member's name linking to their ficha
 * (`linked`), and on the ficha's plan card without.
 */
export function FreezeRequestRow({
  request,
  onDone,
  linked = false,
}: {
  request: FreezeRequest
  onDone: (message: string) => void
  linked?: boolean
}) {
  const [open, setOpen] = useState<'approve' | 'reject' | null>(null)
  const name = request.person_name
  const reason = t.me.plans.reasons[request.reason]

  return (
    <div className="freeze-request">
      <div className="join-requests__text">
        {linked ? (
          <Link
            to="/admin/alumnos/$personId"
            params={{ personId: request.person_id }}
            className="join-requests__name freeze-request__name"
          >
            {name}
          </Link>
        ) : (
          <span className="join-requests__name">{copy.onCard}</span>
        )}
        <span className="join-requests__detail">
          {linked ? `${request.plan_name} · ` : ''}
          {copy.dates(shortDay(request.from_date), shortDay(request.to_date))}
        </span>
        <span className="join-requests__detail">{copy.reason(reason, request.note)}</span>
        {request.requested_by !== request.person_id && request.requested_by_name && (
          <span className="join-requests__detail">{copy.askedBy(request.requested_by_name)}</span>
        )}
      </div>
      {open === 'approve' && (
        <ApproveForm request={request} onCancel={() => setOpen(null)} onDone={onDone} />
      )}
      {open === 'reject' && <RejectForm request={request} onCancel={() => setOpen(null)} onDone={onDone} />}
      {open === null && (
        <div className="join-requests__actions">
          <Button variant="danger" aria-label={copy.rejectLabel(name)} onClick={() => setOpen('reject')}>
            {copy.reject}
          </Button>
          <Button aria-label={copy.approveLabel(name)} onClick={() => setOpen('approve')}>
            {copy.approve}
          </Button>
        </div>
      )}
    </div>
  )
}

/** After an answer: the queue, and the member's plan and ledger, which an approval moved. */
function useAnswered() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: freezeRequestsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: ['memberships'] }),
      queryClient.invalidateQueries({ queryKey: ['ledger'] }),
    ])
}

function ApproveForm({
  request,
  onCancel,
  onDone,
}: {
  request: FreezeRequest
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const today = useGymToday()
  const refresh = useAnswered()
  const ids = { from: useId(), until: useId(), hint: useId() }
  // A request that waited past its first day starts today, unless the admin says otherwise.
  const [from, setFrom] = useState(request.from_date < today ? today : request.from_date)
  const [until, setUntil] = useState(request.to_date)
  const [checked, setChecked] = useState(false)
  const fromOk = from >= today
  const untilOk = until > from

  const approve = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      approveFreezeRequest(request.id, {
        ...(from !== request.from_date ? { from_date: from } : {}),
        ...(until !== request.to_date ? { to_date: until } : {}),
      }),
    onSuccess: async (frozen) => {
      onDone(copy.approved(request.person_name, shortDay(frozen.freeze?.to_date ?? until)))
      await refresh()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (fromOk && untilOk) approve.mutate()
  }

  return (
    <form className="freeze-request__form" aria-label={copy.approveLabel(request.person_name)} onSubmit={submit} noValidate>
      <div className="freeze-request__dates">
        <div className="freeze-request__field">
          <label htmlFor={ids.from} className="join-requests__label">
            {copy.from}
          </label>
          <Input
            id={ids.from}
            type="date"
            min={today}
            value={from}
            aria-invalid={checked && !fromOk}
            aria-describedby={ids.hint}
            onChange={(e) => setFrom(e.target.value)}
          />
        </div>
        <div className="freeze-request__field">
          <label htmlFor={ids.until} className="join-requests__label">
            {copy.until}
          </label>
          <Input
            id={ids.until}
            type="date"
            min={addDays(fromOk ? from : today, 1)}
            value={until}
            aria-invalid={checked && !untilOk}
            aria-describedby={ids.hint}
            onChange={(e) => setUntil(e.target.value)}
          />
        </div>
      </div>
      <p id={ids.hint} className="join-requests__hint">
        {copy.datesHint}
      </p>
      {checked && !fromOk && (
        <p className="join-requests__error" role="alert">
          {copy.fromNeeded}
        </p>
      )}
      {checked && !untilOk && (
        <p className="join-requests__error" role="alert">
          {copy.untilNeeded}
        </p>
      )}
      {approve.error && (
        <p className="join-requests__error" role="alert">
          {refusedOrFailed(approve.error)}
        </p>
      )}
      <div className="join-requests__actions">
        <Button disabled={approve.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={approve.isPending} busy={approve.isPending}>
          {approve.isPending ? copy.working : copy.confirmApprove}
        </Button>
      </div>
    </form>
  )
}

function RejectForm({
  request,
  onCancel,
  onDone,
}: {
  request: FreezeRequest
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const refresh = useAnswered()
  const noteId = useId()
  const [note, setNote] = useState('')

  const reject = useSubmit({
    offline: 'refuse',
    mutationFn: () => rejectFreezeRequest(request.id, note),
    onSuccess: async () => {
      onDone(copy.rejected(request.person_name))
      await refresh()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    reject.mutate()
  }

  return (
    <form className="freeze-request__form" aria-label={copy.rejectLabel(request.person_name)} onSubmit={submit}>
      <label htmlFor={noteId} className="join-requests__label">
        {copy.note}
      </label>
      <Textarea id={noteId} rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      {reject.error && (
        <p className="join-requests__error" role="alert">
          {refusedOrFailed(reject.error)}
        </p>
      )}
      <div className="join-requests__actions">
        <Button disabled={reject.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="danger" disabled={reject.isPending} busy={reject.isPending}>
          {reject.isPending ? copy.working : copy.confirmReject}
        </Button>
      </div>
    </form>
  )
}

/** A 409 or 422 is the freeze refused as "Congelar" would refuse it; anything else, a retry. */
function refusedOrFailed(error: Error): string {
  return error instanceof ApiError && (error.status === 409 || error.status === 422) ? copy.refused : copy.failed
}
