import { onlineManager } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { es } from '../i18n/es'
import { Loading } from './Loading'

afterEach(() => {
  onlineManager.setOnline(true)
})

describe('Loading', () => {
  it('says it is loading while online, and that there is no signal once it goes (#362)', () => {
    render(<Loading role="status">Cargando los pagos…</Loading>)
    expect(screen.getByRole('status')).toHaveTextContent('Cargando los pagos…')

    act(() => onlineManager.setOnline(false))
    expect(screen.getByRole('status')).toHaveTextContent(es.offline.reading)

    act(() => onlineManager.setOnline(true))
    expect(screen.getByRole('status')).toHaveTextContent('Cargando los pagos…')
  })
})
