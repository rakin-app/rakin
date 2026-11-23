import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, type ReactNode } from 'react'
import { rankLabel } from '../api/grading'
import { MY_DATA_DOWNLOAD, myDataQuery, type MyData as Data, type PersonData } from '../api/myData'
import { Button, buttonClass } from '../components/Button'
import { Card, Section } from '../components/Card'
import { PageContainer } from '../components/Layout'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { isoDay, monthYear } from '../format'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import './MyData.css'

const copy = t.me.myData

/**
 * "Mis datos" (#371): everything the gym holds on the student, and for a guardian on
 * each dependent, as the law's right of access asks: the data, where it came from, how
 * long it is kept, and where the purposes and recipients are (the privacy notice). Each
 * kind of record is a part that opens, with how many it holds; a part with none is not
 * shown. The notes the staff wrote about them are there too; who wrote them is not.
 * "Descargar mis datos" is the same document as a JSON file. Fixing a datum is
 * not done here: the page says to write to the gym's privacy email.
 */
export function MyData() {
  const data = useQuery(myDataQuery())
  useDocumentTitle(copy.title, data.data?.gym.name)

  return (
    <PageContainer>
      <PageHeader eyebrow={data.data?.gym.name} title={copy.title} />
      <div className="my-data">
        <Link to="/me" className="tap-link my-data__back">
          {copy.back}
        </Link>
        {data.isPending ? (
          <Loading className="my-data__note">{copy.loading}</Loading>
        ) : data.isError ? (
          <div className="my-data__note" role="alert">
            <p>{copy.error}</p>
            <Button onClick={() => void data.refetch()}>{copy.retry}</Button>
          </div>
        ) : (
          <Loaded data={data.data} />
        )}
      </div>
    </PageContainer>
  )
}

function Loaded({ data }: { data: Data }) {
  const [mine, ...theirs] = data.people
  const email = data.gym.privacy?.email
  return (
    <>
      <Card className="my-data__about">
        <p>{theirs.length > 0 ? copy.introFamily : copy.intro}</p>
        <a href={MY_DATA_DOWNLOAD} download className={buttonClass({ variant: 'primary' })}>
          {copy.download}
        </a>
        <p className="my-data__hint">{copy.downloadHint}</p>
        <h2 className="my-data__about-title">{copy.sourceTitle}</h2>
        <p>{copy.source}</p>
        <h2 className="my-data__about-title">{copy.retentionTitle}</h2>
        <p>{t.privacy.retention}</p>
        <p>
          {copy.purposeBefore}
          <Link to="/privacidad">{copy.purposeLink}</Link>
          {copy.purposeAfter}
        </p>
        <h2 className="my-data__about-title">{copy.fixTitle}</h2>
        <p>
          {email ? (
            <>
              {copy.fixBefore}
              <a href={`mailto:${email}`}>{email}</a>
              {copy.fixAfter}
            </>
          ) : (
            copy.fixNoEmail
          )}
        </p>
      </Card>
      {mine && <Person person={mine} title={copy.mine} zone={data.gym.timezone} />}
      {theirs.map((person) => (
        <Person key={person.person_id} person={person} title={copy.theirs(person.record.name)} zone={data.gym.timezone} />
      ))}
      <p className="my-data__hint">{copy.onlyFilled}</p>
    </>
  )
}

const day = (iso: string) => t.common.dayYear(iso)

/** A field's value as the ficha writes it. */
function shown(value: unknown): string {
  if (value === null || value === undefined || value === '') return copy.none
  if (typeof value === 'boolean') return value ? copy.yes : copy.no
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

/** A row of a part: what it is, then what else the gym keeps of it. */
type Row = { key: string; title: ReactNode; detail?: (string | null | false | undefined)[] }

function Part({ title, rows }: { title: string; rows: Row[] }) {
  if (rows.length === 0) return null
  return (
    <details className="my-data__part">
      <summary className="my-data__summary">{copy.count(title, rows.length)}</summary>
      <ul className="my-data__rows">
        {rows.map((row) => {
          const detail = (row.detail ?? []).filter(Boolean).join(' · ')
          return (
            <li key={row.key} className="my-data__row">
              <span className="my-data__row-title">{row.title}</span>
              {detail && <span className="my-data__row-detail">{detail}</span>}
            </li>
          )
        })}
      </ul>
    </details>
  )
}

function Person({ person, title, zone }: { person: PersonData; title: string; zone: string }) {
  const titleId = useId()
  const at = (iso: string) => day(isoDay(iso, zone))
  const r = person.record
  const words = copy.record
  const facts: [string, string][] = [
    [words.name, r.name],
    [words.rut, r.rut ? t.common.rut(r.rut) : copy.none],
    [words.email, r.email ?? copy.none],
    [words.phone, r.phone ?? copy.none],
    [words.noWhatsapp, r.no_whatsapp ? copy.yes : copy.no],
    [words.dob, r.dob ? day(r.dob) : copy.none],
  ]
  if (r.member_since) facts.push([words.memberSince, day(r.member_since)])
  if (r.prior_classes !== null) facts.push([words.priorClasses, String(r.prior_classes)])
  if (r.left_on) facts.push([words.leftOn, day(r.left_on)])
  if (r.left_reason) facts.push([words.leftReason, r.left_reason])
  facts.push([words.addedAt, at(r.added_at)], [words.updatedAt, at(r.updated_at)])

  const parts = copy.parts
  const plans = new Map(person.memberships.map((m) => [m.id, m.plan_name]))
  const m = copy.membership
  return (
    <Section id={titleId} title={title} className="my-data__person">
      <Card flush>
        <details className="my-data__part" open>
          <summary className="my-data__summary">{parts.record}</summary>
          <dl className="my-data__facts">
            {facts.map(([label, value]) => (
              <div key={label} className="my-data__fact">
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </details>
        <Part title={parts.guardians} rows={person.guardians.map((g) => ({ key: g.person_id, title: g.name }))} />
        <Part title={parts.dependents} rows={person.dependents.map((d) => ({ key: d.person_id, title: d.name }))} />
        <Part
          title={parts.fields}
          rows={person.fields.map((f) => ({
            key: f.key,
            title: `${f.label}: ${shown(f.value)}`,
            detail: [f.sensitive && copy.field.sensitive, f.archived && copy.field.archived],
          }))}
        />
        <Part
          title={parts.memberships}
          rows={person.memberships.map((ms) => ({
            key: ms.id,
            title: `${ms.plan_name} · ${t.admin.students.status[ms.status]}`,
            detail: [
              copy.span(at(ms.started_at), ms.current_period_end ? day(ms.current_period_end) : null),
              ms.discount_pct !== null && m.discount(ms.discount_pct, ms.discount_reason),
              ms.credits_remaining !== null && m.credits(ms.credits_remaining),
              ms.next_plan_name && m.next(ms.next_plan_name, ms.next_plan_from && day(ms.next_plan_from)),
              ms.cancelled_at && m.cancelled(at(ms.cancelled_at), ms.cancel_reason),
              ms.voided_at && m.voided(at(ms.voided_at), ms.void_reason),
            ],
          }))}
        />
        <Part
          title={parts.planEvents}
          rows={person.plan_events.map((e, i) => ({
            key: `${e.membership_id}-${e.kind}-${e.occurred_on}-${i}`,
            title: `${copy.planEvent[e.kind]} · ${day(e.occurred_on)}`,
            detail: [plans.get(e.membership_id)],
          }))}
        />
        <Part
          title={parts.freezes}
          rows={person.freezes.map((f, i) => ({
            key: `${f.membership_id}-${f.from_date}-${i}`,
            title: copy.span(day(f.from_date), f.to_date && day(f.to_date)),
            detail: [plans.get(f.membership_id), f.reason],
          }))}
        />
        <Part
          title={parts.freezeRequests}
          rows={person.freeze_requests.map((f, i) => ({
            key: `${f.membership_id}-${f.created_at}-${i}`,
            title: `${copy.span(day(f.from_date), f.to_date && day(f.to_date))} · ${copy.freezeRequest[f.status]}`,
            detail: [plans.get(f.membership_id), f.note, f.decision_note],
          }))}
        />
        <Part
          title={parts.periods}
          rows={person.periods.map((p) => ({
            key: p.id,
            title: `${t.common.clp(p.amount_due_clp)} · ${copy.span(day(p.period_start), day(p.period_end))}`,
            detail: [copy.period(p.plan_name, day(p.due_date)), p.discount_pct !== null && m.discount(p.discount_pct, p.discount_reason)],
          }))}
        />
        <Part
          title={parts.extraCharges}
          rows={person.extra_charges.map((x) => ({
            key: x.id,
            title: `${x.title} · ${t.common.clp(x.amount_due_clp)}`,
            detail: [
              x.due_date && copy.extraCharge.due(day(x.due_date)),
              x.cancelled_at && copy.extraCharge.cancelled(at(x.cancelled_at)),
              x.cancel_reason,
            ],
          }))}
        />
        <Part
          title={parts.entries}
          rows={person.entries.map((e) => ({
            key: e.id,
            title: `${copy.entry.kind[e.kind]} · ${t.common.clp(e.amount_clp)} · ${copy.entry.status[e.status]}`,
            detail: [at(e.created_at), e.method && copy.method[e.method], e.has_proof && copy.entry.proof, e.note],
          }))}
        />
        <Part
          title={parts.historyPayments}
          rows={person.history_payments.map((h) => ({
            key: h.id,
            title: `${t.common.clp(h.amount_clp)} · ${day(h.paid_on)}`,
            detail: [
              h.plan_name,
              h.covers_month && copy.history.covers(monthYear(h.covers_month)),
              h.method && copy.method[h.method],
              h.note,
            ],
          }))}
        />
        <Part
          title={parts.attendance}
          rows={person.attendance.map((v) => ({
            key: v.session_id,
            title: at(v.starts_at),
            detail: [copy.visit(v.class_type_name, v.program_name)],
          }))}
        />
        <Part
          title={parts.grades}
          rows={person.grades.map((g) => ({ key: g.id, title: rankLabel(g), detail: [day(g.awarded_on), g.note] }))}
        />
        <Part
          title={parts.requirements}
          rows={person.requirements.map((q) => ({ key: q.id, title: q.requirement_name, detail: [day(q.done_on), q.note] }))}
        />
        <Part
          title={parts.consents}
          rows={person.consents.map((c) => ({
            key: c.id,
            title: copy.consent[c.action],
            detail: [at(c.at), copy.consent.source[c.source], c.by_name && copy.consent.by(c.by_name)],
          }))}
        />
        <Part
          title={parts.messages}
          rows={person.messages.map((msg) => ({
            key: msg.id,
            title: `${copy.message.channel[msg.channel]} · ${at(msg.sent_at)}`,
            detail: [copy.message.to(msg.to_address), copy.message.status[msg.status]],
          }))}
        />
        <Part title={parts.groups} rows={person.charge_groups.map((g) => ({ key: g, title: g }))} />
        <Part
          title={parts.email}
          rows={person.unsubscribed_at ? [{ key: 'unsubscribed', title: copy.unsubscribed, detail: [at(person.unsubscribed_at)] }] : []}
        />
        <Part
          title={parts.staff}
          rows={
            person.staff
              ? [
                  {
                    key: 'staff',
                    title: person.staff.account_holder ? copy.staff.holder : copy.staff.role,
                    detail: [at(person.staff.added_at)],
                  },
                  ...person.staff.titles.map((s, i) => ({
                    key: `${s.title_name}-${s.starts_on}-${i}`,
                    title: s.title_name,
                    detail: [copy.span(day(s.starts_on), s.ends_on && day(s.ends_on))],
                  })),
                ]
              : []
          }
        />
      </Card>
    </Section>
  )
}
