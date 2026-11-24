import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react'
import { useSubmit } from '../api/submit'
import {
  acceptTerms,
  conflictCode,
  contactLine,
  termsPageQuery,
  type BreachContact,
  type TermsDocument,
  type TermsFilled,
  type TermsKey,
  type TermsPage,
} from '../api/terms'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Banner, cardClass, CheckRow, Section, SectionTitle } from '../components/Card'
import { Disclosure } from '../components/Disclosure'
import { Field, FieldError, Input } from '../components/Field'
import { PageContainer } from '../components/Layout'
import { useFocusFirstInvalid, useRefusal } from '../components/focusInvalid'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { formatRut } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { LoadFailed } from './settingsForm'
import './TermsAcceptance.css'

const copy = t.terms

const EMPTY_CONTACT: BreachContact = { name_and_role: '', email: '', phone: '' }

type Drafts = {
  legal_name: string
  rut: string
  address: string
  representative: string
  contacts: BreachContact[]
}

/** The form as the page opens it: the latest acceptance's values, or the titular's name. */
function draftsOf(prefill: Partial<TermsFilled>): Drafts {
  const contacts = prefill.breach_contacts?.length ? prefill.breach_contacts : [EMPTY_CONTACT]
  return {
    legal_name: prefill.legal_name ?? '',
    rut: prefill.rut ?? '',
    address: prefill.address ?? '',
    representative: prefill.representative ?? '',
    contacts: contacts.map((c) => ({ ...c })),
  }
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/** `rut` as the backend stores it, `7654321-6`, or `null` when it is no RUT. */
function rutOf(rut: string): { body: string; digit: string } | null {
  const match = /^(\d{1,8})-?([\dkK])$/.exec(rut.replace(/[.\s]/g, ''))
  return match ? { body: match[1]!, digit: match[2]!.toUpperCase() } : null
}

/** Whether `rut` has the check digit its body asks for (backend `app.domain.rut`). */
export function validRut(rut: string): boolean {
  const parts = rutOf(rut)
  if (!parts) return false
  const { body, digit } = parts
  let sum = 0
  let factor = 2
  for (const d of [...body].reverse()) {
    sum += Number(d) * factor
    factor = factor === 7 ? 2 : factor + 1
  }
  const expected = 11 - (sum % 11)
  const check = expected === 11 ? '0' : expected === 10 ? 'K' : String(expected)
  return check === digit
}

/** What the form still lacks, by field, as the server would refuse it. */
function problemsOf(drafts: Drafts): Record<string, string> {
  const problems: Record<string, string> = {}
  for (const field of ['legal_name', 'address', 'representative'] as const) {
    if (drafts[field].trim() === '') problems[field] = copy.required
  }
  if (drafts.rut.trim() === '') problems.rut = copy.required
  else if (!validRut(drafts.rut)) problems.rut = copy.refusals.rut
  drafts.contacts.forEach((contact, n) => {
    if (contact.name_and_role.trim() === '') problems[`${n}.name_and_role`] = copy.required
    if (contact.email.trim() === '') problems[`${n}.email`] = copy.required
    else if (!EMAIL.test(contact.email.trim())) problems[`${n}.email`] = copy.refusals.email
    if (contact.phone.trim() === '') problems[`${n}.phone`] = copy.required
  })
  const [first, second] = drafts.contacts
  if (second && first && second.email.trim() !== '' && second.email.trim().toLowerCase() === first.email.trim().toLowerCase()) {
    problems['1.email'] = copy.refusals.same_contact_email
  }
  return problems
}

function filledOf(drafts: Drafts): TermsFilled {
  return {
    legal_name: drafts.legal_name.trim(),
    rut: drafts.rut.trim(),
    address: drafts.address.trim(),
    representative: drafts.representative.trim(),
    breach_contacts: drafts.contacts.map((c) => ({
      name_and_role: c.name_and_role.trim(),
      email: c.email.trim(),
      phone: c.phone.trim(),
    })),
  }
}

/** Each blank's text as the titular has filled it so far, or `null` while empty, by
 * field, as the server fills them on acceptance (`TermsFilled.values`). */
function blanksOf(drafts: Drafts): Record<string, string | null> {
  const typed = (value: string) => value.trim() || null
  const [first, second] = drafts.contacts
  return {
    legal_name: typed(drafts.legal_name),
    rut: validRut(drafts.rut) ? formatRut(`${rutOf(drafts.rut)!.body}-${rutOf(drafts.rut)!.digit}`) : typed(drafts.rut),
    address: typed(drafts.address),
    representative: typed(drafts.representative),
    contact_name: typed(first?.name_and_role ?? ''),
    contact_email: typed(first?.email ?? ''),
    contact_phone: typed(first?.phone ?? ''),
    second_contact: second ? (second.name_and_role.trim() ? contactLine(second) : null) : contactLine(undefined),
  }
}

/**
 * The page the titular sees before anything else, on every admin path, while the gym
 * has not accepted the current terms (#499): both texts in full, which they can download
 * or print before accepting (#500, requirement 11); the gym's details the texts ask
 * for; one unticked box per text, in the gym's name; and "Aceptar y empezar". For a gym
 * that accepted an earlier version, what changed comes first. Once accepted, the admin
 * opens on Hoy.
 */
export function TermsAcceptance() {
  usePageTitle(copy.tab)
  const page = useQuery(termsPageQuery())
  return (
    <PageContainer className="terms">
      <PageHeader title={copy.title} />
      {page.isPending ? (
        <Loading className="terms__note" role="status">
          {copy.loading}
        </Loading>
      ) : page.isError ? (
        <LoadFailed error={page.error} message={copy.failed} retry={() => void page.refetch()} />
      ) : (
        <AcceptanceForm page={page.data} />
      )}
    </PageContainer>
  )
}

function AcceptanceForm({ page }: { page: TermsPage }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [drafts, setDrafts] = useState(() => draftsOf(page.prefill))
  const [checked, setChecked] = useState<Record<TermsKey, boolean>>({ service: false, processor: false })
  const [changed, setChanged] = useState(false)
  const [tried, setTried] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const changesId = useId()
  const textsId = useId()
  const boxesError = useId()
  const blanks = blanksOf(drafts)

  const accept = useSubmit({
    offline: 'refuse',
    mutationFn: acceptTerms,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['me', 'role'] })
      void queryClient.invalidateQueries({ queryKey: ['terms'] })
      void navigate({ to: '/admin', replace: true })
    },
    onError: (error) => {
      if (conflictCode(error) === 'terms_changed') {
        setChanged(true)
        setChecked({ service: false, processor: false })
        void queryClient.invalidateQueries({ queryKey: termsPageQuery().queryKey })
      }
    },
  })
  useFocusFirstInvalid(formRef, accept.error)
  // Its own check too (#569): a blank field focused, not "Aceptar y empezar" at the foot.
  const refuse = useRefusal(formRef)

  const problems = problemsOf(drafts)
  const valid = Object.keys(problems).length === 0
  const both = checked.service && checked.processor
  const firstUnticked = !checked.service ? 'service' : !checked.processor ? 'processor' : null
  const apiErrors = validationErrors(accept.error)
  const errorOf = (key: string) => (tried ? problems[key] : undefined) ?? apiRefusal(apiErrors, key)

  const set = (field: Exclude<keyof Drafts, 'contacts'>, value: string) => setDrafts({ ...drafts, [field]: value })
  const setContact = (n: number, field: keyof BreachContact, value: string) =>
    setDrafts({ ...drafts, contacts: drafts.contacts.map((c, i) => (i === n ? { ...c, [field]: value } : c)) })

  const service = page.documents.find((d) => d.key === 'service')!
  const processor = page.documents.find((d) => d.key === 'processor')!
  const declaration = (key: TermsKey) => declarationOf(page.declarations[key], blanks.legal_name ?? null)
  const withChanges = page.documents.filter((d) => d.changes.length > 0)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setTried(true)
    if (!valid || !both) return refuse()
    setChanged(false)
    accept.mutate({
      service_version: service.version,
      processor_version: processor.version,
      filled: filledOf(drafts),
      accept_service: true,
      accept_processor: true,
    })
  }

  return (
    <form ref={formRef} className="terms__form" aria-label={copy.title} onSubmit={submit} noValidate>
      <p className="terms__lead">{page.state === 'outdated' ? copy.leadOutdated(page.gym_name) : copy.lead()}</p>
      {changed && <Banner tone="error">{copy.changed}</Banner>}

      {page.state === 'outdated' && withChanges.length > 0 && (
        <Section id={changesId} title={copy.changes}>
          <div className={cardClass({}, 'terms__card')}>
            {withChanges.map((document) =>
              document.changes.map((change) => (
                <div key={`${document.key}-${change.version}`} className="terms__change">
                  <h3 className="terms__change-title">{copy.changesOf(document.title, change.version)}</h3>
                  {/* Built by the server from docs/legal/, every value escaped (`app.legal.terms`). */}
                  <div className="legal" dangerouslySetInnerHTML={{ __html: demoted(change.html, 3) }} />
                </div>
              )),
            )}
          </div>
        </Section>
      )}

      <Section
        id={textsId}
        title={copy.texts}
        trailing={
          <Button onClick={() => openPrintable(page, blanks)} className="terms__print">
            {copy.print}
          </Button>
        }
      >
        {page.documents.map((document) => (
          <LegalText key={document.key} document={document} blanks={blanks} />
        ))}
      </Section>

      <fieldset className={cardClass({}, 'terms__card terms__fields')}>
        <SectionTitle as="legend" className="terms__legend">
          {copy.form()}
        </SectionTitle>
        <p className="terms__note">{copy.formHint}</p>
        <Field label={copy.legalName} hint={copy.legalNameHint} error={errorOf('legal_name')}>
          {(props) => (
            <Input {...props} type="text" maxLength={300} value={drafts.legal_name} onChange={(e) => set('legal_name', e.target.value)} />
          )}
        </Field>
        <Field label={copy.rut} hint={copy.rutHint()} error={errorOf('rut')}>
          {(props) => (
            <Input {...props} type="text" autoComplete="off" value={drafts.rut} onChange={(e) => set('rut', e.target.value)} />
          )}
        </Field>
        <Field label={copy.address} error={errorOf('address')}>
          {(props) => (
            <Input {...props} type="text" maxLength={300} value={drafts.address} onChange={(e) => set('address', e.target.value)} />
          )}
        </Field>
        <Field label={copy.representative} hint={copy.representativeHint()} error={errorOf('representative')}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              value={drafts.representative}
              onChange={(e) => set('representative', e.target.value)}
            />
          )}
        </Field>
        {drafts.contacts.map((contact, n) => (
          <fieldset key={n} className="terms__contact">
            <legend className="terms__contact-title">{n === 0 ? copy.contact : copy.otherContact}</legend>
            {n === 0 && <p className="terms__note">{copy.contactHint()}</p>}
            <Field label={copy.contactName} error={errorOf(`${n}.name_and_role`)}>
              {(props) => (
                <Input
                  {...props}
                  type="text"
                  maxLength={300}
                  value={contact.name_and_role}
                  onChange={(e) => setContact(n, 'name_and_role', e.target.value)}
                />
              )}
            </Field>
            <Field label={copy.contactEmail} error={errorOf(`${n}.email`)}>
              {(props) => (
                <Input {...props} type="email" value={contact.email} onChange={(e) => setContact(n, 'email', e.target.value)} />
              )}
            </Field>
            <Field label={copy.contactPhone} error={errorOf(`${n}.phone`)}>
              {(props) => (
                <Input {...props} type="tel" value={contact.phone} onChange={(e) => setContact(n, 'phone', e.target.value)} />
              )}
            </Field>
            {n === 1 && (
              <Button onClick={() => setDrafts({ ...drafts, contacts: drafts.contacts.slice(0, 1) })}>{copy.removeOther}</Button>
            )}
          </fieldset>
        ))}
        {drafts.contacts.length === 1 && (
          <Button onClick={() => setDrafts({ ...drafts, contacts: [...drafts.contacts, { ...EMPTY_CONTACT }] })}>
            {copy.addOther}
          </Button>
        )}
      </fieldset>

      <div className={cardClass({}, 'terms__card terms__checks')}>
        {(['service', 'processor'] as const).map((key) => (
          <CheckRow key={key} start>
            <input
              type="checkbox"
              checked={checked[key]}
              // Refused for a box left unticked, the first of them is focused and says so (#569).
              aria-invalid={tried && key === firstUnticked}
              aria-describedby={tried && key === firstUnticked ? boxesError : undefined}
              onChange={(e) => setChecked({ ...checked, [key]: e.target.checked })}
            />
            <span>{declaration(key)}</span>
          </CheckRow>
        ))}
        {tried && !both && <FieldError id={boxesError}>{copy.needsBoth}</FieldError>}
      </div>

      {accept.isError && !changed && (
        <Banner tone="error">{Object.keys(apiErrors).length > 0 ? copy.invalid : copy.acceptFailed}</Banner>
      )}
      {tried && !valid && <Banner tone="error">{copy.invalid}</Banner>}
      <div className="terms__actions">
        {!both && !tried && <p className="terms__note">{copy.needsBoth}</p>}
        <Button type="submit" variant="primary" disabled={!both || accept.isPending} busy={accept.isPending}>
          {accept.isPending ? copy.accepting : copy.accept}
        </Button>
      </div>
    </form>
  )
}

/** The API's refusal of `key` (`rut`, `0.email`), from its path under `filled`. */
function apiRefusal(errors: Record<string, string>, key: string): string | undefined {
  const path = key.includes('.') ? `filled.breach_contacts.${key}` : `filled.${key}`
  const code = errors[path] ?? (key === '1.email' ? errors['filled'] : undefined)
  if (code === undefined) return undefined
  if (code === 'missing' || code === 'string_too_short') return copy.required
  const field = key.split('.').pop()!
  return (copy.refusals as Record<string, string>)[code] ?? (copy.refusals as Record<string, string>)[field] ?? copy.invalid
}

/** One text, collapsed under its title, its blanks showing what the titular types. */
function LegalText({ document, blanks }: { document: TermsDocument; blanks: Record<string, string | null> }) {
  const body = useRef<HTMLDivElement>(null)
  // Under the page's h1 and the section's h2, the text's own h1 is an h3 (#570).
  const html = useMemo(() => demoted(document.html, 2), [document.html])
  useEffect(() => {
    fillBlanks(body.current, blanks)
  })
  return (
    <Disclosure className="terms__text" title={document.title} meta={copy.version(document.version)} cue={copy.read}>
      {/* Built by the server from docs/legal/, every value escaped (`app.legal.terms`). */}
      <div ref={body} className="legal" dangerouslySetInnerHTML={{ __html: html }} />
    </Disclosure>
  )
}

/**
 * What a box says, in the gym's name as the titular types it, or "la academia" until
 * they do (#570): never the blank's label in brackets, which reads as a template's.
 */
export function declarationOf(declaration: string, legalName: string | null): string {
  return declaration.replace('{legal_name}', legalName ?? copy.thePlace())
}

/** `html` with each heading `by` levels down, to h6 at most: the server's text, whose
 * every value is escaped, so a `<h1` in it is only ever a tag. */
export function demoted(html: string, by: number): string {
  return html.replace(/<(\/?)h([1-6])\b/g, (_, slash: string, level: string) => `<${slash}h${Math.min(6, Number(level) + by)}`)
}

/** Each blank under `root` shows its field's value, as text, or its label while empty:
 * what the server renders and keeps on acceptance. */
function fillBlanks(root: ParentNode | null, blanks: Record<string, string | null>): void {
  root?.querySelectorAll<HTMLElement>('[data-blank]').forEach((span) => {
    const field = span.dataset.blank!
    if (!(field in blanks)) return
    span.dataset.label ??= span.textContent ?? ''
    span.textContent = blanks[field] ?? span.dataset.label
  })
}

/** Both texts, as they stand, in a page of their own to save or print before accepting. */
function openPrintable(page: TermsPage, blanks: Record<string, string | null>): void {
  const holder = document.createElement('div')
  holder.innerHTML = page.documents.map((d) => d.html).join('<hr>')
  fillBlanks(holder, blanks)
  const title = document.createElement('title')
  title.textContent = copy.printTitle(page.gym_name)
  const html =
    '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' +
    title.outerHTML +
    '<style>body{font:16px/1.6 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#18181b}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d4d4d8;padding:.4rem;text-align:left;vertical-align:top}</style></head><body>' +
    holder.innerHTML +
    '</body></html>'
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  window.open(url, '_blank', 'noopener')
}
