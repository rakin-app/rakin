import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { refusalCode } from '../api/client'
import {
  addRecurring,
  changeRecurring,
  EXPENSE_METHODS,
  recordRecurring,
  recurringMonthQuery,
  recurringQuery,
  skipRecurring,
  unskipRecurring,
  type AmountKind,
  type DueRecurring,
  type Expense,
  type ExpenseCategory,
  type ExpenseMethod,
  type Recurring,
  type RecurringDraft,
} from '../api/expenses'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Banner, Card, cardClass, CheckRow, PlainList } from '../components/Card'
import { cx } from '../components/classNames'
import { Field, Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import './RecurringExpenses.css'

const copy = t.admin.expenses
const clp = t.common.clp

/** The template's name on a row: its category, and who is paid when it says. */
function nameOf(template: Recurring): string {
  return template.payee ? `${template.category_name} · ${template.payee}` : template.category_name
}

/** Its amount as the card shows it: `~$84.000` for an estimate. */
function amountOf(template: Recurring): string {
  return template.amount_kind === 'estimated' ? copy.due.estimate(clp(template.amount_clp)) : clp(template.amount_clp)
}

/** Recorded in one tap: a fixed amount under a category still in use. An estimated one,
 * or one whose category was archived, opens the form. */
function oneTap(template: DueRecurring): boolean {
  return template.amount_kind === 'fixed' && !template.category_archived
}

/**
 * "Gastos fijos por registrar" (#315), above the month's list: the active gastos fijos
 * with no expense from them in `month`, and not skipped. A fixed one records in one tap at
 * its amount; an estimated one opens the form (`onOpen`) with the amount selected;
 * "Registrar los fijos" records every fixed one; "No este mes" hides one until next
 * month, and can be taken back. Nothing here records an expense unless tapped.
 */
export function RecurringDue({
  month,
  onRecorded,
  onOpen,
}: {
  // The first day of the month shown.
  month: string
  onRecorded: (message: string) => void
  onOpen: (template: DueRecurring) => void
}) {
  const words = copy.due
  const queryClient = useQueryClient()
  const card = useQuery(recurringMonthQuery(month))
  const record = useSubmit({
    offline: 'refuse',
    mutationFn: (ids: string[]) => recordRecurring(month, ids),
    onSuccess: (saved: Expense[]) => {
      void queryClient.invalidateQueries({ queryKey: ['expenses'] })
      const total = saved.reduce((sum, e) => sum + e.amount_clp, 0)
      onRecorded(saved.length === 0 ? words.nothingNew : words.recorded(saved.length, clp(total)))
    },
  })
  const skip = useSubmit({
    offline: 'refuse',
    mutationFn: ({ id, undo }: { id: string; undo: boolean }) => (undo ? unskipRecurring(id, month) : skipRecurring(id, month)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['expenses', 'recurring', 'month'] }),
  })
  const data = card.data
  if (!data || data.month !== month || (data.due.length === 0 && data.skipped.length === 0)) return null

  const fixed = data.due.filter(oneTap)
  const busy = record.isPending || skip.isPending
  const failure = record.error ?? skip.error
  const title = words.title(t.common.month(month, month.slice(0, 4)).toLowerCase())
  return (
    <Card className="recurring-due" aria-label={title}>
      <div className="recurring-due__head">
        <h2 className="recurring-due__title">{title}</h2>
        <p className="recurring-due__intro">{words.intro}</p>
      </div>
      {failure && <Banner tone="error">{refusalCode(failure) === 'already_recorded' ? words.alreadyRecorded : words.failed}</Banner>}
      {data.due.length > 0 && (
        <PlainList className="recurring-due__list">
          {data.due.map((template) => {
            const what = nameOf(template)
            return (
              <li key={template.id} className="recurring-due__row">
                <span className="recurring-due__what">
                  <span className="recurring-due__name">{what}</span>
                  <span className="recurring-due__day">{words.day(template.day_of_month)}</span>
                </span>
                <span className="recurring-due__amount">{amountOf(template)}</span>
                <span className="recurring-due__actions">
                  {oneTap(template) ? (
                    <Button
                      variant="primary"
                      aria-label={words.recordWhat(what)}
                      disabled={busy}
                      onClick={() => record.mutate([template.id])}
                    >
                      {words.record}
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      aria-label={words.recordWhat(what)}
                      disabled={busy}
                      onClick={() => onOpen(template)}
                    >
                      {words.recordEstimated}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    aria-label={words.skipWhat(what)}
                    disabled={busy}
                    onClick={() => skip.mutate({ id: template.id, undo: false })}
                  >
                    {words.skip}
                  </Button>
                </span>
              </li>
            )
          })}
        </PlainList>
      )}
      {fixed.length > 1 && (
        <div className="recurring-due__all">
          <Button busy={record.isPending} disabled={busy} onClick={() => record.mutate(fixed.map((f) => f.id))}>
            {record.isPending ? words.working : words.recordAll(fixed.length)}
          </Button>
        </div>
      )}
      {data.skipped.length > 0 && (
        <div className="recurring-due__skipped">
          <h3 className="recurring-due__subtitle">{words.skippedTitle}</h3>
          <PlainList className="recurring-due__list">
            {data.skipped.map((template) => {
              const what = nameOf(template)
              return (
                <li key={template.id} className="recurring-due__row recurring-due__row--skipped">
                  <span className="recurring-due__what">
                    <span className="recurring-due__name">{what}</span>
                  </span>
                  <span className="recurring-due__amount">{amountOf(template)}</span>
                  <span className="recurring-due__actions">
                    <Button
                      variant="ghost"
                      aria-label={words.unskipWhat(what)}
                      disabled={busy}
                      onClick={() => skip.mutate({ id: template.id, undo: true })}
                    >
                      {words.unskip}
                    </Button>
                  </span>
                </li>
              )
            })}
          </PlainList>
        </div>
      )}
    </Card>
  )
}

/**
 * Gastos fijos (#315): the gym's templates, added, edited, paused and resumed, below the
 * month's list beside the categories. A paused one is on no month's card.
 */
export function RecurringTemplates({ categories }: { categories: ExpenseCategory[] }) {
  const words = copy.recurring
  const queryClient = useQueryClient()
  const templates = useQuery(recurringQuery())
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const pause = useSubmit({
    offline: 'refuse',
    mutationFn: ({ id, active }: { id: string; active: boolean }) => changeRecurring(id, { active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['expenses', 'recurring'] }),
  })
  const list = templates.data ?? []

  return (
    <details className={cardClass({}, 'recurring')}>
      <summary className="recurring__title">{words.title}</summary>
      <p className="recurring__meta">{words.intro}</p>
      {pause.error && <Banner tone="error">{words.failed}</Banner>}
      {templates.isSuccess && list.length === 0 && <p className="recurring__meta">{words.empty}</p>}
      {list.length > 0 && (
        <PlainList className="recurring__list">
          {list.map((template) => (
            <li key={template.id} className={cx('recurring__row', !template.active && 'recurring__row--paused')}>
              {editing === template.id ? (
                <RecurringForm template={template} categories={categories} onDone={() => setEditing(null)} />
              ) : (
                <>
                  <span className="recurring__what">
                    <span className="recurring__name">
                      {nameOf(template)}
                      {!template.active && <span className="recurring__badge">{words.paused}</span>}
                    </span>
                    <span className="recurring__meta">
                      {words.summary(amountOf(template), template.day_of_month, words.kind[template.amount_kind])}
                    </span>
                    {template.category_archived && <span className="recurring__meta">{words.archivedCategory}</span>}
                  </span>
                  <span className="recurring__actions">
                    <Button variant="ghost" disabled={pause.isPending} onClick={() => setEditing(template.id)}>
                      {words.edit}
                    </Button>
                    <Button
                      variant="ghost"
                      disabled={pause.isPending}
                      onClick={() => pause.mutate({ id: template.id, active: !template.active })}
                    >
                      {template.active ? words.pause : words.resume}
                    </Button>
                  </span>
                </>
              )}
            </li>
          ))}
        </PlainList>
      )}
      {editing === 'new' ? (
        <RecurringForm categories={categories} onDone={() => setEditing(null)} />
      ) : (
        <div>
          <Button disabled={categories.length === 0} onClick={() => setEditing('new')}>
            {words.add}
          </Button>
        </div>
      )}
    </details>
  )
}

const digits = (value: string) => value.replace(/\D/g, '').replace(/^0+(?=\d)/, '')

/** A new gasto fijo, or an edit of `template`. */
function RecurringForm({
  template,
  categories,
  onDone,
}: {
  template?: Recurring
  categories: ExpenseCategory[]
  onDone: () => void
}) {
  const words = copy.recurring
  const form = copy.form
  const queryClient = useQueryClient()
  const kindId = useId()
  const [categoryId, setCategoryId] = useState(template && !template.category_archived ? template.category_id : '')
  const [payee, setPayee] = useState(template?.payee ?? '')
  const [method, setMethod] = useState<ExpenseMethod | ''>(template?.method ?? '')
  const [amount, setAmount] = useState(template ? String(template.amount_clp) : '')
  const [kind, setKind] = useState<AmountKind>(template?.amount_kind ?? 'fixed')
  const [day, setDay] = useState(template ? String(template.day_of_month) : '')
  const [checked, setChecked] = useState(false)

  const amountClp = Number(amount)
  const dayNumber = Number(day)
  const amountOk = amountClp > 0
  const dayOk = Number.isInteger(dayNumber) && dayNumber >= 1 && dayNumber <= 31
  const categoryOk = categoryId !== ''

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: (draft: RecurringDraft) => {
      if (!template) return addRecurring(draft)
      const changes: Partial<RecurringDraft> = {}
      for (const field of Object.keys(draft) as (keyof RecurringDraft)[]) {
        if (draft[field] !== template[field]) Object.assign(changes, { [field]: draft[field] })
      }
      return changeRecurring(template.id, changes)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['expenses', 'recurring'] })
      onDone()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!amountOk || !dayOk || !categoryOk) return
    save.mutate({
      category_id: categoryId,
      payee: payee.trim() || null,
      method: method || null,
      amount_clp: amountClp,
      amount_kind: kind,
      day_of_month: dayNumber,
    })
  }
  const title = template ? words.editTitle(nameOf(template)) : words.newTitle
  const failure = save.error && (refusalCode(save.error) === 'too_many_recurring' ? words.tooMany : words.failed)

  return (
    <form className="recurring__form" aria-label={title} onSubmit={submit} noValidate>
      <h3 className="recurring__form-title">{title}</h3>
      <div className="recurring__fields">
        <Field label={form.category} error={checked && !categoryOk && form.categoryNeeded}>
          {(props) => (
            <Select {...props} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              {categoryId === '' && <option value="">{form.pickCategory}</option>}
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={form.payee} hint={form.payeeHint}>
          {(props) => <Input {...props} maxLength={200} value={payee} onChange={(e) => setPayee(e.target.value)} />}
        </Field>
        <fieldset className="recurring__kind">
          <legend className="field__label">{words.kindLabel}</legend>
          {(['fixed', 'estimated'] as const).map((k) => (
            <CheckRow key={k}>
              <input type="radio" name={kindId} value={k} checked={kind === k} onChange={() => setKind(k)} />
              {words.kind[k]}
            </CheckRow>
          ))}
          <p className="field__hint">{words.kindHint}</p>
        </fieldset>
        <Field label={kind === 'estimated' ? words.amountEstimated : words.amount} error={checked && !amountOk && form.amountNeeded}>
          {(props) => (
            <Input
              {...props}
              inputMode="numeric"
              autoComplete="off"
              value={amount === '' ? '' : Number(amount).toLocaleString('es-CL')}
              onChange={(e) => setAmount(digits(e.target.value))}
            />
          )}
        </Field>
        <Field label={words.dayOfMonth} hint={words.dayHint} error={checked && !dayOk && words.dayNeeded}>
          {(props) => (
            <Input
              {...props}
              type="number"
              inputMode="numeric"
              min={1}
              max={31}
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
          )}
        </Field>
        <Field label={form.method}>
          {(props) => (
            <Select {...props} value={method} onChange={(e) => setMethod(e.target.value as ExpenseMethod | '')}>
              <option value="">{form.noMethod}</option>
              {EXPENSE_METHODS.map((m) => (
                <option key={m} value={m}>
                  {copy.method[m]}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {failure && <Banner tone="error">{failure}</Banner>}
      <div className="recurring__form-actions">
        <Button disabled={save.isPending} onClick={onDone}>
          {words.cancel}
        </Button>
        <Button type="submit" variant="primary" busy={save.isPending}>
          {save.isPending ? words.working : words.save}
        </Button>
      </div>
    </form>
  )
}
