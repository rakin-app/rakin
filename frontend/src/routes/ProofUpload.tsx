import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type ChangeEvent, type FormEvent } from 'react'
import { myLinesQuery } from '../api/extraCharges'
import {
  isConflict,
  openPeriodsQuery,
  PROOF_TYPES,
  proofProblem,
  submitProof,
  submitSplitProof,
  UploadFailed,
  type OpenPeriod,
  type ProofTarget,
} from '../api/proofs'
import { Button, buttonClass } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import './ProofUpload.css'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'
import { Banner, Card, SectionHeader } from '../components/Card'

const copy = t.me.proof

/** One thing a proof can pay, as the form lists it. */
type Payable = ProofTarget & { label: string; outstanding_clp: number; pending_clp: number }

/** The periods one transfer can pay together (#66): each still owing, with no proof in review. */
export function payableTogether(periods: OpenPeriod[]): OpenPeriod[] {
  return periods.filter((p) => p.outstanding_clp > 0 && p.pending_clp === 0)
}

/** Whether `periods` are more than one person's: a family's, to pay in one transfer. */
export function isFamily(periods: OpenPeriod[]): boolean {
  return new Set(periods.map((p) => p.person_id)).size > 1
}

/**
 * "Subir comprobante": pick what it pays, a plan's period or a cobro extra (#195), say
 * how much was transferred, and send a photo or PDF of the transfer. The file goes
 * straight to storage; the payment then waits, pending, for the gym to check it.
 * `initial` is the cobro line to start on, when the student came from one. `together`
 * is a guardian's one transfer for several periods, theirs and their dependents' (#66):
 * every period ticked is paid in full, and the proof is split over them.
 */
export function ProofUpload({ initial, together = false }: { initial?: string; together?: boolean } = {}) {
  const periods = useQuery(openPeriodsQuery())
  const lines = useQuery(myLinesQuery())
  const [sent, setSent] = useState(false)
  const titleId = useId()

  // The cobros are waited for only when the upload opened on one. Otherwise the plan's
  // periods show at once, and a cobro list that is slow or cannot load is left out, as
  // if there were none, rather than standing in the way of paying the plan.
  if (periods.isPending || (initial !== undefined && lines.isPending)) {
    return <Loading className="proof__note">{copy.loading}</Loading>
  }
  if (periods.isError) {
    return (
      <p className="proof__note" role="alert">
        {copy.error}
      </p>
    )
  }

  const payables: Payable[] = [
    ...periods.data.map((p) => ({
      kind: 'period' as const,
      id: p.id,
      label: copy.period(p.person_name, p.plan_name, t.common.longDay(p.due_date)),
      outstanding_clp: p.outstanding_clp,
      pending_clp: p.pending_clp,
    })),
    ...(lines.data ?? []).map((l) => ({
      kind: 'line' as const,
      id: l.id,
      label: copy.line(l.person_name, l.title, t.common.longDay(l.due_date)),
      outstanding_clp: l.outstanding_clp,
      pending_clp: l.pending_clp,
    })),
  ]

  return (
    <Card className="proof" aria-labelledby={titleId}>
      <SectionHeader id={titleId} title={copy.title} />
      {sent ? (
        <div className="proof__sent" role="status">
          <p>{copy.sent}</p>
          <Button onClick={() => setSent(false)}>
            {copy.another}
          </Button>
        </div>
      ) : together ? (
        payableTogether(periods.data).length < 2 ? (
          <p className="proof__note">{copy.none}</p>
        ) : (
          <TogetherForm periods={payableTogether(periods.data)} onSent={() => setSent(true)} />
        )
      ) : payables.length === 0 ? (
        <p className="proof__note">{copy.none}</p>
      ) : (
        <ProofForm payables={payables} initial={initial} onSent={() => setSent(true)} />
      )}
    </Card>
  )
}

function ProofForm({ payables, initial, onSent }: { payables: Payable[]; initial?: string; onSent: () => void }) {
  const queryClient = useQueryClient()
  const [periodId, setPeriodId] = useState((payables.find((p) => p.id === initial) ?? payables[0]!).id)
  const period = payables.find((p) => p.id === periodId) ?? payables[0]!
  const [amount, setAmount] = useState(String(period.outstanding_clp))
  const [file, setFile] = useState<File | null>(null)
  // Raw digits while they type, so the caret stays where they put it; `$45.000` otherwise.
  const [editing, setEditing] = useState(false)
  const ids = { amount: useId() }

  const send = useSubmit({
    offline: 'refuse',
    mutationFn: ({ file, amount }: { file: File; amount: number }) =>
      submitProof(file, { kind: period.kind, id: period.id }, amount),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['me'] })
      onSent()
    },
  })

  const amountClp = Number(amount)
  const amountOk = Number.isInteger(amountClp) && amountClp > 0
  const problem = file ? proofProblem(file) : null

  const pickPeriod = (id: string) => {
    setPeriodId(id)
    const picked = payables.find((p) => p.id === id)
    if (picked) setAmount(String(picked.outstanding_clp))
  }
  const pickFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null)
    send.reset()
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (file && !problem && amountOk) send.mutate({ file, amount: amountClp })
  }

  return (
    <form className="proof__form" onSubmit={submit}>
      <fieldset className="proof__periods">
        <legend className="proof__label">{copy.periodLabel}</legend>
        {payables.map((p) => (
          <label key={p.id} className="proof__period">
            <input
              type="radio"
              name="period"
              value={p.id}
              checked={p.id === period.id}
              onChange={() => pickPeriod(p.id)}
            />
            <span>
              <span className="proof__period-name">{p.label}</span>
              <span className="proof__period-detail">{copy.outstanding(t.common.clp(p.outstanding_clp))}</span>
              {p.pending_clp > 0 && (
                <span className="proof__period-detail proof__period-detail--review">
                  {copy.inReview(t.common.clp(p.pending_clp))}
                </span>
              )}
            </span>
          </label>
        ))}
      </fieldset>

      <label htmlFor={ids.amount} className="proof__label">
        {copy.amountLabel}
      </label>
      {/* Pesos as the card writes them, `$45.000`, once out of the field; the state keeps the digits. */}
      <Input
        id={ids.amount}
        inputMode="numeric"
        required
        value={editing || amount === '' ? amount : t.common.clp(Number(amount))}
        onFocus={() => setEditing(true)}
        onBlur={() => setEditing(false)}
        onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').replace(/^0+/, '').slice(0, 12))}
      />

      <ProofFile file={file} onPick={pickFile} />

      {(problem || send.error || (amount !== '' && !amountOk)) && (
        <Banner tone="error">
          {problem ? copy.problem[problem] : send.error ? refusal(send.error) : copy.problem.amount}
        </Banner>
      )}

      <Button
        type="submit"
        variant="primary"
        disabled={!file || problem !== null || !amountOk || send.isPending} busy={send.isPending}
      >
        {send.isPending ? copy.sending : copy.submit}
      </Button>
    </form>
  )
}

/** The proof itself: a photo from the camera, or a file or image already on the phone. */
function ProofFile({ file, onPick }: { file: File | null; onPick: (event: ChangeEvent<HTMLInputElement>) => void }) {
  const ids = { camera: useId(), choose: useId(), hint: useId() }
  return (
    <>
      <span className="proof__label">{copy.fileLabel}</span>
      <div className="proof__pickers">
        {/* `capture` opens the camera on a phone; the other input offers the gallery and
            files. Each input sits before its label, which CSS shows as the button and
            outlines while the hidden input has focus. */}
        <input
          id={ids.camera}
          className="visually-hidden proof__file"
          type="file"
          accept="image/*"
          capture="environment"
          aria-describedby={ids.hint}
          onChange={onPick}
        />
        <label htmlFor={ids.camera} className={buttonClass()}>
          {copy.camera}
        </label>
        <input
          id={ids.choose}
          className="visually-hidden proof__file"
          type="file"
          accept={[...PROOF_TYPES, '.heic', '.heif'].join(',')}
          aria-describedby={ids.hint}
          onChange={onPick}
        />
        <label htmlFor={ids.choose} className={buttonClass()}>
          {copy.choose}
        </label>
      </div>
      <p id={ids.hint} className="proof__note">
        {file ? copy.chosen(file.name) : copy.fileHint}
      </p>
    </>
  )
}

/**
 * One transfer for several periods (#66): each ticked period is paid what it still
 * owes, the total is what to transfer, and one proof backs them all.
 */
function TogetherForm({ periods, onSent }: { periods: OpenPeriod[]; onSent: () => void }) {
  const words = copy.together
  const queryClient = useQueryClient()
  const [picked, setPicked] = useState(() => new Set(periods.map((p) => p.id)))
  const [file, setFile] = useState<File | null>(null)
  const chosen = periods.filter((p) => picked.has(p.id))
  const total = chosen.reduce((sum, p) => sum + p.outstanding_clp, 0)

  const send = useSubmit({
    offline: 'refuse',
    mutationFn: (file: File) =>
      submitSplitProof(
        file,
        chosen.map((p) => ({ billing_period_id: p.id, amount_clp: p.outstanding_clp })),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['me'] })
      onSent()
    },
  })

  const problem = file ? proofProblem(file) : null
  const enough = chosen.length >= 2
  const toggle = (id: string) => {
    setPicked((now) => {
      const next = new Set(now)
      if (!next.delete(id)) next.add(id)
      return next
    })
    send.reset()
  }
  const pickFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null)
    send.reset()
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (file && !problem && enough) send.mutate(file)
  }

  return (
    <form className="proof__form" onSubmit={submit}>
      <fieldset className="proof__periods">
        <legend className="proof__label">{words.periodsLabel}</legend>
        {periods.map((p) => (
          <label key={p.id} className="proof__period">
            <input type="checkbox" checked={picked.has(p.id)} onChange={() => toggle(p.id)} />
            <span>
              <span className="proof__period-name">
                {copy.period(p.person_name, p.plan_name, t.common.longDay(p.due_date))}
              </span>
              <span className="proof__period-detail">{copy.outstanding(t.common.clp(p.outstanding_clp))}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <p className="proof__total" role="status">
        <span className="proof__label">{words.total}</span>
        <span className="proof__total-amount">{t.common.clp(total)}</span>
      </p>

      <ProofFile file={file} onPick={pickFile} />

      {(problem || send.error || !enough) && (
        <Banner tone={problem || send.error ? 'error' : 'info'}>
          {problem ? copy.problem[problem] : send.error ? refusal(send.error) : words.pickTwo}
        </Banner>
      )}

      <Button
        type="submit"
        variant="primary"
        disabled={!file || problem !== null || !enough || send.isPending} busy={send.isPending}
      >
        {send.isPending ? copy.sending : words.submit(t.common.clp(total))}
      </Button>
    </form>
  )
}

function refusal(error: unknown): string {
  if (isConflict(error)) return copy.refused.paid
  if (error instanceof UploadFailed || error instanceof TypeError) return copy.refused.upload
  return copy.refused.failed
}
