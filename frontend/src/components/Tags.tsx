import type { TagOn } from '../api/classTags'
import { t } from '../i18n/es'
import { Chip } from './Chip'
import './Tags.css'

const copy = t.tagHours

/**
 * The gym's tags as chips to press (#243): a class's or a slot's, beside its topic.
 * They wrap rather than scroll, so every tag the gym has is in view. An archived one
 * shows only while it is still on, and says so.
 */
export function TagPicker({
  label,
  tags,
  selected,
  onChange,
  disabled = false,
}: {
  label: string
  tags: readonly TagOn[]
  selected: readonly string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}) {
  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((each) => each !== id) : [...selected, id])
  return (
    <div role="group" aria-label={label} className="tag-picker">
      {tags.map((tag) => (
        <Chip key={tag.id} pressed={selected.includes(tag.id)} disabled={disabled} onClick={() => toggle(tag.id)}>
          {tag.archived ? `${tag.name} (${copy.archived})` : tag.name}
        </Chip>
      ))}
    </div>
  )
}

/** A class's tags, read only: small pills, in a list. */
export function TagList({ tags, label }: { tags: readonly TagOn[]; label: string }) {
  if (tags.length === 0) return null
  return (
    <ul className="tag-list" aria-label={label}>
      {tags.map((tag) => (
        <li key={tag.id} className="tag-list__tag">
          {tag.name}
        </li>
      ))}
    </ul>
  )
}
