import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { myMaterialQuery, type MyMaterial as Material } from '../api/studyMaterial'
import { Button } from '../components/Button'
import { Card, Section } from '../components/Card'
import { MaterialContent } from '../components/StudyMaterial'
import { t } from '../i18n/es'
import '../components/StudyMaterial.css'

const copy = t.me.material

// How many the list shows before "Ver N más".
const FIRST = 5

/**
 * "Material de estudio" on the student page (#537): what the gym's coaches shared with
 * the student or a dependent, newest first, each with its class, its day and who shared
 * it; tapping one opens its text and links. The database decides what reaches them. A
 * page with none shows no section: most gyms may never share any.
 */
export function MyMaterial() {
  const list = useQuery(myMaterialQuery())
  const titleId = useId()
  const [all, setAll] = useState(false)
  // Said politely: the payment and its upload are what the page is for.
  if (list.isError) return <p className="me-home__note">{copy.error}</p>
  if (!list.data || list.data.length === 0) return null
  const shown = all ? list.data : list.data.slice(0, FIRST)
  return (
    <Section id={titleId} title={copy.title}>
      <Card as="ul" flush className="my-material">
        {shown.map((material) => (
          <MaterialItem key={material.id} material={material} />
        ))}
      </Card>
      {!all && list.data.length > FIRST && (
        <Button variant="ghost" onClick={() => setAll(true)}>
          {copy.more(list.data.length - FIRST)}
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
