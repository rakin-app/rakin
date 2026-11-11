import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  GOAL_METRICS,
  gradingPresetsQuery,
  gradingSchemeQuery,
  saveGradingScheme,
  type GoalMetric,
  type GradingPreset,
  type GradingScheme,
  type SchemeRank,
} from '../api/grading'
import { validationErrors } from '../api/validation'
import { Belt } from '../components/Belt'
import { Button } from '../components/Button'
import { ListRowContent, listRowClass } from '../components/Card'
import { Input, Select } from '../components/Field'
import { ChevronDownIcon, CloseIcon } from '../components/icons'
import { t } from '../i18n/es'
import { Field, integerOf, LoadFailed, MoveButtons, refusal } from './settingsForm'

const copy = t.admin.settings.grading
const LADDERS = ['ranks', 'kids_ladder'] as const
type Ladder = (typeof LADDERS)[number]

const EMPTY: GradingScheme = { ranks: [], kids_ladder: [], goal_metric: null }

// A rank or sub-rank as edited: its key is kept once it has one, since promotions name
// it; a new one is given its key on save. `id` is only React's.
type DraftSubRank = {
  id: number
  key: string | null
  label: string
  target: string
}
type DraftRank = DraftSubRank & { colors: string[]; sub_ranks: DraftSubRank[] }
type Draft = Record<Ladder, DraftRank[]> & { goal_metric: GoalMetric | null }

let nextId = 0
const blank = (): DraftSubRank => ({
  id: nextId++,
  key: null,
  label: '',
  target: '',
})

function draftOf(scheme: GradingScheme): Draft {
  const item = ({ key, label, target }: { key: string; label: string; target?: number | null }) => ({
    id: nextId++,
    key,
    label,
    target: target == null ? '' : String(target),
  })
  const ladder = (ranks: SchemeRank[]) =>
    ranks.map((r) => ({ ...item(r), colors: r.colors ?? [], sub_ranks: r.sub_ranks.map(item) }))
  return {
    ranks: ladder(scheme.ranks),
    kids_ladder: ladder(scheme.kids_ladder),
    goal_metric: scheme.goal_metric,
  }
}

/** A label as a key: lower-case ASCII, digits and single dashes, as the API takes them. */
function slug(label: string, fallback: string): string {
  const base = label
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)
    .replace(/-+$/, '')
  return base || fallback
}

/** A key not in `taken`, which it is then added to. */
function freshKey(label: string, fallback: string, taken: Set<string>): string {
  const base = slug(label, fallback)
  let key = base
  for (let n = 2; taken.has(key); n++) key = `${base}-${n}`
  taken.add(key)
  return key
}

/**
 * The draft as the API takes it. A rank's key is unique across both ladders, a
 * sub-rank's within its rank. With no goal metric there is nothing for a target to
 * count, so none is sent.
 */
function schemeOf(draft: Draft): GradingScheme {
  const target = (text: string) => (draft.goal_metric === null || text.trim() === '' ? null : integerOf(text))
  const rankKeys = new Set(LADDERS.flatMap((l) => draft[l].map((r) => r.key).filter((k) => k !== null)))
  const ladder = (ranks: DraftRank[]): SchemeRank[] =>
    ranks.map((rank) => {
      const subKeys = new Set(rank.sub_ranks.map((s) => s.key).filter((k) => k !== null))
      return {
        key: rank.key ?? freshKey(rank.label, 'grado', rankKeys),
        label: rank.label,
        target: target(rank.target) as number | null,
        colors: rank.colors,
        sub_ranks: rank.sub_ranks.map((sub) => ({
          key: sub.key ?? freshKey(sub.label, 'sub', subKeys),
          label: sub.label,
          target: target(sub.target) as number | null,
        })),
      }
    })
  return {
    ranks: ladder(draft.ranks),
    kids_ladder: ladder(draft.kids_ladder),
    goal_metric: draft.goal_metric,
  }
}

const isStale = (error: Error | null) =>
  error instanceof ApiError &&
  error.status === 409 &&
  (error.body as { detail?: { code?: string } } | undefined)?.detail?.code === 'grading_scheme_invalid'

/**
 * "Graduación": the gym's ranks, sub-ranks and kids ladder, lowest first, and what
 * "ready for promotion" counts. A preset is a starting point to edit; the scheme is
 * saved whole. One stored before a change to the model no longer reads, and the admin
 * repairs it by re-applying a preset.
 */
export function GradingSettings() {
  const scheme = useQuery(gradingSchemeQuery())
  const presets = useQuery(gradingPresetsQuery)

  if (scheme.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  const stale = isStale(scheme.error)
  if (scheme.isError && !stale) {
    return <LoadFailed error={scheme.error} message={copy.error} retry={() => void scheme.refetch()} />
  }
  return (
    <GradingEditor
      initial={scheme.data ?? EMPTY}
      stale={stale}
      presets={presets.data}
      presetsFailed={presets.isError}
    />
  )
}

function GradingEditor({
  initial,
  stale,
  presets,
  presetsFailed,
}: {
  initial: GradingScheme
  stale: boolean
  presets: GradingPreset[] | undefined
  presetsFailed: boolean
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(() => draftOf(initial))
  const [preset, setPreset] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  // The stored scheme stays broken until one is saved over it.
  const [repairing, setRepairing] = useState(stale)
  // The one rank open to edit, by its draft id (#177): the rest are a row each.
  const [opened, setOpened] = useState<number | null>(null)

  const save = useMutation({
    mutationFn: () => saveGradingScheme(schemeOf(draft)),
    onSuccess: (answer) => {
      setDraft(draftOf(answer))
      setOpened(null)
      setRepairing(false)
      setNotice(copy.saved)
      queryClient.setQueryData(gradingSchemeQuery().queryKey, answer)
    },
    // The first rank the API refused opens, so its error shows.
    onError: (error) => {
      const path = Object.keys(validationErrors(error)).find((key) => /^(ranks|kids_ladder)\.\d+\./.test(key))
      const [ladder, index] = path?.split('.') ?? []
      const rank = ladder ? draft[ladder as Ladder][Number(index)] : undefined
      if (rank) setOpened(rank.id)
    },
  })
  const errors = validationErrors(save.error)
  const errorOf = (path: string, leaf: 'label' | 'target', text: string) =>
    path in errors ? refusal(errors[path]!, leaf, { range: copy.range, value: {} }, text.trim() === '') : undefined
  const refused = (prefix: string) => Object.keys(errors).some((path) => path.startsWith(prefix))

  const change = (next: Draft) => {
    setNotice(null)
    setDraft(next)
  }
  const setLadder = (ladder: Ladder, ranks: DraftRank[]) => change({ ...draft, [ladder]: ranks })

  const apply = () => {
    const chosen = presets?.find((p) => p.key === preset)
    if (!chosen) return
    save.reset()
    setOpened(null)
    setDraft(draftOf(chosen.scheme))
    setNotice(copy.applied(chosen.label))
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setNotice(null)
    save.mutate()
  }

  return (
    <section className="settings__section" aria-label={copy.title}>
      {repairing && (
        <p className="settings__error" role="alert">
          {copy.stale}
        </p>
      )}
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      {/* Closed unless the stored scheme needs one (#177): a preset is a starting point, not a daily edit. */}
      <details className="settings__card settings__start" open={repairing || undefined} aria-label={copy.start}>
        <summary className="settings__legend">
          {copy.start}
          <ChevronDownIcon />
        </summary>
        {presetsFailed ? (
          <p className="settings__detail">{copy.presetsError}</p>
        ) : (
          <>
            <Field label={copy.preset} hint={copy.presetHint}>
              {(props) => (
                <Select
                  {...props}
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                >
                  <option value="">{copy.choosePreset}</option>
                  {presets?.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Button disabled={preset === ''} onClick={apply}>
              {repairing ? copy.reapply : copy.apply}
            </Button>
          </>
        )}
      </details>

      <form className="settings__form" aria-label={copy.title} onSubmit={submit} noValidate>
        <div className="settings__card">
          <Field label={copy.goalMetric} hint={copy.goalMetricHint}>
            {(props) => (
              <Select
                {...props}
                value={draft.goal_metric ?? ''}
                onChange={(e) =>
                  change({
                    ...draft,
                    goal_metric: (e.target.value || null) as GoalMetric | null,
                  })
                }
              >
                <option value="">{copy.goalMetrics.none}</option>
                {GOAL_METRICS.map((m) => (
                  <option key={m} value={m}>
                    {copy.goalMetrics[m]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        {LADDERS.map((ladder) => (
          <LadderEditor
            key={ladder}
            ladder={ladder}
            ranks={draft[ladder]}
            metric={draft.goal_metric}
            errorOf={errorOf}
            refused={refused}
            opened={opened}
            onOpen={setOpened}
            onChange={(ranks) => setLadder(ladder, ranks)}
          />
        ))}

        {save.error && (
          <p className="settings__error" role="alert">
            {'' in errors ? copy.schemeInvalid : Object.keys(errors).length > 0 ? copy.invalid : copy.failed}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? copy.working : copy.submit}
        </Button>
      </form>
    </section>
  )
}

type ErrorOf = (path: string, leaf: 'label' | 'target', text: string) => string | undefined
/** Whether the API refused a field under `prefix`. */
type Refused = (prefix: string) => boolean

/** `list` with the item at `index` moved by `by`; then replaced, and removed. */
function moved<T>(list: T[], index: number, by: number): T[] {
  const next = [...list]
  const [item] = next.splice(index, 1)
  next.splice(index + by, 0, item!)
  return next
}
const replaced = <T,>(list: T[], index: number, item: T) => list.map((x, i) => (i === index ? item : x))
const removed = <T,>(list: T[], index: number) => list.filter((_, i) => i !== index)

function LadderEditor({
  ladder,
  ranks,
  metric,
  errorOf,
  refused,
  opened,
  onOpen,
  onChange,
}: {
  ladder: Ladder
  ranks: DraftRank[]
  metric: GoalMetric | null
  errorOf: ErrorOf
  refused: Refused
  opened: number | null
  onOpen: (id: number | null) => void
  onChange: (ranks: DraftRank[]) => void
}) {
  const title = copy.ladders[ladder]
  return (
    <div className="settings__card" role="group" aria-label={title}>
      <h2 className="settings__legend">{title}</h2>
      <p className="settings__hint">{copy.laddersHint[ladder]}</p>
      {ranks.length === 0 ? (
        <p className="settings__detail">{copy.emptyLadder}</p>
      ) : (
        <ol className="settings__menu settings__ladder">
          {ranks.map((rank, index) => (
            <RankEditor
              key={rank.id}
              path={`${ladder}.${index}`}
              number={index + 1}
              rank={rank}
              metric={metric}
              first={index === 0}
              last={index === ranks.length - 1}
              errorOf={errorOf}
              refused={refused}
              open={opened === rank.id}
              onToggle={() => onOpen(opened === rank.id ? null : rank.id)}
              onChange={(next) => onChange(replaced(ranks, index, next))}
              onMove={(by) => onChange(moved(ranks, index, by))}
              onRemove={() => {
                onOpen(null)
                onChange(removed(ranks, index))
              }}
            />
          ))}
        </ol>
      )}
      <Button
        onClick={() => {
          // A new rank opens, to be named.
          const rank = { ...blank(), colors: [], sub_ranks: [] }
          onChange([...ranks, rank])
          onOpen(rank.id)
        }}
      >
        {copy.addRank}
      </Button>
    </div>
  )
}

/**
 * A rank, closed: a row with its belt, its name and what it takes to the next, and its
 * ↑ ↓ (#177). Tapping the row opens it to edit its name, target, belt and sub-ranks; one
 * rank is open at a time, so a scheme of twenty is not twenty forms.
 */
function RankEditor({
  path,
  number,
  rank,
  metric,
  first,
  last,
  errorOf,
  refused,
  open,
  onToggle,
  onChange,
  onMove,
  onRemove,
}: {
  path: string
  number: number
  rank: DraftRank
  metric: GoalMetric | null
  first: boolean
  last: boolean
  errorOf: ErrorOf
  refused: Refused
  open: boolean
  onToggle: () => void
  onChange: (rank: DraftRank) => void
  onMove: (by: -1 | 1) => void
  onRemove: () => void
}) {
  const name = rank.label.trim() || copy.unnamed
  const setSubRanks = (sub_ranks: DraftSubRank[]) => onChange({ ...rank, sub_ranks })
  // A rank whose sub-ranks were refused opens on them.
  const [subOpen, setSubOpen] = useState(false)
  const panel = useId()
  const target = Number(rank.target)
  const detail = refused(`${path}.`) ? (
    <span className="settings__refused">{copy.refusedRank}</span>
  ) : (
    [
      // A rank with no target of its own says nothing about one.
      metric && rank.target.trim() !== '' && Number.isFinite(target) && copy.summary[metric](target),
      rank.sub_ranks.length > 0 && copy.subRanks(rank.sub_ranks.length),
    ]
      .filter(Boolean)
      .join(' · ')
  )

  return (
    <li aria-label={copy.rank(number)}>
      <div className="settings__row">
        <button
          type="button"
          className={listRowClass(true)}
          aria-expanded={open}
          aria-controls={panel}
          onClick={onToggle}
        >
          <span className="settings__rank-belt" aria-hidden="true">
            {rank.colors.length > 0 && <Belt colors={rank.colors} stripes={0} maxStripes={0} label="" compact />}
          </span>
          <ListRowContent
            title={`${number}. ${name}`}
            detail={detail || undefined}
          />
        </button>
        <div className="settings__row-controls">
          <MoveButtons up={copy.moveUp(name)} down={copy.moveDown(name)} first={first} last={last} onMove={onMove} />
        </div>
      </div>
      <div id={panel} className="settings__rank-panel" hidden={!open}>
        {open && (
          <>
            <div className="settings__rank-fields">
              <Field label={copy.rank(number)} error={errorOf(`${path}.label`, 'label', rank.label)}>
                {(props) => (
                  <Input
                    {...props}
                    type="text"
                    maxLength={60}
                    value={rank.label}
                    onChange={(e) => onChange({ ...rank, label: e.target.value })}
                  />
                )}
              </Field>
              {metric && (
                <Field
                  label={copy.target[metric]}
                  hint={rank.sub_ranks.length > 0 ? copy.targetHint : undefined}
                  error={errorOf(`${path}.target`, 'target', rank.target)}
                >
                  {(props) => (
                    <Input
                      {...props}
                      type="text"
                      inputMode="numeric"
                      value={rank.target}
                      onChange={(e) => onChange({ ...rank, target: e.target.value })}
                    />
                  )}
                </Field>
              )}
            </div>
            <BeltColors rank={rank} name={name} onChange={(colors) => onChange({ ...rank, colors })} />
            <details
              className="settings__sub-ranks"
              open={subOpen || refused(`${path}.sub_ranks.`)}
              onToggle={(e) => setSubOpen(e.currentTarget.open)}
            >
              <summary>{copy.subRanks(rank.sub_ranks.length)}</summary>
              <ol className="settings__list">
                {rank.sub_ranks.map((sub, index) => {
                  const subPath = `${path}.sub_ranks.${index}`
                  return (
                    <li
                      key={sub.id}
                      className={metric ? 'settings__sub-rank settings__sub-rank--target' : 'settings__sub-rank'}
                    >
                      <Field label={copy.subRank(index + 1)} error={errorOf(`${subPath}.label`, 'label', sub.label)}>
                        {(props) => (
                          <Input
                            {...props}
                            type="text"
                            maxLength={60}
                            value={sub.label}
                            onChange={(e) =>
                              setSubRanks(
                                replaced(rank.sub_ranks, index, {
                                  ...sub,
                                  label: e.target.value,
                                }),
                              )
                            }
                          />
                        )}
                      </Field>
                      {metric && (
                        <Field label={copy.subTarget[metric]} error={errorOf(`${subPath}.target`, 'target', sub.target)}>
                          {(props) => (
                            <Input
                              {...props}
                              type="text"
                              inputMode="numeric"
                              placeholder={rank.target}
                              value={sub.target}
                              onChange={(e) =>
                                setSubRanks(
                                  replaced(rank.sub_ranks, index, {
                                    ...sub,
                                    target: e.target.value,
                                  }),
                                )
                              }
                            />
                          )}
                        </Field>
                      )}
                      <Button
                        icon
                        aria-label={copy.remove(sub.label.trim() || copy.subRank(index + 1))}
                        onClick={() => setSubRanks(removed(rank.sub_ranks, index))}
                      >
                        <CloseIcon />
                      </Button>
                    </li>
                  )
                })}
              </ol>
              <Button onClick={() => setSubRanks([...rank.sub_ranks, blank()])}>
                {copy.addSubRank}
              </Button>
            </details>
            <div className="settings__actions">
              <Button onClick={onToggle}>
                {copy.done}
              </Button>
            </div>
            <div className="settings__danger">
              <Button variant="danger" onClick={onRemove}>
                {copy.remove(name)}
              </Button>
            </div>
          </>
        )}
      </div>
    </li>
  )
}

/**
 * A rank's belt colours: none, and the rank shows as its name; one; or a second for the
 * stripe through a two-tone belt. Drawn as it will look, every stripe on its bar.
 */
function BeltColors({ rank, name, onChange }: { rank: DraftRank; name: string; onChange: (colors: string[]) => void }) {
  const words = copy.belt
  const [main, tone] = rank.colors
  const stripes = Math.max(rank.sub_ranks.length - 1, 0)
  return (
    <fieldset className="settings__belt">
      <legend className="settings__label">{words.title}</legend>
      {main === undefined ? (
        <>
          <p className="settings__hint">{words.none}</p>
          <Button onClick={() => onChange([DEFAULT_COLOR])}>
            {words.add}
          </Button>
        </>
      ) : (
        <>
          <Belt colors={rank.colors} stripes={stripes} maxStripes={stripes} label={words.preview(name)} />
          <div className="settings__belt-colors">
            <label className="settings__belt-color">
              <input type="color" value={main} onChange={(e) => onChange([e.target.value, ...rank.colors.slice(1)])} />
              {words.main}
            </label>
            {tone === undefined ? (
              <Button onClick={() => onChange([main, DEFAULT_COLOR])}>
                {words.addTone}
              </Button>
            ) : (
              <>
                <label className="settings__belt-color">
                  <input type="color" value={tone} onChange={(e) => onChange([main, e.target.value])} />
                  {words.tone}
                </label>
                <Button onClick={() => onChange([main])}>
                  {words.removeTone}
                </Button>
              </>
            )}
            <Button onClick={() => onChange([])}>
              {words.remove}
            </Button>
          </div>
        </>
      )}
    </fieldset>
  )
}

const DEFAULT_COLOR = '#ffffff'
