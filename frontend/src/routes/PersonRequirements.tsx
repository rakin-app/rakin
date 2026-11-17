import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import type { Person } from '../api/member'
import {
  personRequirementsQuery,
  recordRequirement,
  type PersonRequirement,
} from '../api/requirements'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Banner, Card, PlainList, SectionHeader } from '../components/Card'
import { Field, Input, Textarea } from '../components/Field'
import { requirementDates, RequirementPill } from '../components/RequirementState'
import { t } from '../i18n/es'
import { HISTORY_WINDOW_YEARS, yearsBefore } from './historyWindow'
import './PersonRequirements.css'

const copy = t.admin.member.requirements
const form = copy.form

/**
 * "Requisitos" (#349): each of the gym's active requirements the signed-in role sees, a
 * waiver, an induction, a medical certificate, as al día (with its dates), vence pronto
 * (within 30 days), vencido or pendiente, and "Registrar" on each: the day it was done,
 * today unless back-dated, and a note. A record never changes; a new one replaces it.
 * Nothing shows when the gym asks for nothing, nor while it loads.
 */
export function PersonRequirements({ person }: { person: Person }) {
  const requirements = useQuery(personRequirementsQuery(person.id))
  const [recording, setRecording] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // Nothing while it loads, so a gym that asks for nothing never sees the card come and go.
  if (!requirements.isError && !requirements.data?.length) return null

  return (
    <section className="member__section" aria-label={copy.title}>
      <SectionHeader title={copy.title} />
      {notice && <Banner tone="done">{notice}</Banner>}
      <Card as="div" className="member__card">
        {requirements.isError && (
          <p className="member__note" role="alert">
            {copy.error}
          </p>
        )}
        {requirements.data && (
          <PlainList className="requirements__list">
            {requirements.data.map((requirement) => (
              <li key={requirement.id} className="requirements__item" aria-label={requirement.name}>
                <Row
                  requirement={requirement}
                  recording={recording === requirement.id}
                  onRecord={() => {
                    setNotice(null)
                    setRecording(requirement.id)
                  }}
                />
                {recording === requirement.id && (
                  <RecordForm
                    personId={person.id}
                    requirement={requirement}
                    onCancel={() => setRecording(null)}
                    onDone={() => {
                      setRecording(null)
                      setNotice(copy.recorded(requirement.name))
                    }}
                  />
                )}
              </li>
            ))}
          </PlainList>
        )}
      </Card>
    </section>
  )
}

function Row({
  requirement,
  recording,
  onRecord,
}: {
  requirement: PersonRequirement
  recording: boolean
  onRecord: () => void
}) {
  const dates = requirementDates(requirement, copy)
  return (
    <div className="requirements__row">
      <div className="requirements__text">
        <span className="requirements__name">{requirement.name}</span>
        {dates && <span className="member__detail">{dates}</span>}
        {requirement.note && <span className="member__detail requirements__note">{requirement.note}</span>}
      </div>
      <div className="requirements__end">
        <RequirementPill state={requirement.state} />
        {!recording && (
          <Button aria-label={copy.recordLabel(requirement.name)} onClick={onRecord}>
            {copy.record}
          </Button>
        )}
      </div>
    </div>
  )
}

function RecordForm({
  personId,
  requirement,
  onCancel,
  onDone,
}: {
  personId: string
  requirement: PersonRequirement
  onCancel: () => void
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const today = useGymToday()
  const [doneOn, setDoneOn] = useState(today)
  const [note, setNote] = useState('')
  const [checked, setChecked] = useState(false)
  const earliest = yearsBefore(today, HISTORY_WINDOW_YEARS)
  const dayOk = doneOn !== '' && doneOn <= today && doneOn >= earliest

  const save = useSubmit({
    mutationFn: () => recordRequirement(personId, requirement.id, { done_on: doneOn, note: note.trim() || null }),
    onSuccess: (answer) => {
      queryClient.setQueryData(personRequirementsQuery(personId).queryKey, answer)
      onDone()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (dayOk) save.mutate()
  }

  return (
    <form className="member__form requirements__form" aria-label={form.title(requirement.name)} onSubmit={submit} noValidate>
      <Field label={form.doneOn} hint={form.doneOnHint} error={checked && !dayOk ? form.future : undefined}>
        {(props) => (
          <Input
            {...props}
            type="date"
            min={earliest}
            max={today}
            value={doneOn}
            onChange={(e) => setDoneOn(e.target.value)}
          />
        )}
      </Field>
      <Field label={form.note} hint={form.noteHint}>
        {(props) => (
          <Textarea {...props} rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        )}
      </Field>
      {save.isError && <Banner tone="error">{form.failed}</Banner>}
      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
