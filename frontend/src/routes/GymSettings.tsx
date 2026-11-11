import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import {
  ACCOUNT_TYPES,
  gymSettingsQuery,
  updateGymSettings,
  type GymSettings as Settings,
  type GymSettingsUpdate,
} from '../api/gym'
import { myselfQuery, type MyRole } from '../api/me'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import { DEFAULT_THEME, THEMES, type Theme } from '../theme'
import { Field, integerOf, LoadFailed, refusal } from './settingsForm'
import { useSubmit } from '../api/submit'

const copy = t.admin.settings.gym

const BANK_FIELDS = ['bank', 'account_type', 'holder', 'rut', 'number', 'email'] as const
type BankField = (typeof BANK_FIELDS)[number]

const PRIVACY_FIELDS = ['legal_name', 'rut', 'email', 'address'] as const
type PrivacyField = (typeof PRIVACY_FIELDS)[number]

type Drafts = {
  name: string
  timezone: string
  theme: Theme
  grace_days: string
  reminder_every_days: string
  whatsapp: boolean
  bank: Record<BankField, string>
  privacy: Record<PrivacyField, string>
}

function draftsOf(settings: Settings): Drafts {
  const account = settings.bank_account
  return {
    name: settings.name,
    timezone: settings.timezone,
    theme: settings.theme,
    grace_days: String(settings.grace_days),
    reminder_every_days: String(settings.reminder_every_days),
    whatsapp: settings.channels.whatsapp,
    bank: {
      bank: account?.bank ?? '',
      account_type: account?.account_type ?? '',
      holder: account?.holder ?? '',
      rut: account ? t.common.rut(account.rut) : '',
      number: account?.number ?? '',
      email: account?.email ?? '',
    },
    privacy: {
      legal_name: settings.privacy?.legal_name ?? '',
      rut: settings.privacy ? t.common.rut(settings.privacy.rut) : '',
      email: settings.privacy?.email ?? '',
      address: settings.privacy?.address ?? '',
    },
  }
}

/** Only what changed, so a setting someone else edited meanwhile is left as they left it. */
function changesOf(before: Drafts, after: Drafts): GymSettingsUpdate {
  const changes: GymSettingsUpdate = {}
  if (after.name !== before.name) changes.name = after.name
  if (after.timezone !== before.timezone) changes.timezone = after.timezone
  if (after.theme !== before.theme) changes.theme = after.theme
  if (after.grace_days !== before.grace_days) changes.grace_days = integerOf(after.grace_days)
  if (after.reminder_every_days !== before.reminder_every_days) {
    changes.reminder_every_days = integerOf(after.reminder_every_days)
  }
  if (after.whatsapp !== before.whatsapp) changes.channels = { whatsapp: after.whatsapp }
  if (BANK_FIELDS.some((f) => after.bank[f] !== before.bank[f])) {
    // The account is replaced whole; every field emptied takes it away.
    const bank = after.bank
    changes.bank_account = BANK_FIELDS.every((f) => bank[f].trim() === '')
      ? null
      : { ...bank, email: bank.email.trim() || null }
  }
  if (PRIVACY_FIELDS.some((f) => after.privacy[f] !== before.privacy[f])) {
    // Replaced whole; a field left empty is the API's to refuse, the address aside.
    const privacy = after.privacy
    changes.privacy = { ...privacy, address: privacy.address.trim() || null }
  }
  return changes
}

/** The zones the browser knows, and the gym's own even if it does not. */
function timezones(current: string): string[] {
  const known = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : []
  return known.includes(current) ? known : [current, ...known]
}

/** "Gimnasio": the gym's profile, how it bills and reminds, and where students transfer to. */
export function GymSettings() {
  const settings = useQuery(gymSettingsQuery())

  if (settings.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (settings.isError) {
    return <LoadFailed error={settings.error} message={copy.error} retry={() => void settings.refetch()} />
  }
  return <GymForm settings={settings.data} />
}

function GymForm({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient()
  const [initial, setInitial] = useState(() => draftsOf(settings))
  const [drafts, setDrafts] = useState(initial)
  const [saved, setSaved] = useState(false)

  const save = useSubmit({
    mutationFn: updateGymSettings,
    onSuccess: (answer) => {
      queryClient.setQueryData(gymSettingsQuery().queryKey, answer)
      // Every screen wears the new theme at once (App's `GymTheme` reads it there).
      queryClient.setQueryData<MyRole>(myselfQuery().queryKey, (me) => me && { ...me, theme: answer.theme })
      const next = draftsOf(answer)
      setInitial(next)
      setDrafts(next)
      setSaved(true)
    },
  })
  const errors = validationErrors(save.error)
  const blank = (value: string) => value.trim() === ''
  const errorOf = (field: string, draft: string) =>
    field in errors ? refusal(errors[field]!, field, copy, blank(draft)) : undefined
  const bankError = (field: BankField) => errorOf(`bank_account.${field}`, drafts.bank[field])
  const setBank = (field: BankField, value: string) => setDrafts({ ...drafts, bank: { ...drafts.bank, [field]: value } })
  const privacyError = (field: PrivacyField) => errorOf(`privacy.${field}`, drafts.privacy[field])
  const setPrivacy = (field: PrivacyField, value: string) =>
    setDrafts({ ...drafts, privacy: { ...drafts.privacy, [field]: value } })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSaved(false)
    const changes = changesOf(initial, drafts)
    if (Object.keys(changes).length === 0) {
      save.reset()
      setSaved(true)
      return
    }
    save.mutate(changes)
  }

  return (
    <form className="settings__form settings__form--panels" aria-label={copy.formLabel} onSubmit={submit} noValidate>
      <fieldset className="settings__card">
        <legend className="settings__legend">{copy.profile}</legend>
        <Field label={copy.name} error={errorOf('name', drafts.name)}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              value={drafts.name}
              onChange={(e) => setDrafts({ ...drafts, name: e.target.value })}
            />
          )}
        </Field>
        <Field label={copy.slug}>
          {(props) => <Input {...props} type="text" value={settings.web_address} readOnly />}
        </Field>
        <Field label={copy.timezone} error={errorOf('timezone', drafts.timezone)}>
          {(props) => (
            <Select
              {...props}
              value={drafts.timezone}
              onChange={(e) => setDrafts({ ...drafts, timezone: e.target.value })}
            >
              {timezones(initial.timezone).map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </fieldset>

      <fieldset className="settings__card">
        <legend className="settings__legend">{copy.theme}</legend>
        <p className="settings__hint">{copy.themeHint}</p>
        <div className="theme-picker">
          {THEMES.map((theme) => (
            <label key={theme} className="theme-picker__option">
              <input
                type="radio"
                name="theme"
                value={theme}
                className="theme-picker__input"
                checked={drafts.theme === theme}
                onChange={() => setDrafts({ ...drafts, theme })}
              />
              <ThemePreview theme={theme} />
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="settings__card">
        <legend className="settings__legend">{copy.billing}</legend>
        <Field label={copy.graceDays} hint={copy.graceDaysHint} error={errorOf('grace_days', drafts.grace_days)}>
          {(props) => (
            <Input
              {...props}
              type="text"
              inputMode="numeric"
              value={drafts.grace_days}
              onChange={(e) => setDrafts({ ...drafts, grace_days: e.target.value })}
            />
          )}
        </Field>
        <Field
          label={copy.reminderEveryDays}
          hint={copy.reminderEveryDaysHint}
          error={errorOf('reminder_every_days', drafts.reminder_every_days)}
        >
          {(props) => (
            <Input
              {...props}
              type="text"
              inputMode="numeric"
              value={drafts.reminder_every_days}
              onChange={(e) => setDrafts({ ...drafts, reminder_every_days: e.target.value })}
            />
          )}
        </Field>
      </fieldset>

      <fieldset className="settings__card">
        <legend className="settings__legend">{copy.channels}</legend>
        <p className="settings__hint">{copy.email}</p>
        <label className="settings__check">
          <input
            type="checkbox"
            checked={drafts.whatsapp}
            onChange={(e) => setDrafts({ ...drafts, whatsapp: e.target.checked })}
          />
          <span>{copy.whatsapp}</span>
        </label>
      </fieldset>

      <fieldset className="settings__card">
        <legend className="settings__legend">{copy.bank}</legend>
        <p className="settings__hint">{copy.bankHint}</p>
        <Field label={copy.bankName} error={bankError('bank')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              value={drafts.bank.bank}
              onChange={(e) => setBank('bank', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.accountType} error={bankError('account_type')}>
          {(props) => (
            <Select
              {...props}
              value={drafts.bank.account_type}
              onChange={(e) => setBank('account_type', e.target.value)}
            >
              <option value="">{copy.choose}</option>
              {ACCOUNT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={copy.holder} error={bankError('holder')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              value={drafts.bank.holder}
              onChange={(e) => setBank('holder', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.rut} error={bankError('rut')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              autoComplete="off"
              value={drafts.bank.rut}
              onChange={(e) => setBank('rut', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.number} error={bankError('number')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              inputMode="numeric"
              autoComplete="off"
              value={drafts.bank.number}
              onChange={(e) => setBank('number', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.bankEmail} error={bankError('email')}>
          {(props) => (
            <Input
              {...props}
              type="email"
              value={drafts.bank.email}
              onChange={(e) => setBank('email', e.target.value)}
            />
          )}
        </Field>
      </fieldset>

      <fieldset className="settings__card" id="privacidad">
        <legend className="settings__legend">{copy.privacy}</legend>
        <p className="settings__hint">{copy.privacyHint}</p>
        <Field label={copy.privacyLegalName} error={privacyError('legal_name')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              autoComplete="organization"
              value={drafts.privacy.legal_name}
              onChange={(e) => setPrivacy('legal_name', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.privacyRut} error={privacyError('rut')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              autoComplete="off"
              value={drafts.privacy.rut}
              onChange={(e) => setPrivacy('rut', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.privacyEmail} error={privacyError('email')}>
          {(props) => (
            <Input
              {...props}
              type="email"
              value={drafts.privacy.email}
              onChange={(e) => setPrivacy('email', e.target.value)}
            />
          )}
        </Field>
        <Field label={copy.privacyAddress} error={privacyError('address')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              autoComplete="street-address"
              value={drafts.privacy.address}
              onChange={(e) => setPrivacy('address', e.target.value)}
            />
          )}
        </Field>
        {settings.privacy && (
          <Link to="/privacidad" target="_blank" className="settings__link">
            {copy.privacyView}
          </Link>
        )}
      </fieldset>

      {save.error && (
        <p className="settings__error" role="alert">
          {Object.keys(errors).length > 0 ? copy.invalid : copy.failed}
        </p>
      )}
      {saved && (
        <p className="settings__done" role="status">
          {copy.saved}
        </p>
      )}
      <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
        {save.isPending ? copy.working : copy.submit}
      </Button>
    </form>
  )
}

/** A theme as it looks: its name, the hero card, a button and the paid and overdue
 * pills, in the theme's own colours whatever the page wears. */
function ThemePreview({ theme }: { theme: Theme }) {
  const sample = copy.themeSample
  return (
    <span className="theme-preview" data-theme={theme}>
      <span className="theme-preview__head">
        <span className="theme-preview__name">{copy.themes[theme]}</span>
        {theme === DEFAULT_THEME && <span className="theme-preview__default">{copy.themeDefault}</span>}
      </span>
      <span className="theme-preview__hero" aria-hidden="true">
        <span className="theme-preview__hero-label">{sample.collected}</span>
        <span className="theme-preview__hero-figure">{sample.figure}</span>
      </span>
      <span className="theme-preview__row" aria-hidden="true">
        <span className="theme-preview__pill theme-preview__pill--paid">{sample.paid}</span>
        <span className="theme-preview__pill theme-preview__pill--overdue">{sample.overdue}</span>
        <span className="theme-preview__button">{sample.action}</span>
      </span>
    </span>
  )
}
