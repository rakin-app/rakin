import { Link } from '@tanstack/react-router'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import '../components/PlaceholderPage.css'

export function NotFound() {
  return (
    <main>
      <PageHeader title={t.notFound.title} />
      <div className="placeholder-page">
        <p className="placeholder-page__body">
          {t.notFound.body} <Link to="/admin">{t.notFound.backToAdmin}</Link>
        </p>
      </div>
    </main>
  )
}
