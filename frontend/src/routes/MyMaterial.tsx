import { useInfiniteQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { myMaterialQuery, type MyMaterial as Material } from '../api/studyMaterial'
import { Button } from '../components/Button'
import { Card, Section } from '../components/Card'
import { MaterialContent } from '../components/StudyMaterial'
import { t } from '../i18n/es'
import '../components/StudyMaterial.css'

const copy = t.me.material

/**
 * "Material de estudio" on the student page (#537): what the gym's coaches shared with
 * the student or a dependent, newest first: the recent few, then "Ver material anterior"
 * for older material a page at a time (#548), each with the class it reached them through,
 * its day, whom it is for when only a dependent (a guardian's "Para León"), and who
 * shared it; tapping one opens its text and links. The database decides what reaches them. A
 * page with none shows no section: most gyms may never share any.
 */
export function MyMaterial() {
  const list = useInfiniteQuery(myMaterialQuery())
  const titleId = useId()
  // Said politely: the payment and its upload are what the page is for. An older page
  // that fails keeps what is shown and says so under it.
  if (list.isError && !list.data) return <p className="me-home__note">{copy.error}</p>
  const shown = list.data?.pages.flatMap((page) => page.items) ?? []
  if (shown.length === 0) return null
  return (
    <Section id={titleId} title={copy.title}>
      <Card as="ul" flush className="my-material">
        {shown.map((material) => (
          <MaterialItem key={material.id} material={material} />
        ))}
      </Card>
      {list.isFetchNextPageError && <p className="me-home__note">{copy.error}</p>}
      {list.hasNextPage && (
        <Button variant="ghost" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
          {copy.older}
        </Button>
      )}
    </Section>
  )
}

function MaterialItem({ material }: { material: Material }) {
  const [open, setOpen] = useState(false)
  const contentId = useId()
  const day = t.common.shortDay(material.day)
  return (
    <li className="history__row my-material__row">
      <button
        type="button"
        className="my-material__toggle"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((was) => !was)}
      >
        <span className="history__what">
          <span className="history__month">{material.title}</span>
          <span className="history__detail">
            {material.recurring
              ? copy.since(material.class_type_name, day)
              : copy.when(material.class_type_name, day)}
          </span>
          {material.for_names.length > 0 && (
            <span className="history__detail">{copy.forWhom(material.for_names)}</span>
          )}
          {material.shared_by_name && (
            <span className="history__detail">{copy.sharedBy(material.shared_by_name)}</span>
          )}
        </span>
      </button>
      <div id={contentId} className="my-material__content" hidden={!open}>
        <MaterialContent body={material.body} links={material.links} />
      </div>
    </li>
  )
}
