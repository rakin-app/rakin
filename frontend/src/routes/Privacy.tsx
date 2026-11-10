import { useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { lastUpdated, privacyNoticeQuery, type PrivacyNotice } from '../api/privacy'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import './Privacy.css'

const copy = t.privacy
const route = getRouteApi('/privacidad')

/** The search `/privacidad` takes: the join link it was opened from, if any. */
export function validatePrivacySearch(search: Record<string, unknown>): { enlace?: string } {
  return typeof search.enlace === 'string' && search.enlace ? { enlace: search.enlace } : {}
}

/**
 * "Política de privacidad": a gym's privacy notice (#168), open to anyone. The text is
 * the template in `t.privacy`, filled in with what the gym set in Ajustes: who answers
 * for the data, what is kept and why, who else processes it, for how long, and how to
 * exercise one's rights. Which gym's is the API's to say (`privacyNoticeQuery`); the
 * join form names its link, for when it is on the shared host.
 */
export function Privacy() {
  const { enlace } = route.useSearch()
  const notice = useQuery(privacyNoticeQuery(enlace))

  if (notice.isPending) {
    return (
      <Shell>
        <p role="status">{copy.loading}</p>
      </Shell>
    )
  }
  if (notice.isError) {
    if (notice.error instanceof ApiError && notice.error.status === 404) {
      return (
        <Shell>
          <p role="alert">{copy.missing}</p>
        </Shell>
      )
    }
    return (
      <Shell>
        <p role="alert">{copy.error}</p>
        <button type="button" className="privacy__button" onClick={() => void notice.refetch()}>
          {copy.retry}
        </button>
      </Shell>
    )
  }
  return (
    <Shell title={copy.title(notice.data.gym)}>
      <NoticeText notice={notice.data} />
    </Shell>
  )
}

function Shell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="privacy">
      <PageHeader eyebrow={copy.eyebrow} title={title ?? t.app.name} />
      <div className="privacy__card">{children}</div>
    </div>
  )
}

function NoticeText({ notice }: { notice: PrivacyNotice }) {
  const email = (
    <a className="privacy__link" href={`mailto:${notice.email}`}>
      {notice.email}
    </a>
  )
  return (
    <article className="privacy__text">
      <p className="privacy__updated">{copy.updated(t.common.longDayYear(lastUpdated(notice)))}</p>

      <h2 className="privacy__heading">{copy.controllerTitle}</h2>
      <p>
        {copy.controller(notice.legal_name, t.common.rut(notice.rut), notice.gym)}
        {notice.address && <> {copy.address(notice.address)}</>}
      </p>
      <p>
        {copy.contactBefore}
        {email}
        {copy.contactAfter}
      </p>

      <h2 className="privacy__heading">{copy.dataTitle}</h2>
      <List items={copy.data} />

      <h2 className="privacy__heading">{copy.purposeTitle}</h2>
      <List items={copy.purpose} />
      <p>{copy.purposeAfter}</p>

      <h2 className="privacy__heading">{copy.basisTitle}</h2>
      <p>{copy.basis}</p>

      <h2 className="privacy__heading">{copy.processorsTitle}</h2>
      <p>{copy.processors}</p>
      <List items={copy.subprocessors} />
      <p>{copy.processorsAfter}</p>

      <h2 className="privacy__heading">{copy.retentionTitle}</h2>
      <p>{copy.retention}</p>

      <h2 className="privacy__heading">{copy.rightsTitle}</h2>
      <p>{copy.rights}</p>
      <p>
        {copy.rightsHowBefore}
        {email}
        {copy.rightsHowAfter}
      </p>
      <p>{copy.complaint}</p>

      <p className="privacy__disclaimer">{copy.disclaimer}</p>
    </article>
  )
}

function List({ items }: { items: readonly string[] }) {
  return (
    <ul className="privacy__list">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}
