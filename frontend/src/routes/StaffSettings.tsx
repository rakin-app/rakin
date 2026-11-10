import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { myRoleQuery, type StaffRole } from '../api/me'
import {
  changeStaffRole,
  INVITABLE_ROLES,
  inviteStaff,
  managesRole,
  revokeStaff,
  staffQuery,
  type InvitableRole,
  type StaffMember,
} from '../api/staff'
import { validationErrors } from '../api/validation'
import { t } from '../i18n/es'
import { Field, LoadFailed, refusal } from './settingsForm'

const copy = t.admin.settings.staff

/**
 * "Equipo": who holds a role in the gym, inviting an admin or a coach, moving them
 * between the two and taking the role away. The owner manages everyone but
 * themselves; an admin only the coaches, as the API decides, so a row shows only the
 * actions the signed-in role may take.
 */
export function StaffSettings() {
  const staff = useQuery(staffQuery)
  const role = useQuery(myRoleQuery())
  const [inviting, setInviting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setInviting(false)
    setNotice(message)
  }

  if (staff.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (staff.isError) return <LoadFailed error={staff.error} message={copy.error} retry={() => void staff.refetch()} />

  return (
    <section className="settings__section" aria-label={copy.title}>
      <p className="settings__note">{copy.intro}</p>
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      {inviting ? (
        <InviteForm acting={role.data} onCancel={() => setInviting(false)} onDone={done} />
      ) : (
        <button
          type="button"
          className="settings__button settings__button--primary"
          onClick={() => {
            setNotice(null)
            setInviting(true)
          }}
        >
          {copy.add}
        </button>
      )}
      <ul className="settings__list">
        {staff.data.map((member) => (
          <StaffRow key={member.person_id} member={member} acting={role.data} onDone={done} />
        ))}
      </ul>
    </section>
  )
}

function StaffRow({
  member,
  acting,
  onDone,
}: {
  member: StaffMember
  acting: StaffRole | null | undefined
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: staffQuery.queryKey })
  const other: InvitableRole = member.role === 'admin' ? 'coach' : 'admin'

  const change = useMutation({
    mutationFn: () => changeStaffRole(member.person_id, other),
    onSuccess: async (answer) => {
      onDone(copy.roleChanged(answer.name, copy.roles[answer.role]!))
      await refresh()
    },
  })
  const revoke = useMutation({
    mutationFn: () => revokeStaff(member.person_id),
    onSuccess: async () => {
      setConfirming(false)
      onDone(copy.revoked(member.name))
      await refresh()
    },
  })
  // Moving to the other role needs managing both: only the owner moves anyone to or from admin.
  const mayChange = managesRole(acting, member.role) && managesRole(acting, other)
  const mayRevoke = managesRole(acting, member.role)
  const pending = change.isPending || revoke.isPending

  return (
    <li className="settings__card settings__plan" aria-label={member.name}>
      <div className="settings__plan-text">
        <span className="settings__plan-name">
          {member.name}
          <span className="settings__tag">{copy.roles[member.role]}</span>
        </span>
        <span className="settings__detail">{[member.phone, member.email].filter(Boolean).join(' · ')}</span>
      </div>
      {(change.isError || revoke.isError) && (
        <p className="settings__error" role="alert">
          {copy.actionFailed}
        </p>
      )}
      {confirming ? (
        <div className="settings__plan-text" role="group" aria-label={copy.confirmRevoke(member.name)}>
          <p className="settings__detail">{copy.confirmRevoke(member.name)}</p>
          <div className="settings__actions">
            <button type="button" className="settings__button" disabled={pending} onClick={() => setConfirming(false)}>
              {copy.cancel}
            </button>
            <button
              type="button"
              className="settings__button settings__button--primary"
              disabled={pending}
              onClick={() => revoke.mutate()}
            >
              {copy.confirm}
            </button>
          </div>
        </div>
      ) : (
        (mayChange || mayRevoke) && (
          <div className="settings__actions">
            {mayChange && (
              <button type="button" className="settings__button" disabled={pending} onClick={() => change.mutate()}>
                {other === 'admin' ? copy.makeAdmin : copy.makeCoach}
              </button>
            )}
            {mayRevoke && (
              <button type="button" className="settings__button" disabled={pending} onClick={() => setConfirming(true)}>
                {copy.revoke}
              </button>
            )}
          </div>
        )
      )}
    </li>
  )
}

type Drafts = { name: string; phone: string; email: string; role: InvitableRole }

function InviteForm({
  acting,
  onCancel,
  onDone,
}: {
  acting: StaffRole | null | undefined
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const roles = INVITABLE_ROLES.filter((r) => managesRole(acting, r))
  const [drafts, setDrafts] = useState<Drafts>({ name: '', phone: '', email: '', role: 'coach' })
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  const save = useMutation({
    mutationFn: () => inviteStaff(drafts),
    onSuccess: async (answer) => {
      onDone(copy.invited(answer.name, answer.email ?? drafts.email))
      await queryClient.invalidateQueries({ queryKey: staffQuery.queryKey })
    },
  })
  const taken = save.error instanceof ApiError && save.error.status === 409
  const errors = validationErrors(save.error)
  const error = (field: keyof Drafts) =>
    field === 'phone' && taken
      ? copy.alreadyStaff
      : field in errors
        ? refusal(errors[field]!, field, copy, drafts[field].trim() === '')
        : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <form className="settings__form" aria-label={copy.form.title} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{copy.form.title}</h2>
      <Field label={copy.form.name} error={error('name')}>
        {(props) => (
          <input
            {...props}
            className="settings__input"
            type="text"
            maxLength={200}
            autoComplete="off"
            value={drafts.name}
            onChange={(e) => set('name', e.target.value)}
          />
        )}
      </Field>
      <Field label={copy.form.phone} error={error('phone')}>
        {(props) => (
          <input
            {...props}
            className="settings__input"
            type="tel"
            inputMode="tel"
            autoComplete="off"
            value={drafts.phone}
            onChange={(e) => set('phone', e.target.value)}
          />
        )}
      </Field>
      <Field label={copy.form.email} hint={copy.form.emailHint} error={error('email')}>
        {(props) => (
          <input
            {...props}
            className="settings__input"
            type="email"
            inputMode="email"
            autoComplete="off"
            value={drafts.email}
            onChange={(e) => set('email', e.target.value)}
          />
        )}
      </Field>
      <Field
        label={copy.form.role}
        hint={roles.includes('admin') ? undefined : copy.form.adminOnlyHint}
        error={error('role')}
      >
        {(props) => (
          <select
            {...props}
            className="settings__input"
            value={drafts.role}
            onChange={(e) => set('role', e.target.value)}
          >
            {roles.map((r) => (
              <option key={r} value={r}>
                {copy.roles[r]}
              </option>
            ))}
          </select>
        )}
      </Field>
      {save.isError && (
        <p className="settings__error" role="alert">
          {taken || Object.keys(errors).length > 0 ? copy.invalid : copy.failed}
        </p>
      )}
      <div className="settings__actions">
        <button type="button" className="settings__button" disabled={save.isPending} onClick={onCancel}>
          {copy.cancel}
        </button>
        <button type="submit" className="settings__button settings__button--primary" disabled={save.isPending}>
          {save.isPending ? copy.working : copy.submit}
        </button>
      </div>
    </form>
  )
}
