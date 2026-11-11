import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { GymMark, initials } from './GymMark'

describe('initials', () => {
  it.each([
    ['Academia Sur', 'AS'],
    ['Meta', 'M'],
    ['  Ñandú   jiu jitsu club ', 'ÑJ'],
    ['"Gracie" Barra', 'GB'],
    ['10th Planet', '1P'],
  ])('reads %j as %s', (name, expected) => {
    expect(initials(name)).toBe(expected)
  })
})

describe('GymMark', () => {
  const LOGO = '/api/logos/gym/0123456789abcdef'

  it('shows the logo, decorative, in files sized for the screen (#223)', () => {
    const { container } = render(<GymMark name="Academia Sur" logo={LOGO} size="large" />)
    const image = container.querySelector('img')!
    expect(image.className).toBe('gym-mark gym-mark--large')
    expect(image.getAttribute('alt')).toBe('')
    expect(image.getAttribute('src')).toBe(`${LOGO}/128.webp`)
    expect(image.getAttribute('sizes')).toBe('56px')
    expect(image.getAttribute('srcset')).toBe(`${LOGO}/64.webp 64w, ${LOGO}/128.webp 128w, ${LOGO}/512.webp 512w`)
    expect([image.getAttribute('width'), image.getAttribute('height')]).toEqual(['56', '56'])
  })

  it('falls back to the initials with no logo, or one that does not load', () => {
    const { container, rerender } = render(<GymMark name="Academia Sur" />)
    expect(container.textContent).toBe('AS')

    rerender(<GymMark name="Academia Sur" logo={LOGO} />)
    fireEvent.error(container.querySelector('img')!)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toBe('AS')

    // A new logo is tried afresh.
    rerender(<GymMark name="Academia Sur" logo={`${LOGO}0`} />)
    expect(container.querySelector('img')).not.toBeNull()
  })
})
