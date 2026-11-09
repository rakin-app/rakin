import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { myRoleQuery, readsLedger } from '../api/me'
import { pendingCountQuery } from '../api/proofs'
import { PlaceholderPage } from '../components/PlaceholderPage'
import { t } from '../i18n/es'
import './Payments.css'

/** "Libro de pagos". The ledger itself lands with #39; for now it leads to the proofs
 *  waiting for review. */
export function Payments() {
  const role = useQuery(myRoleQuery())
  const pending = useQuery({ ...pendingCountQuery(), enabled: readsLedger(role.data) })
  const count = pending.data ?? 0

  return (
    <>
      <PlaceholderPage title={t.admin.payments.title} />
      {count > 0 && (
        <p className="payments__review">
          <Link to="/admin/pagos/comprobantes" className="payments__review-link">
            {t.admin.payments.review(count)}
          </Link>
        </p>
      )}
    </>
  )
}
