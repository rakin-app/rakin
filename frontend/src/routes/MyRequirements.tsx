import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { myRequirementsQuery, type PersonRequirements } from '../api/requirements'
import { Card, listRowClass, ListRowContent, Section } from '../components/Card'
import { requirementDates, RequirementPill } from '../components/RequirementState'
import { t } from '../i18n/es'

const copy = t.me.requirements

/**
 * "Mis requisitos" (#349): what the gym asks before training, and where the student
 * stands on each, read-only; a guardian's page shows each dependent's. No notes, which
 * are the staff's. Nothing shows when the gym asks for nothing, nor while it loads or
 * fails: the rest of the page does not wait on it.
 */
export function MyRequirements({ mine }: { mine: string }) {
  const people = useQuery(myRequirementsQuery).data ?? []
  return (
    <>
      {people.map((person) => (
        <PersonList key={person.person_id} person={person} mine={person.person_id === mine} />
      ))}
    </>
  )
}

function PersonList({ person, mine }: { person: PersonRequirements; mine: boolean }) {
  const titleId = useId()
  return (
    <Section id={titleId} title={mine ? copy.title : copy.theirs(person.name)}>
      <Card as="ul" flush aria-labelledby={titleId}>
        {person.requirements.map((requirement) => (
          <li key={requirement.id} className={listRowClass()}>
            <ListRowContent
              title={requirement.name}
              detail={requirementDates(requirement, copy) ?? undefined}
              trailing={<RequirementPill state={requirement.state} />}
            />
          </li>
        ))}
      </Card>
    </Section>
  )
}
