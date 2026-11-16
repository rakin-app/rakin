import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  giveConsent,
  isStaleNotice,
  myConsentsQuery,
  withdrawConsent,
  type DependentConsent,
} from '../api/consent'
import { privacyNoticeQuery, privacyPath } from '../api/privacy'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Card, PlainList, Section } from '../components/Card'
import { isoDay } from '../format'
import { t } from '../i18n/es'

const copy = t.me.consent

/**
 * "Autorización de datos" (#370): for a guardian, each minor in their care whose data
 * rest on the guardian's consent, which they give or withdraw here, apart from the
 * inscription. Giving names the notice as the gym has it now; the API refuses one the
 * gym changed meanwhile, and the notice is loaded again. Nothing shows for anyone with
 * no such dependent.
 */
export function MyConsents() {
  const consents = useQuery(myConsentsQuery())
  if (!consents.data || consents.data.length === 0) return null

  return (
    <Section title={copy.title} id="my-consents">
      <p className="me-home__note">
        {copy.introBefore}
        <a href={privacyPath()} target="_blank" rel="noreferrer">
          {copy.link}
        </a>
        {copy.introAfter}
      </p>
      <PlainList>
        {consents.data.map((dependent) => (
          <DependentRow key={dependent.id} dependent={dependent} />
        ))}
      </PlainList>
    </Section>
  )
}

function DependentRow({ dependent }: { dependent: DependentConsent }) {
  const queryClient = useQueryClient()
  const notice = useQuery(privacyNoticeQuery())
  const done = () => queryClient.invalidateQueries({ queryKey: myConsentsQuery().queryKey })
  const send = useSubmit({
    offline: 'refuse',
    mutationFn: (): Promise<DependentConsent> => {
      if (dependent.consent === 'given') return withdrawConsent(dependent.id)
      if (!notice.data) throw new Error('the notice is not loaded')
      return giveConsent(dependent.id, notice.data)
    },
    onSuccess: done,
    onError: (error) => {
      if (isStaleNotice(error)) void queryClient.invalidateQueries({ queryKey: privacyNoticeQuery().queryKey })
    },
  })
  const day = dependent.at && t.common.day(isoDay(dependent.at))
  const state =
    dependent.consent === 'missing' || !day ? copy.missing : copy[dependent.consent](day)
  const given = dependent.consent === 'given'

  return (
    <Card as="li" aria-label={dependent.name}>
      <p>
        <strong>{dependent.name}</strong>
      </p>
      <p className="me-home__note" role="status">
        {state}
      </p>
      {send.isError && (
        <p className="me-home__note" role="alert">
          {isStaleNotice(send.error) ? copy.stale : copy.failed}
        </p>
      )}
      <Button
        variant={given ? undefined : 'primary'}
        disabled={send.isPending || (!given && !notice.data)}
        busy={send.isPending}
        onClick={() => send.mutate()}
      >
        {send.isPending ? copy.working : given ? copy.withdraw : copy.give}
      </Button>
    </Card>
  )
}
