import type { FieldValue, PersonField } from '../api/customFields'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'

const copy = t.admin.member.fields

/** What a field's input sends: `null` for nothing typed, a number for a number field. */
export function valueOf(field: Pick<PersonField, 'type'>, draft: string): FieldValue {
  const text = draft.trim()
  if (!text) return null
  if (field.type !== 'number') return text
  // Not a number: sent as typed, for the API to refuse rather than to clear.
  const number = Number(text.replace(',', '.'))
  return Number.isNaN(number) ? text : number
}

/** One custom field's input, by its type: a choice of its options, a number, a date or text. */
export function FieldInput({
  id,
  field,
  value,
  invalid,
  onChange,
}: {
  id: string
  field: Pick<PersonField, 'type' | 'options'>
  value: string
  invalid: boolean
  onChange: (value: string) => void
}) {
  const props = {
    id,
    value,
    'aria-invalid': invalid,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
  }
  if (field.type === 'enum') {
    return (
      <Select {...props}>
        <option value="">{copy.choose}</option>
        {(field.options ?? []).map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </Select>
    )
  }
  if (field.type === 'number') return <Input {...props} type="text" inputMode="decimal" />
  if (field.type === 'date') return <Input {...props} type="date" />
  return <Input {...props} type="text" maxLength={1000} />
}
