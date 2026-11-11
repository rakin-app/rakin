import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { blockKindsQuery, type BlockKind } from '../api/blockKinds'
import {
  MAX_BLOCK_SECONDS,
  MAX_BLOCKS,
  MAX_ROUND_SECONDS,
  MAX_ROUNDS,
  newId,
  recordActual,
  replacePlan,
  sessionPlanQuery,
  sparredAtMost,
  usePendingSync,
  type BlockActual,
  type PlannedBlock,
  type SessionBlock,
  type SessionPlan,
} from '../api/sessionBlocks'
import type { ClassSession } from '../api/sessions'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { CloseIcon } from '../components/icons'
import { t } from '../i18n/es'
import { savedRun } from './timerEngine'
import { useSubmit } from '../api/submit'

const copy = t.admin.session.record
const timerCopy = t.admin.timer

// A sparring block added here starts from the timer's open mat rounds.
const NEW_SPARRING = { rounds: '6', roundMinutes: '5', restSeconds: 60 }

/** A block as typed, what it ran included: numbers as text, checked on save. */
type Draft = {
  id: string
  kindId: string
  minutes: string
  rounds: string
  roundMinutes: string
  completed: string
  // Kept as they were: the plan's seconds of a block that is not sparring, and the rest
  // between rounds. Neither is what ran.
  plannedSeconds: number | null
  restSeconds: number
}

type Field = 'minutes' | 'rounds' | 'roundMinutes' | 'completed'

const asMinutes = (seconds: number | null) => (seconds === null ? '' : String(Math.round(seconds / 6) / 10))
const number = (text: string) => (text.trim() === '' ? NaN : Number(text.replace(',', '.').trim()))

function draftOf(block: SessionBlock): Draft {
  return {
    id: block.id,
    kindId: block.block_kind_id,
    minutes: asMinutes(block.actual_seconds ?? 0),
    rounds: block.rounds_planned === null ? '' : String(block.rounds_planned),
    roundMinutes: asMinutes(block.round_seconds),
    completed: block.rounds_completed === null ? (block.is_sparring ? '0' : '') : String(block.rounds_completed),
    plannedSeconds: block.is_sparring ? null : block.planned_seconds,
    restSeconds: block.rest_seconds ?? NEW_SPARRING.restSeconds,
  }
}

function newDraft(kind: BlockKind | undefined): Draft {
  const sparring = kind?.is_sparring ?? false
  return {
    id: newId(),
    kindId: kind?.id ?? '',
    minutes: '',
    rounds: sparring ? NEW_SPARRING.rounds : '',
    roundMinutes: sparring ? NEW_SPARRING.roundMinutes : '',
    completed: sparring ? '0' : '',
    plannedSeconds: null,
    restSeconds: NEW_SPARRING.restSeconds,
  }
}

/** The draft as the plan's block and what it ran, or the fields that are wrong. */
function blockOf(draft: Draft, kind: BlockKind | undefined): { plan: PlannedBlock; actual: BlockActual } | Set<Field> {
  const wrong = new Set<Field>()
  if (!kind) return wrong
  const actual = Math.round(number(draft.minutes) * 60)
  const ranOk = actual >= 0 && actual <= MAX_BLOCK_SECONDS
  if (!kind.is_sparring) {
    if (!ranOk) return new Set(['minutes'])
    return {
      plan: {
        id: draft.id,
        block_kind_id: kind.id,
        // A block added here was planned as long as it ran, a minute at least.
        planned_seconds: draft.plannedSeconds ?? Math.max(actual, 60),
        rounds_planned: null,
        round_seconds: null,
        rest_seconds: null,
      },
      actual: { actual_seconds: actual, rounds_completed: null },
    }
  }
  const rounds = number(draft.rounds)
  const roundSeconds = Math.round(number(draft.roundMinutes) * 60)
  const completed = number(draft.completed)
  if (!(Number.isInteger(rounds) && rounds >= 1 && rounds <= MAX_ROUNDS)) wrong.add('rounds')
  if (!(roundSeconds >= 1 && roundSeconds <= MAX_ROUND_SECONDS)) wrong.add('roundMinutes')
  if (wrong.size === 0 && rounds * roundSeconds > MAX_BLOCK_SECONDS) wrong.add('rounds')
  if (!(Number.isInteger(completed) && completed >= 0 && (wrong.has('rounds') || completed <= rounds))) {
    wrong.add('completed')
  }
  // The rounds' own time, rest excluded: the API's bound.
  if (!ranOk || (wrong.size === 0 && actual > sparredAtMost(completed, rounds, roundSeconds))) wrong.add('minutes')
  if (wrong.size > 0) return wrong
  return {
    plan: {
      id: draft.id,
      block_kind_id: kind.id,
      planned_seconds: null,
      rounds_planned: rounds,
      round_seconds: roundSeconds,
      rest_seconds: draft.restSeconds,
    },
    actual: { actual_seconds: actual, rounds_completed: completed },
  }
}

/** What a block ran, as the timer's end screen says it. */
function ran(block: SessionBlock): string {
  if (block.actual_seconds === null) return timerCopy.done.notRun
  if (!block.is_sparring) return timerCopy.minutes(block.actual_seconds)
  return timerCopy.done.rounds(
    block.rounds_completed ?? 0,
    block.rounds_planned ?? 0,
    timerCopy.minutes(block.actual_seconds),
  )
}

/**
 * "Registro del timer": what each block of a class that has begun ran, and "Editar
 * registro" to correct it after: each block's kind, its minutes and, for sparring, its
 * rounds; blocks added and removed. It goes through the timer's own two writes, the plan
 * then what each block ran, held to their rules. For who may run the class's timer.
 */
export function TimerRecord({ session }: { session: ClassSession }) {
  const plan = useQuery(sessionPlanQuery(session.id))
  const kinds = useQuery(blockKindsQuery)
  const pending = usePendingSync(session.id)
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)

  if (plan.isPending || kinds.isPending || plan.isError || kinds.isError) return null
  // The timer on this phone writes the plan as it runs: a correction meanwhile would be
  // overwritten by its next write.
  const run = savedRun(session.id)
  const busy = run !== null && run.endedAt === null ? copy.running : pending ? copy.pending : null
  const blocks = plan.data.blocks

  return (
    <section className="classes__section" aria-labelledby="timer-record">
      <h2 id="timer-record" className="classes__section-title">
        {copy.title}
      </h2>
      {editing ? (
        <RecordEditor
          plan={plan.data}
          kinds={kinds.data}
          onClose={(done) => {
            setSaved(done)
            setEditing(false)
          }}
        />
      ) : (
        <>
          {blocks.length === 0 ? (
            <p className="classes__note">{copy.empty}</p>
          ) : (
            <ul className="classes__list" aria-label={copy.title}>
              {blocks.map((block) => (
                <li key={block.id} className="classes__row timer-done__row">
                  <span className="classes__name">{block.block_kind_name}</span>
                  <span className="classes__detail">{ran(block)}</span>
                </li>
              ))}
            </ul>
          )}
          {saved && (
            <p className="classes__done" role="status">
              {copy.saved}
            </p>
          )}
          {busy ? (
            <p className="classes__note">{busy}</p>
          ) : (
            <Button
              onClick={() => {
                setSaved(false)
                setEditing(true)
              }}
            >
              {copy.edit}
            </Button>
          )}
        </>
      )}
    </section>
  )
}

function RecordEditor({
  plan,
  kinds,
  onClose,
}: {
  plan: SessionPlan
  kinds: BlockKind[]
  onClose: (saved: boolean) => void
}) {
  const queryClient = useQueryClient()
  const openMat = plan.class_kind === 'open_mat'
  const [drafts, setDrafts] = useState(() => plan.blocks.map(draftOf))
  const [checked, setChecked] = useState(false)
  const byId = new Map(kinds.map((k) => [k.id, k]))
  // The kinds not archived, and an archived one a block already is of.
  const choices = kinds.filter(
    (k) => (!k.archived || plan.blocks.some((b) => b.block_kind_id === k.id)) && (!openMat || k.is_sparring),
  )
  const firstKind = choices.find((k) => !k.archived && !k.is_sparring) ?? choices.find((k) => !k.archived)
  const built = drafts.map((d) => blockOf(d, byId.get(d.kindId)))
  const valid = built.every((b) => !(b instanceof Set))
  const full = drafts.length >= MAX_BLOCKS
  // An open mat is one sparring block: added if it has none, never removed.
  const canAdd = !full && choices.length > 0 && (!openMat || drafts.length === 0)

  const save = useSubmit({
    mutationFn: async (blocks: { plan: PlannedBlock; actual: BlockActual }[]) => {
      // The plan first: a block given another kind starts unrecorded, and a new one
      // must be there before what it ran is.
      await replacePlan(
        plan.session_id,
        blocks.map((b) => b.plan),
      )
      for (const block of blocks) await recordActual(plan.session_id, block.plan.id, block.actual)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'blocks', plan.session_id] })
      // Everyone present gets the class's time: theirs changed.
      void queryClient.invalidateQueries({ queryKey: ['time'] })
    },
    onSuccess: () => onClose(true),
  })

  const change = (index: number, update: Partial<Draft>) =>
    setDrafts((all) => all.map((d, i) => (i === index ? { ...d, ...update } : d)))
  const kindChanged = (index: number, kindId: string) => {
    const draft = drafts[index]!
    const was = byId.get(draft.kindId)?.is_sparring ?? false
    const kind = byId.get(kindId)
    // Turned sparring or back, the block starts from that shape, its minutes kept.
    if (kind && kind.is_sparring !== was) change(index, { ...newDraft(kind), id: draft.id, minutes: draft.minutes })
    else change(index, { kindId })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!valid) return
    save.mutate(built as { plan: PlannedBlock; actual: BlockActual }[])
  }

  return (
    <form className="timer-editor" aria-label={copy.label} onSubmit={submit}>
      <p className="classes__note">{copy.hint}</p>
      {choices.length === 0 && (
        <p className="classes__error" role="alert">
          {copy.noKinds}
        </p>
      )}
      <ol className="timer-editor__list">
        {drafts.map((draft, index) => (
          <li key={draft.id}>
            <RecordCard
              draft={draft}
              number={index + 1}
              kind={byId.get(draft.kindId)}
              choices={choices}
              removable={!openMat}
              wrong={checked && built[index] instanceof Set ? (built[index] as Set<Field>) : new Set()}
              onKind={(kindId) => kindChanged(index, kindId)}
              onChange={(update) => change(index, update)}
              onRemove={() => setDrafts((all) => all.filter((_, i) => i !== index))}
            />
          </li>
        ))}
      </ol>
      {full && <p className="classes__note">{copy.tooMany(MAX_BLOCKS)}</p>}
      {canAdd && (
        <Button fullWidth onClick={() => setDrafts((all) => [...all, newDraft(openMat ? choices[0] : firstKind)])}>
          {copy.add}
        </Button>
      )}
      {checked && !valid && (
        <p className="classes__error" role="alert">
          {copy.invalid}
        </p>
      )}
      {save.isError && (
        <p className="classes__error" role="alert">
          {copy.failed}
        </p>
      )}
      <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
        {save.isPending ? copy.working : copy.submit}
      </Button>
      <Button onClick={() => onClose(false)}>
        {copy.close}
      </Button>
    </form>
  )
}

function RecordCard({
  draft,
  number: n,
  kind,
  choices,
  removable,
  wrong,
  onKind,
  onChange,
  onRemove,
}: {
  draft: Draft
  number: number
  kind: BlockKind | undefined
  choices: BlockKind[]
  removable: boolean
  wrong: Set<Field>
  onKind: (kindId: string) => void
  onChange: (update: Partial<Draft>) => void
  onRemove: () => void
}) {
  const id = useId()
  const input = (field: Field, label: string, mode: 'numeric' | 'decimal') => (
    <div className="timer-editor__field">
      <label htmlFor={`${id}-${field}`} className="classes__label">
        {label}
      </label>
      <Input
        id={`${id}-${field}`}
        inputMode={mode}
        value={draft[field]}
        aria-invalid={wrong.has(field) || undefined}
        onChange={(e) => onChange({ [field]: e.target.value })}
      />
    </div>
  )
  return (
    <fieldset className="classes__card timer-editor__card">
      <legend className="visually-hidden">{copy.block(n)}</legend>
      <div className="timer-editor__head">
        <span className="classes__section-title" aria-hidden="true">
          {copy.block(n)}
        </span>
        {removable && (
          <span className="timer-editor__actions">
            <Button icon aria-label={copy.remove(n)} onClick={onRemove}>
              <CloseIcon />
            </Button>
          </span>
        )}
      </div>
      <label htmlFor={`${id}-kind`} className="classes__label">
        {copy.kind}
      </label>
      <Select id={`${id}-kind`} value={draft.kindId} onChange={(e) => onKind(e.target.value)}>
        {choices.map((k) => (
          <option key={k.id} value={k.id}>
            {k.name}
          </option>
        ))}
      </Select>
      {kind?.is_sparring ? (
        <div className="timer-editor__rounds">
          {input('rounds', copy.rounds, 'numeric')}
          {input('roundMinutes', copy.roundMinutes, 'decimal')}
          {input('completed', copy.completed, 'numeric')}
          {input('minutes', copy.minutes, 'decimal')}
        </div>
      ) : (
        input('minutes', copy.minutes, 'decimal')
      )}
    </fieldset>
  )
}
