import { PageHeader } from '../components/PageHeader'
import { cardClass } from '../components/Card'
import { t } from '../i18n/es'
import { useDocumentTitle } from '../pageTitle'
import '../components/PlaceholderPage.css'

/**
 * What a suspended gym's address shows on every path (#439), in place of the app: its
 * name and a short notice, and nothing else. Nobody signs in there while it lasts.
 */
export function Suspended({ name }: { name: string }) {
  useDocumentTitle(t.suspended.tab, name)
  return (
    <main>
      <PageHeader title={name} />
      <div className="placeholder-page">
        <p className={cardClass({}, 'placeholder-page__body')}>{t.suspended.notice}</p>
      </div>
    </main>
  )
}
