import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { sessionQuery, todaySessionsQuery, updateSession, type ClassSession } from '../api/sessions'
import { ChevronLeftIcon } from '../components/icons'
import { clockTime } from '../format'
import { t } from '../i18n/es'
import './Classes.css'

const copy = t.admin.session

const route = getRouteApi('/admin/clases/$sessionId')

// The topic is one line and notes a few paragraphs: the backend's MAX_TOPIC and MAX_NOTES.
const MAX_TOPIC = 200
const MAX_NOTES = 4000

/**
 * One class: what it is, when it started and who teaches it, and its topic and notes,
 * written during or after class. The roster joins it with attendance (#44).
 */
export function SessionDetail() {
  const { sessionId } = route.useParams()
  const session = useQuery(sessionQuery(sessionId))
  // The gym's timezone, from the day's list; the browser's until it arrives.
  const today = useQuery(todaySessionsQuery())
  const timeZone = today.data?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone

  if (session.isPending) {
    return (
      <Shell>
        <p className="classes__note">{copy.loading}</p>
      </Shell>
    )
  }
  if (session.isError) {
    const missing = session.error instanceof ApiError && session.error.status === 404
    return (
      <Shell>
        <div className="classes__error" role="alert">
          <p>{missing ? copy.notFound : copy.error}</p>
          {!missing && (
            <button type="button" className="classes__button" onClick={() => void session.refetch()}>
              {copy.retry}
            </button>
          )}
        </div>
      </Shell>
    )
  }

  const data = session.data
  return (
    <Shell
      eyebrow={copy.eyebrow(data.program_name, clockTime(data.starts_at, timeZone))}
      title={data.class_type_name}
      subtitle={copy.coach(data.coach_name)}
    >
      <TopicForm key={data.id} session={data} />
    </Shell>
  )
}

function Shell({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow?: string
  title?: string
  subtitle?: string
  children: ReactNode
}) {
  return (
    <div className="classes">
      <header className="classes__header">
        <Link to="/admin/clases" className="classes__icon-button" aria-label={copy.back}>
          <ChevronLeftIcon />
        </Link>
        {title && (
          <div className="classes__heading">
            {eyebrow && <span className="classes__eyebrow">{eyebrow}</span>}
            <h1 className="classes__title">{title}</h1>
            {subtitle && <span className="classes__detail">{subtitle}</span>}
          </div>
        )}
      </header>
      <div className="classes__body">{children}</div>
    </div>
  )
}

function TopicForm({ session }: { session: ClassSession }) {
  const queryClient = useQueryClient()
  const topicId = useId()
  const notesId = useId()
  const [topic, setTopic] = useState(session.topic ?? '')
  const [notes, setNotes] = useState(session.notes ?? '')
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => updateSession(session.id, { topic, notes }),
    onSuccess: (updated) => {
      // As stored: trimmed, and blank as none.
      setTopic(updated.topic ?? '')
      setNotes(updated.notes ?? '')
      setSaved(true)
      queryClient.setQueryData(['sessions', 'detail', session.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
    },
  })
  // "Guardado" until the next edit.
  const changed = topic !== (session.topic ?? '') || notes !== (session.notes ?? '')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSaved(false)
    save.mutate()
  }

  return (
    <form className="classes__card classes__form" aria-label={copy.form.label} onSubmit={submit}>
      <label htmlFor={topicId} className="classes__label">
        {copy.form.topic}
      </label>
      <input
        id={topicId}
        className="classes__input"
        value={topic}
        maxLength={MAX_TOPIC}
        placeholder={copy.form.topicPlaceholder}
        onChange={(e) => setTopic(e.target.value)}
      />
      <label htmlFor={notesId} className="classes__label">
        {copy.form.notes}
      </label>
      <textarea
        id={notesId}
        className="classes__input classes__textarea"
        value={notes}
        maxLength={MAX_NOTES}
        rows={5}
        placeholder={copy.form.notesPlaceholder}
        onChange={(e) => setNotes(e.target.value)}
      />
      {save.isError && (
        <p className="classes__error" role="alert">
          {copy.form.failed}
        </p>
      )}
      {saved && !changed && (
        <p className="classes__done" role="status">
          {copy.form.saved}
        </p>
      )}
      <button type="submit" className="classes__button classes__button--primary" disabled={save.isPending}>
        {save.isPending ? copy.form.working : copy.form.submit}
      </button>
    </form>
  )
}
