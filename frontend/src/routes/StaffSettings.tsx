import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { myRoleQuery, type StaffRole } from '../api/me'
import { duplicateOf } from '../api/people'
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
import { Button } from '../components/Button'
import { ListRow } from '../components/Card'
import { Input, Select } from '../components/Field'
import { formatPhone } from '../format'
import { t } from '../i18n/es'
import { EditRow, Field, LoadFailed, refusal } from './settingsForm'

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
  // The one member open to act on (#177).
  const [opened, setOpened] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setInviting(false)
    setOpened(null)
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
        <Button
          variant="primary"
          onClick={() => {
            setNotice(null)
            setInviting(true)
          }}
        >
          {copy.add}
        </Button>
      )}
      <ul className="settings__card settings__card--rows settings__menu">
        {staff.data.map((member) => (
          <StaffRow
            key={member.person_id}
            member={member}
            acting={role.data}
            open={opened === member.person_id}
            onOpen={() => {
              setNotice(null)
              setOpened(member.person_id)
            }}
            onClose={() => setOpened(null)}
            onDone={done}
          />
        ))}
      </ul>
    </section>
  )
}

/**
 * A member of the staff: a row that opens, for whoever may act on them, to move them to
 * the other role or take their access away (#177). The owner, and anyone the signed-in
 * role may not manage, is a row and nothing more.
 */
function StaffRow({
  member,
  acting,
  open,
  onOpen,
  onClose,
  onDone,
}: {
  member: StaffMember
  acting: StaffRole | null | undefined
  open: boolean
  onOpen: () => void
  onClose: () => void
  onDone: (message: string) => void
}) {
  const other: InvitableRole = member.role === 'admin' ? 'coach' : 'admin'
  // Moving to the other role needs managing both: only the owner moves anyone to or from admin.
  const mayChange = managesRole(acting, member.role) && managesRole(acting, other)
  const mayRevoke = managesRole(acting, member.role)
  const title = (
    <>
      {member.name}
      <span className="settings__tag">{copy.roles[member.role]}</span>
    </>
  )
  const detail = [member.phone && formatPhone(member.phone), member.email].filter(Boolean).join(' · ')

  if (open) {
    return (
      <li aria-label={member.name}>
        <StaffPanel member={member} other={other} mayChange={mayChange} mayRevoke={mayRevoke} onClose={onClose} onDone={onDone} />
      </li>
    )
  }
  if (!mayChange && !mayRevoke) {
    return (
      <li aria-label={member.name}>
        <ListRow title={title} detail={detail} />
      </li>
    )
  }
  return <EditRow title={title} detail={detail} onOpen={onOpen} />
}

function StaffPanel({
  member,
  other,
  mayChange,
  mayRevoke,
  onClose,
  onDone,
}: {
  member: StaffMember
  other: InvitableRole
  mayChange: boolean
  mayRevoke: boolean
  onClose: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: staffQuery.queryKey })

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
  const pending = change.isPending || revoke.isPending

  return (
    <div className="settings__card settings__form" role="group" aria-label={member.name}>
      <h2 className="settings__legend">{copy.panelTitle(member.name, copy.roles[member.role]!)}</h2>
      <p className="settings__detail">
        {[member.phone && formatPhone(member.phone), member.email].filter(Boolean).join(' · ')}
      </p>
      {(change.isError || revoke.isError) && (
        <p className="settings__error" role="alert">
          {copy.actionFailed}
        </p>
      )}
      <div className="settings__actions">
        <Button disabled={pending} onClick={onClose}>
          {copy.close}
        </Button>
        {mayChange && (
          <Button variant="primary" disabled={pending} onClick={() => change.mutate()}>
            {other === 'admin' ? copy.makeAdmin : copy.makeCoach}
          </Button>
        )}
      </div>
      {mayRevoke && (
        <div className="settings__danger">
          {confirming ? (
            <div className="settings__plan-text" role="group" aria-label={copy.confirmRevoke(member.name)}>
              <p className="settings__detail">{copy.confirmRevoke(member.name)}</p>
              <div className="settings__actions">
                <Button disabled={pending} onClick={() => setConfirming(false)}>
                  {copy.cancel}
                </Button>
                <Button variant="danger" disabled={pending} onClick={() => revoke.mutate()}>
                  {copy.confirm}
                </Button>
              </div>
            </div>
          ) : (
            <Button variant="danger" disabled={pending} onClick={() => setConfirming(true)}>
              {copy.revoke}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

type Drafts = { name: string; rut: string; email: string; phone: string; role: InvitableRole }

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
  const [drafts, setDrafts] = useState<Drafts>({ name: '', rut: '', email: '', phone: '', role: 'coach' })
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  const save = useMutation({
    // The optional ones only when typed: an empty RUT or phone is none, not an invalid one.
    mutationFn: () =>
      inviteStaff({
        name: drafts.name,
        email: drafts.email,
        rut: drafts.rut.trim() || undefined,
        phone: drafts.phone.trim() || undefined,
        role: drafts.role,
      }),
    onSuccess: async (answer) => {
      onDone(copy.invited(answer.name, answer.email ?? drafts.email))
      await queryClient.invalidateQueries({ queryKey: staffQuery.queryKey })
    },
  })
  // A 409 is someone already on the staff, or an email another person here has.
  const taken = save.error instanceof ApiError && save.error.status === 409
  const emailTaken = duplicateOf(save.error)?.code === 'email_in_gym'
  const errors = validationErrors(save.error)
  const error = (field: keyof Drafts) =>
    field === 'email' && taken
      ? emailTaken
        ? copy.emailTaken
        : copy.alreadyStaff
      : field in errors
        ? refusal(errors[field]!, field, copy, drafts[field].trim() === '')
        : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <form className="settings__card settings__form" aria-label={copy.form.title} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{copy.form.title}</h2>
      <Field label={copy.form.name} error={error('name')}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={200}
            autoComplete="off"
            value={drafts.name}
            onChange={(e) => set('name', e.target.value)}
          />
        )}
      </Field>
      <Field label={copy.form.rut} hint={copy.form.rutHint} error={error('rut')}>
        {(props) => (
          <Input
            {...props}
            type="text"
            autoComplete="off"
            value={drafts.rut}
            onChange={(e) => set('rut', e.target.value)}
          />
        )}
      </Field>
      <Field label={copy.form.phone} error={error('phone')}>
        {(props) => (
          <Input
            {...props}
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
          <Input
            {...props}
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
          <Select
            {...props}
            value={drafts.role}
            onChange={(e) => set('role', e.target.value)}
          >
            {roles.map((r) => (
              <option key={r} value={r}>
                {copy.roles[r]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {save.isError && (
        <p className="settings__error" role="alert">
          {taken || Object.keys(errors).length > 0 ? copy.invalid : copy.failed}
        </p>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? copy.working : copy.submit}
        </Button>
      </div>
    </form>
  )
}
