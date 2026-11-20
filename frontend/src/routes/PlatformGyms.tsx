import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import {
  PLATFORM_GYM_PATH,
  PLATFORM_NEW_GYM_PATH,
  platformGymsQuery,
  resendOwnerLink,
  type PlatformGym,
} from '../api/platform'
import { useSubmit } from '../api/submit'
import { Button, buttonClass } from '../components/Button'
import { Card, CheckRow } from '../components/Card'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { StatusPill } from '../components/StatusPill'
import { shortDate } from '../format'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import { LoadFailed } from './settingsForm'
import './PlatformGyms.css'

const copy = t.platform.gyms

/**
 * "Gimnasios" (#436): every gym Rakin hosts, one row each, with where it is served, its
 * titular, the terms it accepted and whether they are the current ones (#499), how many
 * members and staff it has and when anything last happened there. Counts and dates
 * only: nobody's data but the titular's own contact. "Sin los términos vigentes" keeps
 * only the gyms whose titular has yet to accept them.
 */
export function PlatformGyms() {
  useDocumentTitle(copy.tab, t.platform.tab)
  const gyms = useQuery(platformGymsQuery())
  const [waiting, setWaiting] = useState(false)
  const shown = gyms.data?.filter((gym) => !waiting || gym.terms_state !== 'current')
  return (
    <>
      <PageHeader title={copy.title} eyebrow={gyms.data && copy.count(gyms.data.length)} />
      <div className="platform-gyms__actions">
        <Link to={PLATFORM_NEW_GYM_PATH} className={buttonClass({ variant: 'primary' })}>
          {copy.add}
        </Link>
        <CheckRow>
          <input type="checkbox" checked={waiting} onChange={(e) => setWaiting(e.target.checked)} />
          <span>{copy.withoutCurrentTerms}</span>
        </CheckRow>
      </div>
      {gyms.isPending ? (
        <Loading className="platform-gyms__note" role="status">
          {copy.loading}
        </Loading>
      ) : gyms.isError ? (
        <LoadFailed error={gyms.error} message={copy.failed} retry={() => void gyms.refetch()} />
      ) : gyms.data.length === 0 ? (
        <p className="platform-gyms__note">{copy.empty}</p>
      ) : shown?.length === 0 ? (
        <p className="platform-gyms__note">{copy.allCurrent}</p>
      ) : (
        <Card flush className="platform-gyms__scroll">
          <table className="platform-gyms__table">
            <thead>
              <tr>
                <th scope="col">{copy.columns.name}</th>
                <th scope="col">{copy.columns.address}</th>
                <th scope="col">{copy.columns.titular}</th>
                <th scope="col">{copy.columns.created}</th>
                <th scope="col">{copy.columns.terms}</th>
                <th scope="col" className="platform-gyms__count">
                  {copy.columns.members}
                </th>
                <th scope="col" className="platform-gyms__count">
                  {copy.columns.staff}
                </th>
                <th scope="col">{copy.columns.lastActivity}</th>
                <th scope="col">{copy.columns.status}</th>
              </tr>
            </thead>
            <tbody>
              {shown?.map((gym) => (
                <GymRow key={gym.id} gym={gym} />
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}

function GymRow({ gym }: { gym: PlatformGym }) {
  return (
    <tr>
      <th scope="row">
        <Link to={PLATFORM_GYM_PATH} params={{ gymId: gym.id }}>
          {gym.name}
        </Link>
      </th>
      <td>
        <a href={gym.address} target="_blank" rel="noreferrer">
          {new URL(gym.address).host}
        </a>
      </td>
      <td>
        {gym.titular_name ?? <span className="platform-gyms__muted">{copy.noTitular}</span>}
        {gym.titular_email && <span className="platform-gyms__muted platform-gyms__line">{gym.titular_email}</span>}
        {gym.owner_link_failed && <ResendLink gym={gym} />}
      </td>
      <td>{shortDate(gym.created_at)}</td>
      <td>
        <StatusPill status={TERMS_PILL[gym.terms_state]}>{copy.terms[gym.terms_state]}</StatusPill>
        {gym.terms_version !== null && (
          <span className="platform-gyms__muted platform-gyms__line">
            {gym.terms_accepted_at ? copy.accepted(gym.terms_version, shortDate(gym.terms_accepted_at)) : gym.terms_version}
          </span>
        )}
      </td>
      <td className="platform-gyms__count">{gym.members}</td>
      <td className="platform-gyms__count">{gym.staff}</td>
      <td>
        {gym.last_activity === null ? (
          <span className="platform-gyms__muted">{copy.noActivity}</span>
        ) : (
          shortDate(gym.last_activity)
        )}
      </td>
      <td>
        <StatusPill status={gym.status}>{copy.status[gym.status]}</StatusPill>
        {gym.suspended_at && (
          <span className="platform-gyms__muted platform-gyms__line">
            {copy.suspendedSince(shortDate(gym.suspended_at))}
          </span>
        )}
      </td>
    </tr>
  )
}

// The terms' state as a pill: settled once current, overdue while the titular has yet to
// accept them, whichever they last accepted.
const TERMS_PILL = { current: 'done', outdated: 'overdue', pending: 'overdue' } as const

/**
 * The titular's sign-in link did not go when the gym was created, or when last sent
 * (#437): said so, with the button that sends it again, the invitation to accept the
 * terms while they wait on them (#499).
 */
function ResendLink({ gym }: { gym: PlatformGym }) {
  const queryClient = useQueryClient()
  const resend = useSubmit({
    offline: 'refuse',
    mutationFn: () => resendOwnerLink(gym.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: platformGymsQuery().queryKey }),
  })
  const failed = resend.isError || resend.data?.sent === false
  return (
    <span className="platform-gyms__line platform-gyms__link">
      <StatusPill status="overdue">{copy.linkFailed}</StatusPill>
      <Button disabled={resend.isPending} busy={resend.isPending} onClick={() => resend.mutate()}>
        {resend.isPending ? copy.resending : gym.terms_state === 'current' ? copy.resend : copy.resendInvite}
      </Button>
      {failed && (
        <span className="platform-gyms__muted" role="alert">
          {copy.resendFailed}
        </span>
      )}
    </span>
  )
}
