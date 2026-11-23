import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { refusalCode as refusal } from '../api/client'
import {
  addCategory,
  archiveCategory,
  changedFields,
  changeExpense,
  EXPENSE_METHODS,
  expenseCategoriesQuery,
  expenseMonthQuery,
  orderCategories,
  receiptUrl,
  recordExpense,
  renameCategory,
  restoreCategory,
  voidExpense,
  type DueRecurring,
  type Expense,
  type ExpenseCategory,
  type ExpenseDraft,
  type ExpenseMethod,
  type ReceiptChange,
} from '../api/expenses'
import { chargesQuery } from '../api/extraCharges'
import { myAccessQuery, readsExpenses, readsLedger, writesExpenses } from '../api/me'
import { proofProblem } from '../api/proofs'
import { useSubmit } from '../api/submit'
import { Button, buttonClass } from '../components/Button'
import { Disclosure } from '../components/Disclosure'
import { Banner, Card, cardClass, PlainList } from '../components/Card'
import { cx } from '../components/classNames'
import { Field, FieldError, Input, Select, Textarea } from '../components/Field'
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon } from '../components/icons'
import { PageContainer } from '../components/Layout'
import { Loading } from '../components/Loading'
import { MoneyTabs } from '../components/MoneyTabs'
import { PageHeader, PageTitle } from '../components/PageHeader'
import { isoDay, shiftMonth } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { RecurringDue, RecurringTemplates } from './RecurringExpenses'
import './Expenses.css'

const copy = t.admin.expenses
const clp = t.common.clp

export type ExpensesSearch = {
  // The first day of the month shown, `2026-10-01`; the current month when absent.
  month?: string
  // One category's expenses only.
  category?: string
}

export function validateExpensesSearch(search: Record<string, unknown>): ExpensesSearch {
  const month = typeof search.month === 'string' && /^\d{4}-\d{2}-01$/.test(search.month) ? search.month : undefined
  const category = typeof search.category === 'string' && search.category !== '' ? search.category : undefined
  return { month, category }
}

const route = getRouteApi('/admin/finanzas/gastos')

/**
 * Finanzas › Gastos (#314): what the gym spends, a month at a time, newest first, apart
 * from billing (docs/design/expenses-and-officers.md, sections 10 and 12). The form
 * opens in place, at the top for a new expense and on the row for a correction; Anular
 * asks why, and leaves the expense listed, struck through and out of the total.
 *
 * Who holds "Ver gastos" sees it, and "Registrar gastos" writes it; no role holds
 * either until the gym ticks it, so at first only the titular does. Anyone else is told
 * so, and nothing is asked of the API.
 */
export function Expenses() {
  usePageTitle(copy.title)
  const access = useQuery(myAccessQuery())
  if (readsExpenses(access.data)) {
    return <ExpensesPage writes={writesExpenses(access.data)} />
  }
  return (
    <PageContainer>
      <PageHeader title={copy.title} />
      {access.isSuccess && <p className="expenses__note">{copy.onlyWho}</p>}
    </PageContainer>
  )
}

function ExpensesPage({ writes }: { writes: boolean }) {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const month = useQuery({ ...expenseMonthQuery(search.month, search.category), placeholderData: keepPreviousData })
  const categories = useQuery(expenseCategoriesQuery())
  // The form at the top: closed, a new expense, or one from a gasto fijo (#315).
  const [recording, setRecording] = useState<false | { from?: DueRecurring }>(false)
  const [done, setDone] = useState<string | null>(null)
  const categoryId = useId()
  const shown = month.data
  const shownMonth = shown?.month ?? search.month
  const all = categories.data ?? []
  const live = all.filter((c) => !c.archived)

  const go = (next: ExpensesSearch) => void navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })

  return (
    <PageContainer className="expenses">
      <MoneyTabs />
      <header className="expenses__header">
        <div className="expenses__heading">
          <PageTitle>{copy.title}</PageTitle>
          <p className="expenses__subtitle">{copy.subtitle}</p>
        </div>
        {writes && (
          <Button
            variant="primary"
            aria-expanded={recording !== false && !recording.from}
            disabled={live.length === 0}
            onClick={() => {
              setDone(null)
              setRecording(recording !== false && !recording.from ? false : {})
            }}
          >
            {copy.record}
          </Button>
        )}
      </header>

      <div className="expenses__toolbar">
        <div className="expenses__month" role="group" aria-label={copy.month}>
          <Button
            icon
            variant="ghost"
            aria-label={copy.previous}
            disabled={!shownMonth}
            onClick={() => shownMonth && go({ month: shiftMonth(shownMonth, -1) })}
          >
            <ChevronLeftIcon />
          </Button>
          <span className="expenses__month-label" aria-live="polite">
            {shownMonth ? t.common.month(shownMonth, '') : ''}
          </span>
          <Button
            icon
            variant="ghost"
            aria-label={copy.next}
            disabled={!shown || shown.month >= shown.current_month}
            onClick={() => shown && go({ month: shiftMonth(shown.month, 1) })}
          >
            <ChevronRightIcon />
          </Button>
        </div>
        <label htmlFor={categoryId} className="expenses__filter">
          <span className="visually-hidden">{copy.category}</span>
          <Select
            id={categoryId}
            value={search.category ?? ''}
            onChange={(event) => go({ category: event.target.value || undefined })}
          >
            <option value="">{copy.allCategories}</option>
            {all.map((c) => (
              <option key={c.id} value={c.id}>
                {c.archived ? copy.archivedCategory(c.name) : c.name}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {done && <Banner tone="done">{done}</Banner>}
      {writes && shownMonth && !(recording && recording.from) && (
        <RecurringDue
          month={shownMonth}
          onRecorded={setDone}
          onOpen={(from) => {
            setDone(null)
            setRecording({ from })
          }}
        />
      )}
      {recording && shown && (
        <ExpenseForm
          key={recording.from?.id ?? 'new'}
          from={recording.from}
          today={shown.today}
          categories={live}
          onCancel={() => setRecording(false)}
          onDone={(message, saved) => {
            setRecording(false)
            setDone(message)
            // The list goes to the month it was paid in, where it now is.
            const paidIn = `${saved.spent_on.slice(0, 7)}-01`
            if (paidIn !== shownMonth) go({ month: paidIn })
          }}
        />
      )}

      {month.isPending ? (
        <Loading className="expenses__note">{copy.loading}</Loading>
      ) : month.isError && !shown ? (
        <div className="expenses__note" role="alert">
          <p>{copy.error}</p>
          <Button onClick={() => void month.refetch()}>{copy.retry}</Button>
        </div>
      ) : (
        shown && (
          <Card flush className="expenses__card" aria-label={copy.listLabel(t.common.month(shown.month, ''))}>
            <div className="expenses__total">
              <span className="expenses__total-label">{copy.total}</span>
              <span className="expenses__total-figure">{clp(shown.total_clp)}</span>
              <span className="expenses__total-count">{copy.count(shown.count)}</span>
            </div>
            {shown.items.length === 0 ? (
              <p className="expenses__empty">{search.category ? copy.emptyCategory : copy.empty}</p>
            ) : (
              <PlainList className="expenses__list">
                {shown.items.map((expense) => (
                  <ExpenseRow
                    key={expense.id}
                    expense={expense}
                    categories={live}
                    today={shown.today}
                    writes={writes}
                    onDone={setDone}
                  />
                ))}
              </PlainList>
            )}
          </Card>
        )
      )}

      {writes && categories.data && <RecurringTemplates categories={live} />}
      {writes && categories.data && <Categories categories={all} />}
    </PageContainer>
  )
}

/** `Inmobiliaria Los Robles · Transferencia · noviembre`: what else the row says. */
function rowDetail(expense: Expense): string {
  return [expense.payee, expense.method ? copy.method[expense.method] : null, expense.note].filter(Boolean).join(' · ')
}

type Open = 'detail' | 'edit' | 'void' | null

function ExpenseRow({
  expense,
  categories,
  today,
  writes,
  onDone,
}: {
  expense: Expense
  categories: ExpenseCategory[]
  today: string
  writes: boolean
  onDone: (message: string) => void
}) {
  const [open, setOpen] = useState<Open>(null)
  const voided = expense.voided_at !== null
  const detail = rowDetail(expense)
  const panelId = useId()
  return (
    <li className={cx('expenses__row', voided && 'expenses__row--voided')}>
      <button
        type="button"
        className="expenses__row-button"
        aria-expanded={open !== null}
        aria-controls={panelId}
        onClick={() => setOpen(open === null ? 'detail' : null)}
      >
        <span className="expenses__date">{t.common.shortDay(expense.spent_on)}</span>
        <span className="expenses__what">
          <span className="expenses__category">{expense.category_name}</span>
          {detail && <span className="expenses__detail">{detail}</span>}
        </span>
        <span className="expenses__amount">
          {voided && <span className="expenses__voided">{copy.voided}</span>}
          <span className="expenses__figure">{clp(expense.amount_clp)}</span>
        </span>
        <span className="expenses__chevron" aria-hidden="true">
          {open === null ? <ChevronDownIcon /> : <ChevronUpIcon />}
        </span>
      </button>
      {open !== null && (
        <div id={panelId} className="expenses__panel">
          {open === 'detail' && (
            <Detail
              expense={expense}
              writes={writes && !voided}
              onEdit={() => setOpen('edit')}
              onVoid={() => setOpen('void')}
              onClose={() => setOpen(null)}
            />
          )}
          {open === 'edit' && (
            <ExpenseForm
              expense={expense}
              categories={categories}
              today={today}
              onCancel={() => setOpen('detail')}
              onDone={(message) => {
                setOpen(null)
                onDone(message)
              }}
            />
          )}
          {open === 'void' && (
            <VoidForm
              expense={expense}
              onCancel={() => setOpen('detail')}
              onDone={(message) => {
                setOpen(null)
                onDone(message)
              }}
            />
          )}
        </div>
      )}
    </li>
  )
}

/** Who recorded it and when, a correction, a void and its reason, the receipt. */
function Detail({
  expense,
  writes,
  onEdit,
  onVoid,
  onClose,
}: {
  expense: Expense
  writes: boolean
  onEdit: () => void
  onVoid: () => void
  onClose: () => void
}) {
  // Asked for on each tap: a presigned link lasts minutes, and the page may have been
  // open for hours. The tab opens at once, while the tap still counts as one, and goes
  // to the receipt once the link comes back.
  const [opening, setOpening] = useState(false)
  const [failed, setFailed] = useState(false)
  const openReceipt = async () => {
    const tab = window.open('', '_blank')
    if (tab) tab.opener = null
    setFailed(false)
    setOpening(true)
    try {
      const { url } = await receiptUrl(expense.id)
      if (tab) tab.location.href = url
      else window.location.assign(url)
    } catch {
      tab?.close()
      setFailed(true)
    } finally {
      setOpening(false)
    }
  }
  return (
    <div className="expenses__detail-panel">
      <p className="expenses__meta">{copy.recordedBy(expense.created_by_name, t.common.dayYear(isoDay(expense.created_at)))}</p>
      {expense.updated_at && <p className="expenses__meta">{copy.edited(t.common.dayYear(isoDay(expense.updated_at)))}</p>}
      {expense.extra_charge_id && (
        <p className="expenses__meta">
          {expense.extra_charge_title ? (
            <>
              {copy.recoveredBy}{' '}
              <Link to="/admin/pagos/cobros/$chargeId" params={{ chargeId: expense.extra_charge_id }}>
                {expense.extra_charge_title}
              </Link>
            </>
          ) : (
            copy.recoveredByUnnamed
          )}
        </p>
      )}
      {expense.voided_at && (
        <p className="expenses__meta expenses__meta--voided">
          {copy.voidedBy(expense.voided_by_name, expense.void_reason ?? '')}
        </p>
      )}
      {failed && <Banner tone="error">{copy.receiptFailed}</Banner>}
      <div className="expenses__actions">
        {expense.has_receipt && (
          <Button busy={opening} onClick={() => void openReceipt()}>
            {opening ? copy.receiptOpening : copy.receipt}
          </Button>
        )}
        {writes && <Button onClick={onEdit}>{copy.edit}</Button>}
        {writes && (
          <Button variant="danger" onClick={onVoid}>
            {copy.void}
          </Button>
        )}
        <Button variant="ghost" onClick={onClose}>
          {copy.close}
        </Button>
      </div>
    </div>
  )
}

function failureOf(error: unknown): string {
  const code = refusal(error)
  if (code === 'receipt_taken') return copy.form.receiptTaken
  if (code === 'category_archived') return copy.form.categoryArchived
  if (code === 'already_recorded') return copy.due.alreadyRecorded
  if (code === 'no_extra_charge') return copy.form.extraChargeGone
  return copy.form.failed
}

const digits = (value: string) => value.replace(/\D/g, '').replace(/^0+(?=\d)/, '')

/** New, at the top of the list, or a correction of `expense`, on its row. `from` is the
 * gasto fijo it records (#315): its fields filled in, dated its day, and the amount
 * selected for typing the bill's figure. */
function ExpenseForm({
  expense,
  from,
  categories,
  today,
  onCancel,
  onDone,
}: {
  expense?: Expense
  from?: DueRecurring
  categories: ExpenseCategory[]
  // The gym's today (`ExpenseMonth.today`): the latest day it may be paid on.
  today: string
  onCancel: () => void
  onDone: (message: string, saved: Expense) => void
}) {
  const words = copy.form
  const queryClient = useQueryClient()
  // The gym's today, from the API: the browser's may already be tomorrow in UTC.
  const max = today
  const [spentOn, setSpentOn] = useState(expense?.spent_on ?? from?.due_on ?? max)
  const [amount, setAmount] = useState(expense ? String(expense.amount_clp) : from ? String(from.amount_clp) : '')
  // An expense under an archived category keeps it until it is changed; a gasto fijo's
  // archived category is not offered, so one is picked.
  const [categoryId, setCategoryId] = useState(
    expense?.category_id ?? (from && !from.category_archived ? from.category_id : ''),
  )
  const [payee, setPayee] = useState(expense?.payee ?? from?.payee ?? '')
  const [method, setMethod] = useState<ExpenseMethod | ''>(expense?.method ?? from?.method ?? '')
  const amountRef = useRef<HTMLInputElement>(null)
  // From a gasto fijo, the amount is last bill's: selected, so typing replaces it.
  useEffect(() => {
    if (!from) return
    amountRef.current?.focus()
    amountRef.current?.select()
  }, [from])
  const [note, setNote] = useState(expense?.note ?? '')
  // The cobro extra that recovers it (#318): picked by who reads cobros, kept as it was
  // by anyone else.
  const [extraChargeId, setExtraChargeId] = useState(expense?.extra_charge_id ?? '')
  const access = useQuery(myAccessQuery())
  const picksCharge = readsLedger(access.data)
  const charges = useQuery({ ...chargesQuery(), enabled: picksCharge })
  const [file, setFile] = useState<File | null>(null)
  const [removeReceipt, setRemoveReceipt] = useState(false)
  const [checked, setChecked] = useState(false)
  const receiptId = useId()
  const receiptLabelId = useId()

  const amountClp = Number(amount)
  const amountOk = amountClp > 0
  const dayOk = spentOn !== '' && spentOn <= max
  const categoryOk = categoryId !== ''
  const fileProblem = file ? proofProblem(file) : null
  const archivedCurrent =
    expense && !categories.some((c) => c.id === expense.category_id)
      ? { id: expense.category_id, name: copy.archivedCategory(expense.category_name) }
      : null

  const draft = (): ExpenseDraft => ({
    spent_on: spentOn,
    amount_clp: amountClp,
    category_id: categoryId,
    payee: payee.trim() || null,
    method: method || null,
    note: note.trim() || null,
    extra_charge_id: extraChargeId || null,
  })
  const save = useSubmit({
    offline: 'refuse',
    mutationFn: ({ draft, receipt }: { draft: ExpenseDraft; receipt: ReceiptChange }) =>
      expense
        ? changeExpense(expense.id, changedFields(expense, draft), receipt)
        : recordExpense(draft, receipt && receipt !== 'remove' ? receipt.file : null, from?.id ?? null),
    onSuccess: (saved: Expense) => {
      void queryClient.invalidateQueries({ queryKey: ['expenses'] })
      // A cobro's "Gastos asociados" reads the expenses that name it.
      void queryClient.invalidateQueries({ queryKey: ['extra', 'charge'] })
      onDone(expense ? words.changed : words.saved(clp(saved.amount_clp)), saved)
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!amountOk || !dayOk || !categoryOk || fileProblem) return
    const receipt: ReceiptChange = file ? { file } : removeReceipt ? 'remove' : null
    save.mutate({ draft: draft(), receipt })
  }
  const fileError = fileProblem && { type: words.fileType, size: words.fileSize, empty: words.fileEmpty }[fileProblem]

  const title = expense ? words.editTitle : from ? copy.due.recordWhat(from.category_name) : words.newTitle
  return (
    <form className={cardClass({}, 'expenses__form')} aria-label={title} onSubmit={submit} noValidate>
      <h2 className="expenses__form-title">{title}</h2>
      <div className="expenses__fields">
        <Field label={words.spentOn} hint={words.spentOnHint} error={checked && !dayOk && words.dayNeeded}>
          {(props) => (
            <Input {...props} type="date" max={max} value={spentOn} onChange={(e) => setSpentOn(e.target.value)} />
          )}
        </Field>
        <Field
          label={words.amount}
          hint={from?.amount_kind === 'estimated' ? copy.due.estimateHint(clp(from.amount_clp)) : undefined}
          error={checked && !amountOk && words.amountNeeded}
        >
          {(props) => (
            <Input
              {...props}
              ref={amountRef}
              inputMode="numeric"
              autoComplete="off"
              value={amount === '' ? '' : Number(amount).toLocaleString('es-CL')}
              onChange={(e) => setAmount(digits(e.target.value))}
            />
          )}
        </Field>
        <Field label={words.category} error={checked && !categoryOk && words.categoryNeeded}>
          {(props) => (
            <Select {...props} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              {categoryId === '' && <option value="">{words.pickCategory}</option>}
              {archivedCurrent && <option value={archivedCurrent.id}>{archivedCurrent.name}</option>}
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={words.payee} hint={words.payeeHint}>
          {(props) => <Input {...props} maxLength={200} value={payee} onChange={(e) => setPayee(e.target.value)} />}
        </Field>
        <Field label={words.method}>
          {(props) => (
            <Select {...props} value={method} onChange={(e) => setMethod(e.target.value as ExpenseMethod | '')}>
              <option value="">{words.noMethod}</option>
              {EXPENSE_METHODS.map((m) => (
                <option key={m} value={m}>
                  {copy.method[m]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {picksCharge && (charges.data?.length ?? 0) > 0 && (
          <Field label={words.extraCharge} hint={words.extraChargeHint} className="expenses__wide">
            {(props) => (
              <Select {...props} value={extraChargeId} onChange={(e) => setExtraChargeId(e.target.value)}>
                <option value="">{words.noExtraCharge}</option>
                {charges.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        <Field label={words.note} className="expenses__wide">
          {(props) => <Textarea {...props} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        <div className="field expenses__wide">
          <span className="field__label" id={receiptLabelId}>
            {words.receipt}
          </span>
          <div className="expenses__file">
            <input
              id={receiptId}
              className="visually-hidden"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,.heic,.heif,application/pdf"
              aria-labelledby={receiptLabelId}
              aria-describedby={`${receiptId}-hint`}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <label htmlFor={receiptId} className={buttonClass()}>
              {words.chooseFile}
            </label>
            {file && <span className="expenses__file-name">{file.name}</span>}
          </div>
          <p id={`${receiptId}-hint`} className="field__hint">
            {expense?.has_receipt && !file ? (removeReceipt ? words.receiptRemoved : words.receiptKept) : words.receiptHint}
          </p>
          {checked && fileError && <FieldError>{fileError}</FieldError>}
        </div>
        {expense?.has_receipt && !file && (
          <div className="expenses__wide">
            <Button variant="ghost" onClick={() => setRemoveReceipt(!removeReceipt)}>
              {removeReceipt ? words.receiptUndo : words.receiptRemove}
            </Button>
          </div>
        )}
      </div>
      {expense && <p className="expenses__meta">{words.changeNote}</p>}
      {save.error && <Banner tone="error">{failureOf(save.error)}</Banner>}
      <div className="expenses__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {words.cancel}
        </Button>
        <Button type="submit" variant="primary" busy={save.isPending}>
          {save.isPending ? words.working : expense ? words.saveChange : words.save}
        </Button>
      </div>
    </form>
  )
}

function VoidForm({
  expense,
  onCancel,
  onDone,
}: {
  expense: Expense
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const words = copy.voidForm
  const queryClient = useQueryClient()
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''
  const cancel = useSubmit({
    offline: 'refuse',
    mutationFn: () => voidExpense(expense.id, reason.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['expenses'] })
      onDone(words.done)
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (reasonOk) cancel.mutate()
  }
  const title = words.title(`${expense.category_name} · ${clp(expense.amount_clp)}`)
  return (
    <form className={cardClass({}, 'expenses__form')} aria-label={title} onSubmit={submit} noValidate>
      <h2 className="expenses__form-title">{title}</h2>
      <p className="expenses__meta">{words.intro}</p>
      <label htmlFor={reasonId} className="field__label">
        {words.reason}
      </label>
      <Textarea
        id={reasonId}
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && <Banner tone="error">{words.reasonNeeded}</Banner>}
      {cancel.error && <Banner tone="error">{words.failed}</Banner>}
      <div className="expenses__form-actions">
        <Button disabled={cancel.isPending} onClick={onCancel}>
          {words.cancel}
        </Button>
        <Button type="submit" variant="danger" busy={cancel.isPending}>
          {cancel.isPending ? words.working : words.submit}
        </Button>
      </div>
    </form>
  )
}

type CategoryChange =
  | { kind: 'add'; name: string }
  | { kind: 'rename'; id: string; name: string }
  | { kind: 'order'; ids: string[] }
  | { kind: 'archive'; id: string }
  | { kind: 'restore'; id: string }

function runCategoryChange(change: CategoryChange): Promise<ExpenseCategory[]> {
  switch (change.kind) {
    case 'add':
      return addCategory(change.name)
    case 'rename':
      return renameCategory(change.id, change.name)
    case 'order':
      return orderCategories(change.ids)
    case 'archive':
      return archiveCategory(change.id)
    case 'restore':
      return restoreCategory(change.id)
  }
}

/** The gym's categories: renamed, added, moved up or down, archived and restored. */
function Categories({ categories }: { categories: ExpenseCategory[] }) {
  const words = copy.categories
  const queryClient = useQueryClient()
  const addId = useId()
  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState<string | null>(null)
  const live = categories.filter((c) => !c.archived)
  const archived = categories.filter((c) => c.archived)

  const change = useSubmit({
    offline: 'refuse',
    mutationFn: runCategoryChange,
    onSuccess: (data: ExpenseCategory[]) => {
      queryClient.setQueryData(expenseCategoriesQuery().queryKey, data)
      // A rename shows on every expense under it, on Finanzas' categories and on the
      // gastos fijos; an archive takes a gasto fijo off one tap.
      void queryClient.invalidateQueries({ queryKey: ['expenses', 'month'] })
      void queryClient.invalidateQueries({ queryKey: ['expenses', 'finances'] })
      void queryClient.invalidateQueries({ queryKey: ['expenses', 'recurring'] })
      setRenaming(null)
    },
  })
  const failure = change.error && (refusal(change.error) === 'name_taken' ? words.nameTaken : words.failed)
  const move = (index: number, by: number) => {
    const ids = live.map((c) => c.id)
    const [moved] = ids.splice(index, 1)
    ids.splice(index + by, 0, moved!)
    change.mutate({ kind: 'order', ids })
  }
  const add = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (trimmed === '') return
    change.mutate({ kind: 'add', name: trimmed }, { onSuccess: () => setName('') })
  }

  return (
    <Disclosure className="expenses__categories" title={words.title}>
      <p className="expenses__meta">{words.intro}</p>
      {failure && <Banner tone="error">{failure}</Banner>}
      <PlainList className="expenses__category-list">
        {live.map((c, index) => (
          <li key={c.id} className="expenses__category-row">
            {renaming === c.id ? (
              <RenameForm
                category={c}
                busy={change.isPending}
                onCancel={() => setRenaming(null)}
                onSave={(next) => change.mutate({ kind: 'rename', id: c.id, name: next })}
              />
            ) : (
              <>
                <span className="expenses__category-name">
                  {c.name}
                  <span className="expenses__meta">{words.uses(c.expenses)}</span>
                </span>
                <span className="expenses__category-actions">
                  <Button
                    icon
                    variant="ghost"
                    aria-label={words.up(c.name)}
                    disabled={index === 0 || change.isPending}
                    onClick={() => move(index, -1)}
                  >
                    <ChevronUpIcon />
                  </Button>
                  <Button
                    icon
                    variant="ghost"
                    aria-label={words.down(c.name)}
                    disabled={index === live.length - 1 || change.isPending}
                    onClick={() => move(index, 1)}
                  >
                    <ChevronDownIcon />
                  </Button>
                  <Button variant="ghost" disabled={change.isPending} onClick={() => setRenaming(c.id)}>
                    {words.rename}
                  </Button>
                  {!c.is_other && (
                    <Button
                      variant="ghost"
                      disabled={change.isPending}
                      onClick={() => change.mutate({ kind: 'archive', id: c.id })}
                    >
                      {words.archive}
                    </Button>
                  )}
                </span>
              </>
            )}
          </li>
        ))}
      </PlainList>
      <form className="expenses__add" onSubmit={add}>
        <label htmlFor={addId} className="field__label">
          {words.addLabel}
        </label>
        <div className="expenses__add-row">
          <Input id={addId} maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" disabled={name.trim() === ''} busy={change.isPending}>
            {words.add}
          </Button>
        </div>
      </form>
      {archived.length > 0 && (
        <>
          <h3 className="expenses__subheading">{words.archivedTitle}</h3>
          <PlainList className="expenses__category-list">
            {archived.map((c) => (
              <li key={c.id} className="expenses__category-row">
                <span className="expenses__category-name">
                  {c.name}
                  <span className="expenses__meta">{words.uses(c.expenses)}</span>
                </span>
                <Button
                  variant="ghost"
                  disabled={change.isPending}
                  onClick={() => change.mutate({ kind: 'restore', id: c.id })}
                >
                  {words.restore}
                </Button>
              </li>
            ))}
          </PlainList>
        </>
      )}
    </Disclosure>
  )
}

function RenameForm({
  category,
  busy,
  onCancel,
  onSave,
}: {
  category: ExpenseCategory
  busy: boolean
  onCancel: () => void
  onSave: (name: string) => void
}) {
  const words = copy.categories
  const [name, setName] = useState(category.name)
  const id = useId()
  return (
    <form
      className="expenses__rename"
      onSubmit={(event) => {
        event.preventDefault()
        if (name.trim() !== '') onSave(name.trim())
      }}
    >
      <label htmlFor={id} className="visually-hidden">
        {words.nameLabel(category.name)}
      </label>
      <Input id={id} maxLength={60} value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      <Button type="submit" variant="primary" busy={busy} disabled={name.trim() === ''}>
        {words.save}
      </Button>
      <Button variant="ghost" disabled={busy} onClick={onCancel}>
        {words.cancel}
      </Button>
    </form>
  )
}
