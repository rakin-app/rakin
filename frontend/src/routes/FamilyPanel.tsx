import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useState, type FormEvent } from 'react'
import { ApiError, apiFetch } from '../api/client'
import {
  addDependent,
  familyConflict,
  familyQuery,
  removeDependent,
  type AddDependent,
  type PersonRef,
} from '../api/family'
import { membersPath, type MemberPage } from '../api/people'
import { t } from '../i18n/es'

const copy = t.admin.family

// Typing waits this long before it becomes a search, as on the list.
const SEARCH_DEBOUNCE_MS = 250
// How many matches the link search offers.
const MATCHES = 5

/** A person's guardian or dependents, and the forms that change them. */
export function FamilyPanel({ person }: { person: PersonRef }) {
  const family = useQuery(familyQuery(person.id))
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['people'] })

  const add = useMutation({
    mutationFn: (body: AddDependent) => addDependent(person.id, body),
    onSuccess: invalidate,
  })
  const unlink = useMutation({
    mutationFn: ({ guardian, dependent }: { guardian: string; dependent: string }) =>
      removeDependent(guardian, dependent),
    onSuccess: invalidate,
  })
  const failed = add.error ?? unlink.error

  if (family.isPending) return <p className="family__note">{copy.loading}</p>
  if (family.isError) {
    return (
      <p className="family__note" role="alert">
        {copy.error}
      </p>
    )
  }

  const { guardian, dependents } = family.data
  return (
    <div className="family">
      {failed && (
        <p className="family__error" role="alert">
          {refusal(failed)}
        </p>
      )}
      {guardian ? (
        <section className="family__section">
          <h3 className="family__title">{copy.guardian}</h3>
          <ul className="family__list">
            <Linked
              person={guardian}
              disabled={unlink.isPending}
              onUnlink={() => unlink.mutate({ guardian: guardian.id, dependent: person.id })}
            />
          </ul>
        </section>
      ) : (
        <>
          <section className="family__section">
            <h3 className="family__title">{copy.dependents}</h3>
            {dependents.length === 0 ? (
              <p className="family__hint">{copy.none}</p>
            ) : (
              <ul className="family__list">
                {dependents.map((dependent) => (
                  <Linked
                    key={dependent.id}
                    person={dependent}
                    disabled={unlink.isPending}
                    onUnlink={() => unlink.mutate({ guardian: person.id, dependent: dependent.id })}
                  />
                ))}
              </ul>
            )}
          </section>
          <NewDependentForm busy={add.isPending} onAdd={(body) => add.mutateAsync(body)} />
          <LinkExisting
            exclude={[person.id, ...dependents.map((d) => d.id)]}
            busy={add.isPending}
            onLink={(id) => add.mutate({ person_id: id })}
          />
        </>
      )}
    </div>
  )
}

function refusal(error: unknown): string {
  const conflict = familyConflict(error)
  if (conflict) return copy.refused[conflict]
  if (error instanceof ApiError && error.status === 422) return copy.refused.invalid
  return copy.refused.failed
}

function Linked({ person, disabled, onUnlink }: { person: PersonRef; disabled: boolean; onUnlink: () => void }) {
  return (
    <li className="family__person">
      <span>{person.name}</span>
      <button
        type="button"
        className="family__action"
        aria-label={copy.unlinkLabel(person.name)}
        disabled={disabled}
        onClick={onUnlink}
      >
        {copy.unlink}
      </button>
    </li>
  )
}

function NewDependentForm({ busy, onAdd }: { busy: boolean; onAdd: (body: AddDependent) => Promise<unknown> }) {
  const [name, setName] = useState('')
  const [rut, setRut] = useState('')
  const [dob, setDob] = useState('')
  const ids = { name: useId(), rut: useId(), dob: useId() }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const body = { name: name.trim(), ...(rut.trim() && { rut: rut.trim() }), ...(dob && { dob }) }
    // Cleared once saved; a refusal keeps what was typed, to fix and send again.
    onAdd(body).then(
      () => {
        setName('')
        setRut('')
        setDob('')
      },
      () => {},
    )
  }

  return (
    <form className="family__section family__form" onSubmit={submit}>
      <h3 className="family__title">{copy.addTitle}</h3>
      <p className="family__hint">{copy.addHint}</p>
      <label htmlFor={ids.name}>{copy.name}</label>
      <input id={ids.name} className="family__input" required value={name} onChange={(e) => setName(e.target.value)} />
      <label htmlFor={ids.rut}>{copy.rut}</label>
      <input id={ids.rut} className="family__input" value={rut} onChange={(e) => setRut(e.target.value)} />
      <label htmlFor={ids.dob}>{copy.dob}</label>
      <input id={ids.dob} className="family__input" type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
      <button type="submit" className="students__button" disabled={busy || !name.trim()}>
        {copy.add}
      </button>
    </form>
  )
}

function LinkExisting({
  exclude,
  busy,
  onLink,
}: {
  exclude: string[]
  busy: boolean
  onLink: (personId: string) => void
}) {
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setQ(draft.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draft])

  const matches = useQuery({
    queryKey: ['people', 'link-search', q],
    queryFn: () => apiFetch<MemberPage>(membersPath({ q, status: [], plan: [] }, 0)),
    enabled: q !== '',
    select: (data) =>
      data.items
        // Someone with a guardian is taken; a guardian cannot be a dependent.
        .filter((row) => !exclude.includes(row.id) && !row.guardian && row.dependents === 0)
        .slice(0, MATCHES),
  })
  const searchId = useId()

  return (
    <section className="family__section">
      <h3 className="family__title">{copy.linkTitle}</h3>
      <label htmlFor={searchId} className="visually-hidden">
        {copy.linkSearch}
      </label>
      <input
        id={searchId}
        type="search"
        className="family__input"
        placeholder={copy.linkSearch}
        autoComplete="off"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      {q !== '' && matches.data && (
        matches.data.length === 0 ? (
          <p className="family__hint">{copy.noMatches}</p>
        ) : (
          <ul className="family__list" aria-label={copy.linkSearch}>
            {matches.data.map((row) => (
              <li key={row.id} className="family__person">
                <span>{row.name}</span>
                <button
                  type="button"
                  className="family__action"
                  aria-label={copy.linkLabel(row.name)}
                  disabled={busy}
                  onClick={() => onLink(row.id)}
                >
                  {copy.link}
                </button>
              </li>
            ))}
          </ul>
        )
      )}
    </section>
  )
}
