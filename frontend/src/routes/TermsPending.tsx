import { PageHeader } from '../components/PageHeader'
import { cardClass } from '../components/Card'
import { PageContainer } from '../components/Layout'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import '../components/PlaceholderPage.css'

/**
 * What the team sees in place of the admin while the gym has never accepted its terms
 * (#499): who has to accept them, and nothing else, as a suspended gym shows its
 * notice (`Suspended`). Its API takes no data meanwhile, from anyone.
 */
export function TermsPending({ gym, titular }: { gym: string; titular: string | null }) {
  usePageTitle(t.terms.tab)
  return (
    <PageContainer>
      <PageHeader title={t.terms.pendingTitle(gym)} />
      <div className="placeholder-page">
        <p className={cardClass({}, 'placeholder-page__body')}>{t.terms.pending(titular)}</p>
      </div>
    </PageContainer>
  )
}
