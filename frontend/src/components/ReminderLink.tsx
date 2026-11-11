import { useQueryClient } from '@tanstack/react-query'
import { logReminder, ordinal, type PaymentReminder } from '../api/reminders'
import { t } from '../i18n/es'
import { buttonClass } from './Button'
import { WhatsAppIcon } from './icons'
import { useSubmit } from '../api/submit'

const copy = t.admin.reminders

/**
 * The wa.me payment reminder (#55): opens WhatsApp on the message, to the member or
 * their guardian, and records that it was opened. It says which reminder it is, "2.º
 * aviso", and stands out only when the gym's cadence says the next one is due.
 * Nothing when there is no WhatsApp to send it on.
 */
export function ReminderLink({ reminder, label }: { reminder: PaymentReminder; label?: string }) {
  const queryClient = useQueryClient()
  // The link opens WhatsApp itself; this only records that it was opened.
  const log = useSubmit({
    mutationFn: () => logReminder(reminder.billing_period_id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['ledger', 'reminders'] }),
  })
  if (!reminder.whatsapp_url) return null
  const next = ordinal(reminder.reminders_sent + 1)
  const aria =
    reminder.contact_name === reminder.person_name
      ? copy.write(reminder.person_name, next)
      : copy.writeFor(reminder.contact_name, reminder.person_name, next)
  return (
    <a
      href={reminder.whatsapp_url}
      target="_blank"
      rel="noopener noreferrer"
      className={buttonClass({ variant: reminder.reminder_due ? 'secondary' : 'ghost' })}
      aria-label={aria}
      onClick={() => log.mutate()}
      // A middle-click opens it in a new tab too.
      onAuxClick={(event) => {
        if (event.button === 1) log.mutate()
      }}
    >
      <WhatsAppIcon />
      <span>{label ?? copy.next(next)}</span>
    </a>
  )
}
