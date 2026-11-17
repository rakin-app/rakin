import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { activitiesQuery } from '../api/activities'
import { ApiError } from '../api/client'
import {
  beltsByActivity,
  GOAL_METRICS,
  gradingPresetsQuery,
  gradingSchemeQuery,
  isLevels,
  saveGradingScheme,
  type GoalMetric,
  type GradingPreset,
  type GradingScheme,
  type SchemeRank,
} from '../api/grading'
import { validationErrors } from '../api/validation'
import { Belt } from '../components/Belt'
import { Button } from '../components/Button'
import { Banner, Card, cardClass, listRowClass, ListRowContent, PlainList, SectionTitle } from '../components/Card'
import { Input, Select } from '../components/Field'
import { ChevronDownIcon, CloseIcon } from '../components/icons'
import { t } from '../i18n/es'
import { Field, integerOf, LoadFailed, MoveButtons, refusal, SectionHead } from './settingsForm'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'

const copy = t.admin.settings.grading
// The copy's literals as strings. `es` is `as const`, so `typeof copy` types each word as
// its exact belt literal ('Grados', 'Cinturón') and the levels' words ('Niveles', 'Color')
// would not fit it; widened, either set is a `Words`.
type Widened<T> = T extends string
  ? string
  : T extends (...args: infer A) => infer R
    ? (...args: A) => Widened<R>
    : { [K in keyof T]: Widened<T[K]> }
type Words = Widened<typeof copy>

/** The editor's words: a scheme no rank of which has colours is levels (#353). */
function wordsOf(levels: boolean): Words {
  if (!levels) return copy
  const over = copy.levels
  return {
    ...copy,
    ...over,
    goalMetrics: { ...copy.goalMetrics, ...over.goalMetrics },
    ladders: { ...copy.ladders, ...over.ladders },
    laddersHint: { ...copy.laddersHint, ...over.laddersHint },
    belt: { ...copy.belt, ...over.belt },
  }
}
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
  const activities = useQuery(activitiesQuery)
  const graded = activities.data?.filter((a) => a.uses_grades) ?? []
  const grades = graded.length > 0
  const scheme = useQuery({ ...gradingSchemeQuery(), enabled: grades })
  const presets = useQuery({ ...gradingPresetsQuery, enabled: grades })

  if (activities.isPending) return <Loading className="settings__note">{t.admin.settings.loading}</Loading>
  if (activities.isError) {
    return (
      <LoadFailed
        error={activities.error}
        message={copy.activitiesError}
        retry={() => void activities.refetch()}
      />
    )
  }
  // No activity grades (#245): nothing here applies until one does.
  if (!grades) return <GradingOff />
  // The presets too: a scheme never set up reads by them (#353), and should not flicker.
  if (scheme.isPending || presets.isPending) {
    return <Loading className="settings__note">{t.admin.settings.loading}</Loading>
  }
  const stale = isStale(scheme.error)
  if (scheme.isError && !stale) {
    return <LoadFailed error={scheme.error} message={copy.error} retry={() => void scheme.refetch()} />
  }
  return (
    <GradingEditor
      shared={graded.length > 1 ? graded.map((a) => a.name) : null}
      initial={scheme.data ?? EMPTY}
      stale={stale}
      presets={presets.data}
      presetsFailed={presets.isError}
      belts={beltsByActivity(graded, presets.data ?? [])}
    />
  )
}

/** "Graduación" in a gym where no activity grades: where to turn it on. */
function GradingOff() {
  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead intro={t.admin.settings.descriptions.grading} />
      <Card as="div" className="settings__card">
        <p className="settings__note">{copy.off}</p>
        <Link to="/admin/ajustes/gimnasio" hash="actividades" className="tap-link settings__link">
          {copy.turnOn}
        </Link>
      </Card>
    </section>
  )
}

function GradingEditor({
  shared,
  initial,
  stale,
  presets,
  presetsFailed,
  belts,
}: {
  // The graded activities' names, when more than one shares the scheme.
  shared: string[] | null
  initial: GradingScheme
  stale: boolean
  presets: GradingPreset[] | undefined
  presetsFailed: boolean
  // Whether the gym's graded activities are belt sports: how a scheme never set up reads.
  belts: boolean
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(() => draftOf(initial))
  const [preset, setPreset] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  // The stored scheme stays broken until one is saved over it.
  const [repairing, setRepairing] = useState(stale)
  // The one rank open to edit, by its draft id (#177): the rest are a row each.
  const [opened, setOpened] = useState<number | null>(null)
  // Levels while no rank has colours; but a scheme never saved, in a BJJ gym, reads as
  // belts until its first save (#353).
  const unset = initial.ranks.length + initial.kids_ladder.length === 0
  const levels = isLevels(draft) && !(unset && belts)
  const words = wordsOf(levels)

  const save = useSubmit({
    mutationFn: () => saveGradingScheme(schemeOf(draft)),
    onSuccess: (answer) => {
      setDraft(draftOf(answer))
      setOpened(null)
      setRepairing(false)
      setNotice(words.saved)
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
    path in errors ? refusal(errors[path]!, leaf, { range: words.range, value: {} }, text.trim() === '') : undefined
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
    setNotice(words.applied(chosen.label))
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setNotice(null)
    save.mutate()
  }

  return (
    <section className="settings__section" aria-label={words.title}>
      <SectionHead intro={t.admin.settings.descriptions.grading} />
      {shared && (
        <p className="settings__hint" role="note">
          {words.shared(shared)}
        </p>
      )}
      {repairing && (
        <Banner tone="error">
          {words.stale}
        </Banner>
      )}
      {notice && (
        <Banner tone="done">
          {notice}
        </Banner>
      )}
      {/* Closed unless the stored scheme needs one (#177): a preset is a starting point, not a daily edit. */}
      <details className={cardClass({}, 'settings__card settings__start')} open={repairing || undefined} aria-label={words.start}>
        <SectionTitle as="summary" className="settings__legend">
          {words.start}
          <ChevronDownIcon />
        </SectionTitle>
        {presetsFailed ? (
          <p className="settings__detail">{words.presetsError}</p>
        ) : (
          <>
            <Field label={words.preset} hint={words.presetHint}>
              {(props) => (
                <Select
                  {...props}
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                >
                  <option value="">{words.choosePreset}</option>
                  {presets?.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Button disabled={preset === ''} onClick={apply}>
              {repairing ? words.reapply : words.apply}
            </Button>
          </>
        )}
      </details>

      <form className="settings__form" aria-label={words.title} onSubmit={submit} noValidate>
        <Card as="div" className="settings__card">
          <Field label={words.goalMetric} hint={words.goalMetricHint}>
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
                <option value="">{words.goalMetrics.none}</option>
                {GOAL_METRICS.map((m) => (
                  <option key={m} value={m}>
                    {words.goalMetrics[m]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </Card>

        {LADDERS.map((ladder) => (
          <LadderEditor
            key={ladder}
            ladder={ladder}
            words={words}
            belts={!levels}
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
          <Banner tone="error">
            {'' in errors ? words.schemeInvalid : Object.keys(errors).length > 0 ? words.invalid : words.failed}
          </Banner>
        )}
        <div className="settings__actions settings__actions--sticky">
          <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
            {save.isPending ? words.working : words.submit}
          </Button>
        </div>
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
  words,
  belts,
  ranks,
  metric,
  errorOf,
  refused,
  opened,
  onOpen,
  onChange,
}: {
  ladder: Ladder
  words: Words
  // Whether any rank has colours: the rows keep room for a belt.
  belts: boolean
  ranks: DraftRank[]
  metric: GoalMetric | null
  errorOf: ErrorOf
  refused: Refused
  opened: number | null
  onOpen: (id: number | null) => void
  onChange: (ranks: DraftRank[]) => void
}) {
  const title = words.ladders[ladder]
  return (
    <Card as="div" className="settings__card" role="group" aria-label={title}>
      <SectionTitle className="settings__legend">{title}</SectionTitle>
      <p className="settings__hint">{words.laddersHint[ladder]}</p>
      {ranks.length === 0 ? (
        <p className="settings__detail">{words.emptyLadder}</p>
      ) : (
        <PlainList ordered className="settings__menu settings__ladder">
          {ranks.map((rank, index) => (
            <RankEditor
              key={rank.id}
              path={`${ladder}.${index}`}
              words={words}
              belts={belts}
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
        </PlainList>
      )}
      <Button
        onClick={() => {
          // A new rank opens, to be named.
          const rank = { ...blank(), colors: [], sub_ranks: [] }
          onChange([...ranks, rank])
          onOpen(rank.id)
        }}
      >
        {words.addRank}
      </Button>
    </Card>
  )
}

/**
 * A rank, closed: a row with its belt, its name and what it takes to the next, and its
 * ↑ ↓ (#177). Tapping the row opens it to edit its name, target, belt and sub-ranks; one
 * rank is open at a time, so a scheme of twenty is not twenty forms.
 */
function RankEditor({
  path,
  words,
  belts,
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
  words: Words
  belts: boolean
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
  const name = rank.label.trim() || words.unnamed
  const setSubRanks = (sub_ranks: DraftSubRank[]) => onChange({ ...rank, sub_ranks })
  // A rank whose sub-ranks were refused opens on them.
  const [subOpen, setSubOpen] = useState(false)
  const panel = useId()
  const target = Number(rank.target)
  const detail = refused(`${path}.`) ? (
    <span className="settings__refused">{words.refusedRank}</span>
  ) : (
    [
      // A rank with no target of its own says nothing about one.
      metric && rank.target.trim() !== '' && Number.isFinite(target) && words.summary[metric](target),
      rank.sub_ranks.length > 0 && words.subRanks(rank.sub_ranks.length),
    ]
      .filter(Boolean)
      .join(' · ')
  )

  return (
    <li aria-label={words.rank(number)}>
      <div className="settings__row">
        <button
          type="button"
          className={listRowClass(true)}
          aria-expanded={open}
          aria-controls={panel}
          onClick={onToggle}
        >
          {/* Levels have no belt to show (#353): no room kept for one. */}
          {belts && (
            <span className="settings__rank-belt" aria-hidden="true">
              {rank.colors.length > 0 && <Belt colors={rank.colors} stripes={0} maxStripes={0} label="" compact />}
            </span>
          )}
          <ListRowContent
            title={`${number}. ${name}`}
            detail={detail || undefined}
          />
        </button>
        <div className="settings__row-controls">
          <MoveButtons up={words.moveUp(name)} down={words.moveDown(name)} first={first} last={last} onMove={onMove} />
        </div>
      </div>
      <div id={panel} className="settings__rank-panel" hidden={!open}>
        {open && (
          <>
            <div className="settings__rank-fields">
              <Field label={words.rank(number)} error={errorOf(`${path}.label`, 'label', rank.label)}>
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
                  label={words.target[metric]}
                  hint={rank.sub_ranks.length > 0 ? words.targetHint : undefined}
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
            <BeltColors words={words.belt} rank={rank} name={name} onChange={(colors) => onChange({ ...rank, colors })} />
            <details
              className="settings__sub-ranks"
              open={subOpen || refused(`${path}.sub_ranks.`)}
              onToggle={(e) => setSubOpen(e.currentTarget.open)}
            >
              <summary>{words.subRanks(rank.sub_ranks.length)}</summary>
              <PlainList ordered className="settings__list">
                {rank.sub_ranks.map((sub, index) => {
                  const subPath = `${path}.sub_ranks.${index}`
                  return (
                    <li
                      key={sub.id}
                      className={metric ? 'settings__sub-rank settings__sub-rank--target' : 'settings__sub-rank'}
                    >
                      <Field label={words.subRank(index + 1)} error={errorOf(`${subPath}.label`, 'label', sub.label)}>
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
                        <Field label={words.subTarget[metric]} error={errorOf(`${subPath}.target`, 'target', sub.target)}>
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
                        aria-label={words.remove(sub.label.trim() || words.subRank(index + 1))}
                        onClick={() => setSubRanks(removed(rank.sub_ranks, index))}
                      >
                        <CloseIcon />
                      </Button>
                    </li>
                  )
                })}
              </PlainList>
              <Button onClick={() => setSubRanks([...rank.sub_ranks, blank()])}>
                {words.addSubRank}
              </Button>
            </details>
            <div className="settings__actions">
              <Button onClick={onToggle}>
                {words.done}
              </Button>
            </div>
            <div className="settings__danger">
              <Button variant="danger" onClick={onRemove}>
                {words.remove(name)}
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
function BeltColors({
  words,
  rank,
  name,
  onChange,
}: {
  words: Words['belt']
  rank: DraftRank
  name: string
  onChange: (colors: string[]) => void
}) {
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
