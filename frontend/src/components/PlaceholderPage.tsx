import { t } from '../i18n/es'
import { PageHeader } from './PageHeader'
import { cardClass } from './Card'
import './PlaceholderPage.css'

// Stand-in body for screens whose features land in later issues.
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <div className="placeholder-page">
        <p className={cardClass({}, 'placeholder-page__body')}>{t.common.comingSoon}</p>
      </div>
    </>
  )
}
