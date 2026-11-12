import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation } from '@tanstack/react-router'
import type { StaffRole } from '../api/me'
import type { Person } from '../api/member'
import { sendWelcome, welcomeQuery, WELCOME_WAIT_MS } from '../api/people'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { isoDay } from '../format'
import { t } from '../i18n/es'

const copy = t.admin.member.access

/**
 * "Acceso" (#246): where their sign-in link goes, theirs or their guardian's address,
 * whether the latest welcome was sent or failed, and "Enviar link para entrar", which
 * sends it again now, for someone added without it or imported. For the owner and
 * admins, and for someone still in the gym. Fresh from "Nuevo alumno" with the welcome
 * ticked, it waits a few seconds for it to be recorded.
 */
export function PersonWelcome({ person, role }: { person: Person; role: StaffRole | null | undefined }) {
  const manages = role === 'owner' || role === 'admin'
  const welcomeSince = useLocation({ select: (location) => location.state.welcomeSince ?? null })
  const state = useQuery({ ...welcomeQuery(person.id, welcomeSince), enabled: manages && !person.left_on })
  const queryClient = useQueryClient()
  const send = useSubmit({
    mutationFn: () => sendWelcome(person.id),
    onSuccess: (answer) => queryClient.setQueryData(welcomeQuery(person.id).queryKey, answer),
  })

  if (!manages || person.left_on || !state.data) return null
  const { to, guardian, last } = state.data
  // Still read again each second, as `welcomeQuery` does: by when it was last read.
  const waiting = last === null && welcomeSince !== null && state.dataUpdatedAt - welcomeSince < WELCOME_WAIT_MS
  const day = last && t.common.longDay(isoDay(last.sent_at))

  return (
    <section className="member__section" aria-label={copy.title}>
      <h2 className="member__section-title">{copy.title}</h2>
      <div className="member__card">
        {to === null ? (
          <p className="member__detail">{copy.noEmail}</p>
        ) : (
          <>
            <p className="member__detail">{guardian ? copy.toGuardian(guardian, to) : copy.to(to)}</p>
            {last?.status === 'failed' ? (
              <p className="member__error" role="alert">
                {copy.failed(day!)}
              </p>
            ) : (
              <p className={last ? 'member__done' : 'member__note'} role="status">
                {last ? copy.sent(day!) : waiting ? copy.waiting : copy.never}
              </p>
            )}
            {send.isError && (
              <p className="member__error" role="alert">
                {copy.error}
              </p>
            )}
            <div className="member__actions">
              <Button onClick={() => send.mutate()} disabled={send.isPending} busy={send.isPending}>
                {send.isPending ? copy.working : last?.status === 'sent' ? copy.resend : copy.send}
              </Button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
