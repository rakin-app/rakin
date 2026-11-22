import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import { proofContentType, UploadFailed } from './proofs'
import { submissionKey } from './submit'

// Gastos (#314): what the gym spends, apart from billing. Read with `expenses_read`,
// written with `expenses_write` (backend `app.api.expenses`).

export type ExpenseMethod = 'transfer' | 'cash' | 'card' | 'other'

export const EXPENSE_METHODS: readonly ExpenseMethod[] = ['transfer', 'cash', 'card', 'other']

export type Expense = {
  id: string
  spent_on: string
  amount_clp: number
  category_id: string
  category_name: string
  payee: string | null
  method: ExpenseMethod | null
  note: string | null
  has_receipt: boolean
  // The gasto fijo it was recorded from (#315).
  recurring_id: string | null
  // The cobro extra that recovers it (#318), and its title: null to whoever does not
  // read cobros (`money_read`), who still sees that it names one.
  extra_charge_id: string | null
  extra_charge_title: string | null
  created_by_name: string | null
  created_at: string
  updated_at: string | null
  // Anulado: listed struck through, counted nowhere.
  voided_at: string | null
  voided_by_name: string | null
  void_reason: string | null
}

/** A month of expenses, newest first; the total and count are of those not voided. */
export type ExpenseMonth = {
  month: string
  current_month: string
  // The gym's today, in its timezone: the latest day an expense may be paid on.
  today: string
  category_id: string | null
  total_clp: number
  count: number
  items: Expense[]
}

export type ExpenseCategory = {
  id: string
  name: string
  sort: number
  // Otros, which cannot be archived.
  is_other: boolean
  archived: boolean
  expenses: number
}

/** What the form sends: a new expense, or every field of one being corrected. */
export type ExpenseDraft = {
  spent_on: string
  amount_clp: number
  category_id: string
  payee: string | null
  method: ExpenseMethod | null
  note: string | null
  // The cobro extra that recovers it (#318); the picker is for who reads cobros.
  extra_charge_id: string | null
}

/** What happens to the receipt: a new file, taken off, or left as it is. */
export type ReceiptChange = { file: File } | 'remove' | null

const EXPENSES = '/api/expenses'
const CATEGORIES = `${EXPENSES}/categories`

export function expenseMonthQuery(month: string | undefined, category: string | undefined) {
  const search = new URLSearchParams()
  if (month) search.set('month', month)
  if (category) search.set('category', category)
  const query = search.toString()
  return queryOptions({
    queryKey: ['expenses', 'month', month ?? null, category ?? null],
    queryFn: () => apiFetch<ExpenseMonth>(query ? `${EXPENSES}?${query}` : EXPENSES),
  })
}

export function expenseCategoriesQuery() {
  return queryOptions({
    queryKey: ['expenses', 'categories'],
    queryFn: () => apiFetch<ExpenseCategory[]>(CATEGORIES),
  })
}

type Upload = { key: string; url: string; headers: Record<string, string> }

/** PUT `file` to storage on a presigned URL under the gym's receipts; returns its key. */
async function uploadReceipt(file: File, key: string | undefined): Promise<string> {
  const contentType = proofContentType(file)
  if (contentType === null) throw new Error(`not a receipt type: ${file.name}`)
  const upload = await apiFetch<Upload>(`${EXPENSES}/receipt-upload`, {
    method: 'POST',
    body: JSON.stringify({ content_type: contentType, size_bytes: file.size }),
    idempotencyKey: key && `${key}:upload`,
  })
  // Not `apiFetch`: the URL may be the storage's own origin.
  const put = await fetch(upload.url, { method: 'PUT', headers: upload.headers, body: file })
  if (!put.ok) throw new UploadFailed(put.status)
  return upload.key
}

/** Record an expense, its receipt uploaded first when there is one; `recurringId` is the
 * gasto fijo it is recorded from, when the form opened from one. */
export async function recordExpense(
  draft: ExpenseDraft,
  receipt: File | null,
  recurringId: string | null = null,
): Promise<Expense> {
  // Each step by its own name, so a double tap uploads to one key and records once.
  const key = submissionKey()
  const receiptKey = receipt ? await uploadReceipt(receipt, key) : null
  return apiFetch<Expense>(EXPENSES, {
    method: 'POST',
    body: JSON.stringify({ ...draft, receipt_key: receiptKey, ...(recurringId ? { recurring_id: recurringId } : {}) }),
    idempotencyKey: key && `${key}:record`,
  })
}

/** The fields of `draft` that differ from `expense` as it was loaded: a correction sends
 * only these, so two people correcting one expense at once each change only what they
 * touched. */
export function changedFields(expense: Expense, draft: ExpenseDraft): Partial<ExpenseDraft> {
  const changed: Partial<ExpenseDraft> = {}
  for (const field of Object.keys(draft) as (keyof ExpenseDraft)[]) {
    if (draft[field] !== expense[field]) Object.assign(changed, { [field]: draft[field] })
  }
  return changed
}

/** Correct an expense: the fields that changed (`changedFields`), and its receipt. */
export async function changeExpense(
  id: string,
  changes: Partial<ExpenseDraft>,
  receipt: ReceiptChange,
): Promise<Expense> {
  const key = submissionKey()
  const receiptKey = receipt && receipt !== 'remove' ? await uploadReceipt(receipt.file, key) : null
  return apiFetch<Expense>(`${EXPENSES}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      ...changes,
      ...(receiptKey ? { receipt_key: receiptKey } : {}),
      ...(receipt === 'remove' ? { remove_receipt: true } : {}),
    }),
    idempotencyKey: key && `${key}:change`,
  })
}

/** Anular, with the reason the log keeps. */
export function voidExpense(id: string, reason: string): Promise<Expense> {
  return apiFetch<Expense>(`${EXPENSES}/${encodeURIComponent(id)}/void`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

/** Where the browser opens an expense's receipt, presigned for a short while. */
export function receiptUrl(id: string): Promise<{ url: string; content_type: string }> {
  return apiFetch(`${EXPENSES}/${encodeURIComponent(id)}/receipt`)
}

export function addCategory(name: string): Promise<ExpenseCategory[]> {
  return apiFetch<ExpenseCategory[]>(CATEGORIES, { method: 'POST', body: JSON.stringify({ name }) })
}

export function renameCategory(id: string, name: string): Promise<ExpenseCategory[]> {
  return apiFetch<ExpenseCategory[]>(`${CATEGORIES}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
}

export function orderCategories(ids: string[]): Promise<ExpenseCategory[]> {
  return apiFetch<ExpenseCategory[]>(`${CATEGORIES}/order`, { method: 'POST', body: JSON.stringify({ ids }) })
}

export function archiveCategory(id: string): Promise<ExpenseCategory[]> {
  return apiFetch<ExpenseCategory[]>(`${CATEGORIES}/${encodeURIComponent(id)}/archive`, { method: 'POST' })
}

export function restoreCategory(id: string): Promise<ExpenseCategory[]> {
  return apiFetch<ExpenseCategory[]>(`${CATEGORIES}/${encodeURIComponent(id)}/restore`, { method: 'POST' })
}


// --- Gastos fijos (#315) --------------------------------------------------------------
// Rent and bills as monthly templates: Gastos lists those not yet recorded in the month,
// and a person records each. Nothing records one by itself.

/** `fixed`: recorded at its amount in one tap. `estimated`: the amount is a hint, typed
 * from the bill in the form. */
export type AmountKind = 'fixed' | 'estimated'

export type Recurring = {
  id: string
  category_id: string
  category_name: string
  // Its category was archived: it is recorded through the form, under another.
  category_archived: boolean
  payee: string | null
  method: ExpenseMethod | null
  amount_clp: number
  amount_kind: AmountKind
  day_of_month: number
  active: boolean
  created_at: string
}

/** A gasto fijo not yet recorded in the month, and the day it would be recorded on. */
export type DueRecurring = Recurring & { due_on: string }

/** Gastos fijos por registrar: the month's due templates, and those skipped for it. */
export type RecurringMonth = {
  month: string
  current_month: string
  today: string
  due: DueRecurring[]
  skipped: DueRecurring[]
}

export type RecurringDraft = {
  category_id: string
  payee: string | null
  method: ExpenseMethod | null
  amount_clp: number
  amount_kind: AmountKind
  day_of_month: number
}

const RECURRING = `${EXPENSES}/recurring`

export function recurringQuery() {
  return queryOptions({
    queryKey: ['expenses', 'recurring', 'all'],
    queryFn: () => apiFetch<Recurring[]>(RECURRING),
  })
}

export function recurringMonthQuery(month: string | undefined) {
  return queryOptions({
    queryKey: ['expenses', 'recurring', 'month', month ?? null],
    queryFn: () => apiFetch<RecurringMonth>(month ? `${RECURRING}/month?month=${month}` : `${RECURRING}/month`),
  })
}

export function addRecurring(draft: RecurringDraft): Promise<Recurring> {
  return apiFetch<Recurring>(RECURRING, { method: 'POST', body: JSON.stringify(draft) })
}

/** Edit a gasto fijo, or pause it (`active: false`) and resume it. */
export function changeRecurring(id: string, changes: Partial<RecurringDraft> & { active?: boolean }): Promise<Recurring> {
  return apiFetch<Recurring>(`${RECURRING}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** Registrar, and Registrar los fijos: the fixed templates `ids` in `month`, each at its
 * amount. Answers what it recorded; one recorded already is passed over. */
export function recordRecurring(month: string, ids: string[]): Promise<Expense[]> {
  return apiFetch<Expense[]>(`${RECURRING}/record`, {
    method: 'POST',
    body: JSON.stringify({ month, ids }),
  })
}

/** No este mes. */
export function skipRecurring(id: string, month: string): Promise<void> {
  return apiFetch<void>(`${RECURRING}/${encodeURIComponent(id)}/skip`, {
    method: 'POST',
    body: JSON.stringify({ month }),
  })
}

/** Take a No este mes back. */
export function unskipRecurring(id: string, month: string): Promise<void> {
  return apiFetch<void>(`${RECURRING}/${encodeURIComponent(id)}/skip/${month}`, { method: 'DELETE' })
}
