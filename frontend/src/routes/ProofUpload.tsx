import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type ChangeEvent, type FormEvent } from 'react'
import {
  isConflict,
  openPeriodsQuery,
  PROOF_TYPES,
  proofProblem,
  submitProof,
  UploadFailed,
  type OpenPeriod,
} from '../api/proofs'
import { t } from '../i18n/es'
import './ProofUpload.css'

const copy = t.me.proof

/**
 * "Subir comprobante": pick the period, say how much was transferred, and
 * send a photo or PDF of the transfer. The file goes straight to storage;
 * the payment then waits, pending, for the gym to check it.
 */
export function ProofUpload() {
  const periods = useQuery(openPeriodsQuery())
  const [sent, setSent] = useState(false)

  if (periods.isPending) return <p className="proof__note">{copy.loading}</p>
  if (periods.isError) {
    return (
      <p className="proof__note" role="alert">
        {copy.error}
      </p>
    )
  }

  return (
    <section className="proof" aria-labelledby="proof-title">
      <h2 id="proof-title" className="proof__title">
        {copy.title}
      </h2>
      {sent ? (
        <div className="proof__sent" role="status">
          <p>{copy.sent}</p>
          <button type="button" className="proof__button" onClick={() => setSent(false)}>
            {copy.another}
          </button>
        </div>
      ) : periods.data.length === 0 ? (
        <p className="proof__note">{copy.none}</p>
      ) : (
        <ProofForm periods={periods.data} onSent={() => setSent(true)} />
      )}
    </section>
  )
}

function ProofForm({ periods, onSent }: { periods: OpenPeriod[]; onSent: () => void }) {
  const queryClient = useQueryClient()
  const [periodId, setPeriodId] = useState(periods[0]!.id)
  const period = periods.find((p) => p.id === periodId) ?? periods[0]!
  const [amount, setAmount] = useState(String(period.outstanding_clp))
  const [file, setFile] = useState<File | null>(null)
  const ids = { amount: useId(), camera: useId(), choose: useId(), hint: useId() }

  const send = useMutation({
    mutationFn: ({ file, amount }: { file: File; amount: number }) => submitProof(file, period.id, amount),
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
    const picked = periods.find((p) => p.id === id)
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
        {periods.map((p) => (
          <label key={p.id} className="proof__period">
            <input
              type="radio"
              name="period"
              value={p.id}
              checked={p.id === period.id}
              onChange={() => pickPeriod(p.id)}
            />
            <span>
              <span className="proof__period-name">{copy.period(p.person_name, p.plan_name, t.common.day(p.due_date))}</span>
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
      <input
        id={ids.amount}
        className="proof__input"
        inputMode="numeric"
        pattern="[0-9]*"
        required
        value={amount}
        onChange={(e) => setAmount(e.target.value.replace(/\D/g, ''))}
      />

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
          onChange={pickFile}
        />
        <label htmlFor={ids.camera} className="proof__button">
          {copy.camera}
        </label>
        <input
          id={ids.choose}
          className="visually-hidden proof__file"
          type="file"
          accept={[...PROOF_TYPES, '.heic', '.heif'].join(',')}
          aria-describedby={ids.hint}
          onChange={pickFile}
        />
        <label htmlFor={ids.choose} className="proof__button">
          {copy.choose}
        </label>
      </div>
      <p id={ids.hint} className="proof__note">
        {file ? copy.chosen(file.name) : copy.fileHint}
      </p>

      {(problem || send.error || (amount !== '' && !amountOk)) && (
        <p className="proof__error" role="alert">
          {problem ? copy.problem[problem] : send.error ? refusal(send.error) : copy.problem.amount}
        </p>
      )}

      <button
        type="submit"
        className="proof__button proof__button--primary"
        disabled={!file || problem !== null || !amountOk || send.isPending}
      >
        {send.isPending ? copy.sending : copy.submit}
      </button>
    </form>
  )
}

function refusal(error: unknown): string {
  if (isConflict(error)) return copy.refused.paid
  if (error instanceof UploadFailed || error instanceof TypeError) return copy.refused.upload
  return copy.refused.failed
}
