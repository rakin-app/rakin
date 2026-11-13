import { useQueryClient } from '@tanstack/react-query'
import { useId } from 'react'
import { ApiError } from '../api/client'
import { emailReminder, type PaymentReminder } from '../api/reminders'
import { useSubmit } from '../api/submit'
import { toDate } from '../format'
import { t } from '../i18n/es'
import { Button } from './Button'
import { MailIcon } from './icons'
import './EmailReminder.css'

const copy = t.admin.reminders.email

/** `hoy`, `ayer`, `hace 3 días`: calendar days from `iso` to `now`. */
export function daysAgo(iso: string, now: Date): string {
  const then = toDate(iso)
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((day(now) - day(then)) / 86_400_000)
  if (days <= 0) return copy.today
  if (days === 1) return copy.yesterday
  return copy.daysAgo(days)
}

/**
 * "Enviar recordatorio" (#260): the overdue email about the period, sent now to the
 * member or their guardian, as the nightly job sends it on its own days. It says when
 * the last one went out. A period gets one a day, so once one did today, or with no
 * email to send it to, the button stays on screen disabled with the reason beside it
 * (#266): a hidden button reads as a missing feature. A double tap sends once
 * (`useSubmit`). Nothing for a period not yet overdue (a rejected proof sent early)
 * with none sent.
 */
export function EmailReminder({ reminder }: { reminder: PaymentReminder }) {
  const queryClient = useQueryClient()
  const reasonId = useId()
  const send = useSubmit({
    offline: 'refuse',
    mutationFn: () => emailReminder(reminder.billing_period_id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['ledger', 'reminders'] }),
  })
  const overdue = reminder.days_overdue >= 0
  if (!overdue && !reminder.emailed_at && !send.isSuccess) return null
  const reason =
    reminder.emailed_today || send.isSuccess ? copy.sentToday : !reminder.can_email ? copy.noEmail : null
  const aria =
    reminder.contact_name === reminder.person_name
      ? copy.sendTo(reminder.person_name)
      : copy.sendFor(reminder.contact_name, reminder.person_name)
  return (
    <div className="email-reminder">
      {overdue && (
        <Button
          variant="ghost"
          busy={send.isPending}
          disabled={reason !== null}
          aria-label={aria}
          aria-describedby={reason ? reasonId : undefined}
          onClick={() => send.mutate()}
        >
          <MailIcon />
          <span>{copy.send}</span>
        </Button>
      )}
      {overdue && reason && (
        <span id={reasonId} className="email-reminder__note">
          {reason}
        </span>
      )}
      {send.isSuccess ? (
        <span className="email-reminder__note" role="status">
          {copy.sent(send.data.contact_name)}
        </span>
      ) : (
        reminder.emailed_at && (
          <span className="email-reminder__note">{copy.last(daysAgo(reminder.emailed_at, new Date()))}</span>
        )
      )}
      {send.isError && (
        <span className="email-reminder__error" role="alert">
          {refusal(send.error)}
        </span>
      )}
    </div>
  )
}

function refusal(error: Error): string {
  const refused = copy.refused
  if (error instanceof ApiError && error.status === 409) {
    const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
    if (typeof code === 'string' && code in refused) return refused[code as keyof typeof refused]
  }
  return copy.failed
}
