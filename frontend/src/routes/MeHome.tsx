import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { ProofUpload } from './ProofUpload'

/** The student page. For now it holds the proof upload; the rest comes with #65. */
export function MeHome() {
  return (
    <>
      <PageHeader title={t.me.home.title} />
      <ProofUpload />
    </>
  )
}
