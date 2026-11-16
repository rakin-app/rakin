import { Link } from '@tanstack/react-router'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { cardClass } from '../components/Card'
import '../components/PlaceholderPage.css'

/** A path no route has, on its own page. */
export function NotFound() {
  return (
    <main>
      <NotFoundBody />
    </main>
  )
}

/** The same, inside a shell that is the page's `main` already: /admin's keeps its nav and mark (#362). */
export function NotFoundBody() {
  return (
    <>
      <PageHeader title={t.notFound.title} />
      <div className="placeholder-page">
        <p className={cardClass({}, 'placeholder-page__body')}>
          {t.notFound.body} <Link to="/admin">{t.notFound.backToAdmin}</Link>
        </p>
      </div>
    </>
  )
}
