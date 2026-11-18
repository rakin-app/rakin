import type { ReactNode } from 'react'
import { cx } from './classNames'
import './StatusPill.css'

export type StatusTone = 'success' | 'accent' | 'warning' | 'danger' | 'neutral'

/**
 * Every status a pill shows, across the admin and the student page. A membership's
 * (`active`…`cancelled`), a payment's (`pending`, `validated`, `rejected`) and a period's
 * (`paid`, `open`, `due`, `overdue`, `in_review`); `none` is a member with no plan. A
 * requirement's (#349) is `done`, `expiring`, `overdue` once past its date, or `required`,
 * never done. A gym the platform's panel suspended (#439) is `suspended`.
 */
export type Status =
  | 'active'
  | 'trial'
  | 'frozen'
  | 'lapsed'
  | 'cancelled'
  | 'pending'
  | 'in_review'
  | 'validated'
  | 'rejected'
  | 'paid'
  | 'open'
  | 'due'
  | 'overdue'
  | 'freeze'
  | 'none'
  | 'done'
  | 'expiring'
  | 'required'
  | 'suspended'

/**
 * The one mapping from status to colour: green is settled, blue waits on the gym, orange is
 * overdue (a payment, or a requirement past its date) and nothing else, red is a payment the
 * gym refused.
 */
export const STATUS_TONE: Record<Status, StatusTone> = {
  active: 'success',
  validated: 'success',
  paid: 'success',
  pending: 'accent',
  in_review: 'accent',
  overdue: 'warning',
  rejected: 'danger',
  lapsed: 'neutral',
  trial: 'neutral',
  frozen: 'neutral',
  cancelled: 'neutral',
  open: 'neutral',
  due: 'neutral',
  freeze: 'neutral',
  none: 'neutral',
  done: 'success',
  expiring: 'accent',
  required: 'neutral',
  suspended: 'neutral',
}

/** A status, not a control: it never looks tappable. `inverse` on a dark surface. */
export function StatusPill({
  status,
  inverse,
  children,
}: {
  status: Status
  inverse?: boolean
  children: ReactNode
}) {
  const tone = STATUS_TONE[status]
  return (
    <span className={cx('status-pill', `status-pill--${tone}`, inverse && 'status-pill--inverse')} data-status={status}>
      {children}
    </span>
  )
}
