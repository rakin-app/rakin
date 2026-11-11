import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RakinLogo } from './RakinLogo'

describe('RakinLogo', () => {
  it('is the symbol and the wordmark, hidden from screen readers', () => {
    const { container } = render(<RakinLogo />)
    const logo = container.firstElementChild!

    expect(logo).toHaveAttribute('aria-hidden', 'true')
    expect(logo.querySelector('svg')).not.toBeNull()
    expect(logo).toHaveTextContent(/^rakin$/)
  })

  it('rings the tile on either surface, and lightens the wordmark on a dark one', () => {
    const light = render(<RakinLogo />).container
    const dark = render(<RakinLogo surface="dark" />).container

    expect(light.querySelector('.rakin-logo__ring')).not.toBeNull()
    expect(dark.querySelector('.rakin-logo__ring')).not.toBeNull()
    expect(dark.firstElementChild).toHaveClass('rakin-logo--dark')
  })

  it('can be the symbol alone', () => {
    const { container } = render(<RakinLogo symbolOnly />)

    expect(container.querySelector('svg')).not.toBeNull()
    expect(container).toHaveTextContent('')
  })
})
