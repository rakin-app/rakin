import { useState } from 'react'
import { logoImage } from '../logo'
import './GymMark.css'

type Props = {
  name: string
  /** Where the gym's logo is (`logo.ts`); with none, or one that fails to load, its initials. */
  logo?: string | null
  /** 32 px beside a line of text; 56 px over a page's title. */
  size?: 'small' | 'large'
}

const PIXELS = { small: 32, large: 56 } as const

/** The gym's mark: its logo in a circle (#223), or a circle with its initials on the
 * theme's accent, the same size either way so the layout never jumps. Decorative: the
 * gym's name is always written next to it. */
export function GymMark({ name, logo, size = 'small' }: Props) {
  // Remembered per logo, so a new one is tried afresh.
  const [failed, setFailed] = useState<string | null>(null)
  const className = `gym-mark gym-mark--${size}`
  if (logo && failed !== logo) {
    const px = PIXELS[size]
    return (
      <img
        className={className}
        {...logoImage(logo, px)}
        width={px}
        height={px}
        // Decorative: the name beside it says it.
        alt={''}
        onError={() => setFailed(logo)}
      />
    )
  }
  return (
    <span className={className} aria-hidden="true">
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
