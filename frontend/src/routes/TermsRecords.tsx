import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { holdsAccount, myAccessQuery } from '../api/me'
import { termsCopyUrl, termsRecordsQuery, type TermsRecord } from '../api/terms'
import { cardClass, ListRowContent, listRowClass, PlainList, Section } from '../components/Card'
import { Loading } from '../components/Loading'
import { isoDay, longDay } from '../format'
import { t } from '../i18n/es'
import { LoadFailed } from './settingsForm'

const copy = t.terms

// Where the terms are accepted, and the copy's date read (`app.legal.terms.CHILE`).
const CHILE = 'America/Santiago'

/**
 * "Términos aceptados", in Ajustes › Gimnasio, for the titular alone (#499): every
 * acceptance of the gym's terms, the latest first, and for one made in the app a copy of
 * what was accepted, the same the confirmation email attached (#500, requirement 14).
 */
export function TermsRecords() {
  const access = useQuery(myAccessQuery())
  if (!holdsAccount(access.data)) return null
  return <Records />
}

function Records() {
  const records = useQuery(termsRecordsQuery())
  return (
    <Section id={useId()} title={copy.records}>
      <p className="settings__note">{copy.recordsHint}</p>
      {records.isPending ? (
        <Loading className="settings__note">{copy.recordsLoading}</Loading>
      ) : records.isError ? (
        <LoadFailed error={records.error} message={copy.recordsFailed} retry={() => void records.refetch()} />
      ) : records.data.length === 0 ? (
        <p className="settings__note">{copy.noRecords}</p>
      ) : (
        <PlainList className={cardClass({ flush: true })}>
          {records.data.map((record) => (
            <li key={record.id} className={listRowClass()}>
              <Record record={record} />
            </li>
          ))}
        </PlainList>
      )}
    </Section>
  )
}

function Record({ record }: { record: TermsRecord }) {
  const when =
    record.channel === 'in_app'
      ? copy.inApp(record.accepted_by_name, longDay(isoDay(record.accepted_at, CHILE)))
      : copy.outside(record.signed_on && longDay(record.signed_on))
  return (
    <ListRowContent
      title={when}
      detail={copy.versions(record.service_version, record.processor_version)}
      trailing={
        record.has_copy && (
          <a className="tap-link" href={termsCopyUrl(record.id)} download>
            {copy.download}
          </a>
        )
      }
    />
  )
}
