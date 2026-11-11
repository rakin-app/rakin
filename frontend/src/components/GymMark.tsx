import './GymMark.css'

type Props = {
  name: string
}

/** The gym's mark beside its name: a circle with its initials, where its logo goes once
 * a gym can upload one (#223). Decorative: the name is always written next to it. */
export function GymMark({ name }: Props) {
  return (
    <span className="gym-mark" aria-hidden="true">
      {initials(name)}
    </span>
  )
}

/** "Academia Sur" → "AS"; one word gives its first letter. */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((word) => /\p{L}|\p{N}/u.test(word))
    .slice(0, 2)
    .map((word) => [...word.replace(/^[^\p{L}\p{N}]+/u, '')][0]!.toLocaleUpperCase('es'))
    .join('')
}
