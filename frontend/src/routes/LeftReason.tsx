import { useId } from 'react'
import { Chip, ChipGroup } from '../components/Chip'
import { Input } from '../components/Field'
import { t } from '../i18n/es'

const copy = t.admin.member.leftReason

// Backend `LeftReason`: no more than a line.
export const MAX_LEFT_REASON = 200

/**
 * "Motivo" (#294): why someone left, optional, for Dar de baja and "Agregar exalumno".
 * The chips fill the text, and pressing the one that is filled empties it. None is about
 * health, and the hint asks for none: a gym may not keep it (#384). Only the owner and
 * admins read the reason.
 */
export function LeftReasonField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const id = useId()
  const hintId = useId()
  return (
    <>
      <label htmlFor={id} className="member__label">
        {copy.label}
      </label>
      <ChipGroup label={copy.chipsLabel}>
        {copy.chips.map((chip) => (
          <Chip key={chip} pressed={value.trim() === chip} onClick={() => onChange(value.trim() === chip ? '' : chip)}>
            {chip}
          </Chip>
        ))}
      </ChipGroup>
      <Input
        id={id}
        autoComplete="off"
        maxLength={MAX_LEFT_REASON}
        value={value}
        aria-describedby={hintId}
        onChange={(e) => onChange(e.target.value)}
      />
      <p id={hintId} className="member__detail">
        {copy.hint}
      </p>
    </>
  )
}
