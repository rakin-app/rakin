import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  CATEGORIES,
  createCharge,
  groupsQuery,
  previewBody,
  previewCharge,
  type AmountMode,
  type Category,
  type Draft,
  type Preview,
  type Target,
  type TargetKind,
} from '../api/extraCharges'
import type { PersonRef } from '../api/ledger'
import { myRoleQuery, readsLedger } from '../api/me'
import { programsQuery } from '../api/people'
import { Button, buttonClass } from '../components/Button'
import { Card, SectionHeader } from '../components/Card'
import { Field, Input, Select, Textarea } from '../components/Field'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { PeoplePicker, SubHeader } from './ExtraCharges'
import './ExtraCharges.css'
import { useSubmit } from '../api/submit'

const copy = t.admin.extra
const words = copy.wizard
const clp = t.common.clp

const TARGETS: TargetKind[] = ['active', 'program', 'group', 'people']
const MODES: AmountMode[] = ['fixed', 'split']
const LAST = words.steps.length - 1
// The preview waits this long after the last keystroke.
const PREVIEW_DEBOUNCE_MS = 300

type Choice = { kind: TargetKind; program_id: string; group_id: string; people: PersonRef[] }

function targetOf(choice: Choice): Target | null {
  if (choice.kind === 'active') return { kind: 'active' }
  if (choice.kind === 'program') return choice.program_id ? { kind: 'program', program_id: choice.program_id } : null
  if (choice.kind === 'group') return choice.group_id ? { kind: 'group', group_id: choice.group_id } : null
  return choice.people.length ? { kind: 'people', person_ids: choice.people.map((p) => p.id) } : null
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

/**
 * "Nuevo cobro extra" (#195): the details, whom it is for, how much with each person's
 * amount previewed live (a split's share and remainder, and any amount set by hand),
 * the message, and a last look that lists who has no email, with a WhatsApp link each.
 */
export function ExtraChargeNew() {
  usePageTitle(words.title)
  const role = useQuery(myRoleQuery())
  if (!readsLedger(role.data)) {
    return (
      <PageContainer>
        <PageHeader title={words.title} />
        {role.isSuccess && <p className="extra__note">{t.admin.payments.coachesOnly}</p>}
      </PageContainer>
    )
  }
  return <Wizard />
}

function Wizard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(0)
  const [tried, setTried] = useState(false)
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState<Category>('rifa')
  const [description, setDescription] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [choice, setChoice] = useState<Choice>({ kind: 'active', program_id: '', group_id: '', people: [] })
  const [mode, setMode] = useState<AmountMode>('fixed')
  const [amount, setAmount] = useState('')
  const [overrides, setOverrides] = useState<Record<string, number>>({})
  const [message, setMessage] = useState('')
  const [notify, setNotify] = useState(true)

  const target = targetOf(choice)
  const amountClp = Number(amount)
  const draft: Draft | null = target && {
    title,
    description,
    message,
    category,
    due_date: dueDate,
    target,
    amount_mode: mode,
    amount_clp: amountClp,
    overrides: Object.entries(overrides).map(([person_id, amount_clp]) => ({ person_id, amount_clp })),
    notify,
  }
  const settled = useDebounced(draft, PREVIEW_DEBOUNCE_MS)
  const preview = useQuery({
    queryKey: ['extra', 'preview', settled && previewBody(settled)],
    queryFn: () => previewCharge(settled!),
    enabled: step >= 2 && settled !== null && settled.amount_clp > 0,
    placeholderData: keepPreviousData,
    retry: false,
  })

  // The preview shows what will be charged only once it answers for the draft as it
  // stands: not a placeholder from an earlier one, not mid-refetch, and not for a draft
  // the debounce has yet to catch up with.
  const fresh =
    preview.isSuccess &&
    !preview.isPlaceholderData &&
    !preview.isFetching &&
    draft !== null &&
    settled !== null &&
    JSON.stringify(previewBody(draft)) === JSON.stringify(previewBody(settled))
  // The amount and the last look wait for it; an error is shown, not waited on.
  const waiting = (step === 2 || step === LAST) && amountClp > 0 && !fresh && !preview.isError

  const create = useSubmit({
    mutationFn: () => createCharge(draft!),
    onSuccess: async (charge) => {
      await queryClient.invalidateQueries({ queryKey: ['extra'] })
      void navigate({ to: '/admin/pagos/cobros/$chargeId', params: { chargeId: charge.id } })
    },
  })

  const problem = [
    !title.trim() ? words.titleNeeded : !dueDate ? words.dueNeeded : null,
    target ? null : words.pickNeeded,
    !(amountClp > 0) ? words.amountNeeded : preview.isError ? previewProblem(preview.error) : null,
    null,
    null,
  ][step] ?? null

  const next = (event: FormEvent) => {
    event.preventDefault()
    if (problem) {
      setTried(true)
      return
    }
    if (waiting) return
    setTried(false)
    if (step < LAST) setStep(step + 1)
    else create.mutate()
  }

  const retarget = (change: Partial<Choice>) => {
    setChoice({ ...choice, ...change })
    // An amount set by hand belongs to the people it was set for.
    setOverrides({})
  }

  return (
    <PageContainer className="extra">
      <SubHeader title={words.title} back="cobros" />
      <ol className="extra__steps" aria-label={words.title}>
        {words.steps.map((name, i) => (
          <li key={name} className="extra__step" aria-current={i === step ? 'step' : undefined}>
            {name}
          </li>
        ))}
      </ol>
      <form className="extra__wizard" onSubmit={next} noValidate>
        <Card aria-labelledby="extra-step">
          <SectionHeader id="extra-step" title={words.stepOf(step + 1, words.steps.length, words.steps[step]!)} />
          {step === 0 && (
            <>
              <Field label={words.titleLabel} error={tried && !title.trim() ? words.titleNeeded : undefined}>
                {(props) => (
                  <Input
                    {...props}
                    value={title}
                    maxLength={120}
                    placeholder={words.titlePlaceholder}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                )}
              </Field>
              <Field label={words.categoryLabel}>
                {(props) => (
                  <Select {...props} value={category} onChange={(e) => setCategory(e.target.value as Category)}>
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {copy.category[c]}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={words.descriptionLabel}>
                {(props) => (
                  <Textarea {...props} value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} />
                )}
              </Field>
              <Field label={words.dueLabel} error={tried && title.trim() && !dueDate ? words.dueNeeded : undefined}>
                {(props) => <Input {...props} type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}
              </Field>
            </>
          )}
          {step === 1 && <TargetStep choice={choice} onChange={retarget} tried={tried} />}
          {step === 2 && (
            <AmountStep
              mode={mode}
              amount={amount}
              preview={preview.data}
              loading={preview.isFetching}
              error={tried || amount ? problem : null}
              overrides={overrides}
              onMode={(value) => {
                setMode(value)
                setOverrides({})
              }}
              onAmount={setAmount}
              onOverride={(person, value) => {
                const rest = { ...overrides }
                if (value === null) delete rest[person]
                else rest[person] = value
                setOverrides(rest)
              }}
            />
          )}
          {step === 3 && (
            <>
              <Field label={words.messageLabel} hint={words.messageHint}>
                {(props) => <Textarea {...props} value={message} maxLength={2000} onChange={(e) => setMessage(e.target.value)} />}
              </Field>
              <label className="extra__check">
                <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
                <span>
                  {words.notify}
                  <span className="extra__hint">{words.notifyHint}</span>
                </span>
              </label>
            </>
          )}
          {step === 4 && preview.data && <Confirm title={title} preview={preview.data} />}
        </Card>
        {create.isError && (
          <p className="extra__error" role="alert">
            {words.failed}
          </p>
        )}
        <div className="extra__form-actions">
          {step > 0 && <Button onClick={() => setStep(step - 1)}>{words.previous}</Button>}
          <Button type="submit" variant="primary" disabled={create.isPending || waiting} busy={create.isPending}>
            {waiting
              ? words.previewLoading
              : step === LAST
                ? create.isPending
                  ? words.creating
                  : words.create
                : words.next}
          </Button>
          {step === 0 && (
            <Link to="/admin/pagos/cobros" className={buttonClass({ variant: 'ghost' })}>
              {words.cancel}
            </Link>
          )}
        </div>
      </form>
    </PageContainer>
  )
}

function previewProblem(error: unknown): string {
  const detail = error instanceof ApiError ? (error.body as { detail?: unknown } | undefined)?.detail : undefined
  if (detail === 'the target names nobody') return words.nobody
  if (detail === 'a split leaves everyone at least a peso') return words.tooSmall
  return words.previewError
}

function TargetStep({ choice, onChange, tried }: { choice: Choice; onChange: (c: Partial<Choice>) => void; tried: boolean }) {
  const programs = useQuery(programsQuery)
  const groups = useQuery(groupsQuery())
  return (
    <>
      <fieldset className="extra__choices">
        <legend className="extra__legend">{words.targetLabel}</legend>
        {TARGETS.map((kind) => (
          <label key={kind} className="extra__choice">
            <input type="radio" name="target" checked={choice.kind === kind} onChange={() => onChange({ kind })} />
            <span>{words.target[kind]}</span>
          </label>
        ))}
      </fieldset>
      {choice.kind === 'program' && (
        <Field label={words.programLabel} error={tried && !choice.program_id ? words.pickNeeded : undefined}>
          {(props) => (
            <Select {...props} value={choice.program_id} onChange={(e) => onChange({ program_id: e.target.value })}>
              <option value="" />
              {(programs.data ?? []).filter((p) => p.active).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      )}
      {choice.kind === 'group' &&
        (groups.isSuccess && groups.data.length === 0 ? (
          <p className="extra__note">{words.noGroups}</p>
        ) : (
          <Field label={words.groupLabel} error={tried && !choice.group_id ? words.pickNeeded : undefined}>
            {(props) => (
              <Select {...props} value={choice.group_id} onChange={(e) => onChange({ group_id: e.target.value })}>
                <option value="" />
                {(groups.data ?? []).map((g) => (
                  <option key={g.id} value={g.id}>
                    {copy.groups.option(g.name, g.size)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ))}
      {choice.kind === 'people' && (
        <>
          <PeoplePicker
            label={copy.groups.search}
            chosen={choice.people}
            onPick={(person) => onChange({ people: [...choice.people, person] })}
          />
          {choice.people.length > 0 ? (
            <ul className="extra__chosen">
              {choice.people.map((person) => (
                <li key={person.id} className="extra__chosen-item">
                  <span>{person.name}</span>
                  <Button
                    variant="ghost"
                    aria-label={copy.groups.remove(person.name)}
                    onClick={() => onChange({ people: choice.people.filter((p) => p.id !== person.id) })}
                  >
                    {copy.groups.removeShort}
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            tried && (
              <p className="extra__error" role="alert">
                {words.pickNeeded}
              </p>
            )
          )}
        </>
      )}
    </>
  )
}

function digits(value: string): string {
  return value.replace(/\D/g, '').replace(/^0+(?=\d)/, '').slice(0, 12)
}

function AmountStep({
  mode,
  amount,
  preview,
  loading,
  error,
  overrides,
  onMode,
  onAmount,
  onOverride,
}: {
  mode: AmountMode
  amount: string
  preview: Preview | undefined
  loading: boolean
  error: string | null
  overrides: Record<string, number>
  onMode: (mode: AmountMode) => void
  onAmount: (amount: string) => void
  onOverride: (person: string, amount: number | null) => void
}) {
  return (
    <>
      <fieldset className="extra__choices">
        <legend className="extra__legend">{words.modeLabel}</legend>
        {MODES.map((value) => (
          <label key={value} className="extra__choice">
            <input type="radio" name="mode" checked={mode === value} onChange={() => onMode(value)} />
            <span>{words.mode[value]}</span>
          </label>
        ))}
      </fieldset>
      <Field label={words.amountLabel[mode]} error={error ?? undefined}>
        {(props) => <Input {...props} inputMode="numeric" value={amount} onChange={(e) => onAmount(digits(e.target.value))} />}
      </Field>
      {preview && (
        <section className="extra__preview" aria-label={words.previewLabel} aria-busy={loading}>
          <SectionHeader as="h3" title={words.previewLabel} trailing={words.total(clp(preview.total_clp), preview.lines.length)} />
          {preview.share_clp !== null && (
            <p className="extra__hint">{words.split(clp(preview.share_clp), preview.lines.length)}</p>
          )}
          {preview.remainder_clp > 0 && <p className="extra__hint">{words.remainder(preview.remainder_clp)}</p>}
          <ul className="extra__preview-list">
            {preview.lines.map((line) => (
              <li key={line.person.id} className="extra__preview-row">
                <span className="extra__preview-name">
                  {line.person.name}
                  {line.on_behalf && <span className="extra__hint">{words.guardian(line.contact_name)}</span>}
                  {line.overridden && <span className="extra__hint">{words.overridden}</span>}
                </span>
                <Input
                  className="extra__preview-amount"
                  inputMode="numeric"
                  aria-label={words.overrideLabel(line.person.name)}
                  value={String(overrides[line.person.id] ?? line.amount_clp)}
                  onChange={(e) => {
                    const value = digits(e.target.value)
                    onOverride(line.person.id, value === '' ? 0 : Number(value))
                  }}
                />
                {line.person.id in overrides && (
                  <Button variant="ghost" aria-label={words.reset(line.person.name)} onClick={() => onOverride(line.person.id, null)}>
                    {words.undo}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {!preview && loading && <p className="extra__note">{words.previewLoading}</p>}
    </>
  )
}

function Confirm({ title, preview }: { title: string; preview: Preview }) {
  const without = preview.lines.filter((line) => !line.has_email && line.amount_clp > 0)
  return (
    <>
      <p>{words.summary(title.trim(), preview.lines.length, clp(preview.total_clp))}</p>
      {without.length > 0 && (
        <>
          <p className="extra__hint">{words.noEmail(without.length)}</p>
          <ul className="extra__chosen">
            {without.map((line) => (
              <li key={line.person.id} className="extra__chosen-item">
                <span>{words.personAmount(line.person.name, clp(line.amount_clp))}</span>
                {line.whatsapp_url ? (
                  <a className={buttonClass()} href={line.whatsapp_url} target="_blank" rel="noreferrer">
                    {words.whatsapp(line.contact_name)}
                  </a>
                ) : (
                  <span className="extra__hint">{words.noWhatsapp}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  )
}
