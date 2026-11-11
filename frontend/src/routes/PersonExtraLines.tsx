import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { personLinesQuery } from '../api/extraCharges'
import { ListRowContent, listRowClass } from '../components/Card'
import { StatusPill } from '../components/StatusPill'
import { isoDay, shortDay } from '../format'
import { t } from '../i18n/es'
import './ExtraCharges.css'

const copy = t.admin.extra

/**
 * "Cobros extra pendientes" on a member's ficha (#195), beside the plan's money and never
 * part of it: what each still owes, linked to its cobro. Only for who reads the ledger;
 * nothing shows while there is none.
 */
export function PersonExtraLines({ personId }: { personId: string }) {
  const lines = useQuery(personLinesQuery(personId))
  if (!lines.data || lines.data.length === 0) return null
  const today = isoDay(new Date().toISOString())
  return (
    <section className="member__section" aria-labelledby="member-extra">
      <h2 id="member-extra" className="member__section-title">
        {copy.ficha}
      </h2>
      <ul className="extra__list">
        {lines.data.map((line) => {
          const status = line.status === 'in_review' ? 'in_review' : line.due_date < today ? 'overdue' : 'open'
          return (
            <li key={line.id}>
              <Link
                to="/admin/pagos/cobros/$chargeId"
                params={{ chargeId: line.extra_charge_id }}
                className={listRowClass(true)}
              >
                <ListRowContent
                  title={line.title}
                  detail={`${t.common.clp(line.outstanding_clp)} · ${copy.due(shortDay(line.due_date))}`}
                  trailing={<StatusPill status={status}>{copy.status[status]}</StatusPill>}
                />
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
