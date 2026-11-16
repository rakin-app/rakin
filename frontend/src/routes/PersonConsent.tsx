import { useQuery } from '@tanstack/react-query'
import { eventNoticeOn, personConsentQuery, type ConsentEvent } from '../api/consent'
import type { Person } from '../api/member'
import { Banner, Card, PlainList, SectionHeader } from '../components/Card'
import { Loading } from '../components/Loading'
import { isoDay } from '../format'
import { t } from '../i18n/es'

const copy = t.admin.member.consent

/**
 * "Privacidad" (#370): what the member's data rest on, the membership contract or, for
 * a minor, their guardian's consent, which is an act of its own and may be missing or
 * withdrawn with the membership as it is; and every act of the register, newest first,
 * with the version of the notice it names.
 */
export function PersonConsent({ person }: { person: Person }) {
  const consent = useQuery(personConsentQuery(person.id))

  return (
    <section className="member__section" aria-label={copy.title}>
      <SectionHeader title={copy.title} />
      <Card as="div" className="member__card">
        {consent.isPending && <Loading className="member__note">{copy.loading}</Loading>}
        {consent.isError && (
          <p className="member__note" role="alert">
            {copy.error}
          </p>
        )}
        {consent.data && (
          <>
            <p>{copy.basis[consent.data.basis]}</p>
            {consent.data.consent === 'given' && <Banner tone="done">{copy.given}</Banner>}
            {(consent.data.consent === 'missing' || consent.data.consent === 'withdrawn') && (
              <Banner tone="error" role="status">
                {copy[consent.data.consent]}
              </Banner>
            )}
            {consent.data.events.length > 0 ? (
              <PlainList className="member__detail">
                {consent.data.events.map((event, i) => (
                  <li key={i}>{line(event)}</li>
                ))}
              </PlainList>
            ) : (
              consent.data.basis === 'contract' && <p className="member__detail">{copy.none}</p>
            )}
          </>
        )}
      </Card>
    </section>
  )
}

function line(event: ConsentEvent): string {
  const by = event.by?.name ?? copy.someone
  const what =
    event.action === 'consent_given'
      ? copy.event.consent_given(by, event.source === 'page')
      : copy.event[event.action](by)
  const noticeOn = eventNoticeOn(event)
  const version =
    event.action === 'consent_withdrawn' ? '' : ` (${noticeOn ? copy.version(t.common.day(noticeOn)) : copy.noVersion})`
  return `${t.common.day(isoDay(event.at))}: ${what}${version}.`
}
