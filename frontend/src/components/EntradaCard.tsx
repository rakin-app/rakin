import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { doorsQuery } from '../api/checkIn'
import { buttonClass } from './Button'
import { Card, SectionTitle } from './Card'
import { t } from '../i18n/es'
import './EntradaCard.css'

const copy = t.admin.checkIn.card

/**
 * "Entrada" on Clases and Hoy (#348): for a gym with open access, how many came in today
 * and a tap to the door. Nothing at all for a gym without, or while it is not known.
 */
export function EntradaCard() {
  const doors = useQuery(doorsQuery())
  if (!doors.data || doors.data.length === 0) return null
  const arrivals = doors.data.reduce((n, door) => n + door.arrivals.length, 0)
  return (
    <Card className="entrada-card" aria-labelledby="entrada-title">
      <div className="entrada-card__text">
        <SectionTitle id="entrada-title">{copy.title}</SectionTitle>
        <span className="entrada-card__detail">{copy.detail(arrivals)}</span>
      </div>
      <Link to="/admin/entrada" className={buttonClass({ variant: 'primary' })}>
        {copy.open}
      </Link>
    </Card>
  )
}

/** Whether the gym has open access: an Entrada to show. False until known. */
export function useHasEntrada(): boolean {
  const doors = useQuery(doorsQuery())
  return (doors.data?.length ?? 0) > 0
}
