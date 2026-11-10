import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'
import { ApiError } from '../api/client'
import {
  ageOn,
  approveJoinRequest,
  joinRequestsQuery,
  rejectJoinRequest,
  type JoinRequest,
} from '../api/join'
import { managesGym, myRoleQuery } from '../api/me'
import { plansQuery, type Plan } from '../api/plans'
import { useGymTimeZone, useGymToday } from '../api/sessions'
import { isoDay } from '../format'
import { t } from '../i18n/es'
import './JoinRequests.css'

const copy = t.admin.joinRequests

/**
 * "Solicitudes (N)": who filled in the gym's join link and waits for staff (#154), on
 * Hoy and in Alumnos, for every staff role. Each says whether its phone or RUT is
 * someone's in this gym already. "Aprobar" adds the person; an owner or admin may give
 * them a plan as they do, a coach may not, since a plan is money. "Rechazar" deletes
 * the request. Nothing shows while the queue is empty, nor when it fails to load: it
 * is there to bring requests to staff's attention, and the page it sits on carries on.
 */
export function JoinRequests() {
  const requests = useQuery(joinRequestsQuery)
  const role = useQuery(myRoleQuery())
  const managers = managesGym(role.data)
  const plans = useQuery({ ...plansQuery, enabled: managers })
  const [notice, setNotice] = useState<string | null>(null)
  const titleId = useId()

  if (!requests.data || (requests.data.total === 0 && notice === null)) return null
  const { items, total } = requests.data

  // A plan someone can be started on: active, and not a drop-in, which is no membership.
  const choices = (plans.data ?? []).filter((plan) => plan.active && plan.kind !== 'dropin')

  return (
    <section className="join-requests" aria-labelledby={titleId}>
      <h2 id={titleId} className="join-requests__title">
        {copy.title(total)}
      </h2>
      {items.length < total && <p className="join-requests__hint">{copy.oldestShown(items.length)}</p>}
      {notice && (
        <p className="join-requests__done" role="status">
          {notice}
        </p>
      )}
      <ul className="join-requests__list">
        {items.map((request) => (
          <RequestRow
            key={request.id}
            request={request}
            plans={managers ? choices : null}
            onDone={setNotice}
          />
        ))}
      </ul>
    </section>
  )
}

function RequestRow({
  request,
  plans,
  onDone,
}: {
  request: JoinRequest
  // The plans to offer; `null` for a coach, who approves with none.
  plans: Plan[] | null
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const name = `${request.first_name} ${request.last_name}`
  const [planId, setPlanId] = useState('')
  const [confirming, setConfirming] = useState(false)
  const planFieldId = useId()
  const today = useGymToday()
  const sentOn = isoDay(request.created_at, useGymTimeZone())

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: joinRequestsQuery.queryKey })
    await queryClient.invalidateQueries({ queryKey: ['members'] })
  }
  const approve = useMutation({
    mutationFn: () => approveJoinRequest(request.id, planId || null),
    onSuccess: async () => {
      onDone(copy.approved(name))
      await refresh()
    },
  })
  const reject = useMutation({
    mutationFn: () => rejectJoinRequest(request.id),
    onSuccess: async () => {
      onDone(copy.rejected(name))
      await refresh()
    },
  })
  const pending = approve.isPending || reject.isPending
  const failed = approve.error ?? reject.error
  const age = ageOn(request.dob, today)
  // A request for the link's program offers that program's plans first.
  const ordered = plans && [
    ...plans.filter((plan) => plan.program_id === request.program_id && request.program_id !== null),
    ...plans.filter((plan) => plan.program_id !== request.program_id || request.program_id === null),
  ]

  return (
    <li className="join-requests__row" aria-label={name}>
      <div className="join-requests__text">
        <span className="join-requests__name">{name}</span>
        <span className="join-requests__detail">
          {[request.rut && t.common.rut(request.rut), age === null ? null : copy.age(age)].filter(Boolean).join(' · ')}
        </span>
        <span className="join-requests__detail">
          {[request.phone, request.email, request.no_whatsapp && !request.guardian ? copy.noWhatsapp : null]
            .filter(Boolean)
            .join(' · ')}
        </span>
        {request.guardian && (
          <span className="join-requests__detail">
            {[
              copy.guardian(request.guardian.name),
              request.guardian.phone,
              request.guardian.email,
              request.no_whatsapp ? copy.noWhatsapp : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        )}
        {request.program_name && <span className="join-requests__detail">{copy.program(request.program_name)}</span>}
        <span className="join-requests__detail">{copy.sent(t.common.longDay(sentOn))}</span>
        {request.email_in_gym && (
          <Link
            to="/admin/alumnos/$personId"
            params={{ personId: request.email_in_gym.id }}
            className="join-requests__warning"
          >
            {copy.emailInGym(request.email_in_gym.name)}
          </Link>
        )}
        {request.ignored_email && (
          <span className="join-requests__warning">{copy.ignoredEmail(request.ignored_email)}</span>
        )}
        {request.rut_in_gym && (
          <Link
            to="/admin/alumnos/$personId"
            params={{ personId: request.rut_in_gym.id }}
            className="join-requests__warning"
          >
            {copy.rutInGym(request.rut_in_gym.name)}
          </Link>
        )}
      </div>
      {ordered ? (
        <div className="join-requests__field">
          <label htmlFor={planFieldId} className="join-requests__label">
            {copy.plan}
          </label>
          <select
            id={planFieldId}
            className="join-requests__input"
            value={planId}
            disabled={pending}
            onChange={(event) => setPlanId(event.target.value)}
          >
            <option value="">{copy.noPlan}</option>
            {ordered.map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.name}
              </option>
            ))}
          </select>
          {planId === '' && <p className="join-requests__hint">{copy.planHint}</p>}
        </div>
      ) : (
        <p className="join-requests__hint">{copy.coachHint}</p>
      )}
      {failed && (
        <p className="join-requests__error" role="alert">
          {refusalOf(failed)}
        </p>
      )}
      {confirming ? (
        <div className="join-requests__confirm" role="group" aria-label={copy.confirmReject(name)}>
          <p className="join-requests__detail">{copy.confirmReject(name)}</p>
          <div className="join-requests__actions">
            <button type="button" className="join-requests__button" disabled={pending} onClick={() => setConfirming(false)}>
              {copy.cancel}
            </button>
            <button
              type="button"
              className="join-requests__button join-requests__button--primary"
              disabled={pending}
              onClick={() => reject.mutate()}
            >
              {copy.confirm}
            </button>
          </div>
        </div>
      ) : (
        <div className="join-requests__actions">
          <button
            type="button"
            className="join-requests__button"
            aria-label={copy.rejectLabel(name)}
            disabled={pending}
            onClick={() => setConfirming(true)}
          >
            {copy.reject}
          </button>
          <button
            type="button"
            className="join-requests__button join-requests__button--primary"
            aria-label={copy.approveLabel(name)}
            disabled={pending}
            onClick={() => approve.mutate()}
          >
            {approve.isPending ? copy.working : copy.approve}
          </button>
        </div>
      )}
    </li>
  )
}

/** What a refused approval means: a member already (approve with no plan), someone dado de
 * baja (reactivate them first, #157), a family link the gym cannot make. */
function refusalOf(error: Error): string {
  if (!(error instanceof ApiError) || error.status !== 409) return copy.failed
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  if (code === 'has_membership') return copy.hasMembership
  return code === 'has_left' ? copy.hasLeft : copy.family
}
