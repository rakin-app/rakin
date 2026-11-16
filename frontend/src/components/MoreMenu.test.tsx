import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MoreMenu, moreItemClass } from './MoreMenu'

function renderMenu(onPick = vi.fn()) {
  render(
    <>
      <button type="button">Fuera</button>
      <MoreMenu label="Más" ariaLabel="Más acciones para Ana">
        <button type="button" className={moreItemClass()} onClick={onPick}>
          Editar monto
        </button>
        <button type="button" className={moreItemClass(true)}>
          Anular
        </button>
      </MoreMenu>
    </>,
  )
  const summary = screen.getByText('Más').closest('summary')!
  return { menu: summary.closest('details')!, summary }
}

describe('MoreMenu (#357)', () => {
  it('opens on its button, named for whom it is, and closes once an action is chosen', async () => {
    const user = userEvent.setup()
    const onPick = vi.fn()
    const { menu, summary } = renderMenu(onPick)

    expect(summary).toHaveAttribute('aria-label', 'Más acciones para Ana')
    expect(menu.open).toBe(false)
    await user.click(summary)
    expect(menu.open).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Editar monto' }))
    expect(onPick).toHaveBeenCalledOnce()
    expect(menu.open).toBe(false)
    expect(screen.getByRole('button', { name: 'Anular' })).toHaveClass('more-menu__item--danger')
  })

  it('closes on a tap outside it, and on Esc back to its button', async () => {
    const user = userEvent.setup()
    const { menu, summary } = renderMenu()

    await user.click(summary)
    await user.click(screen.getByRole('button', { name: 'Fuera' }))
    expect(menu.open).toBe(false)

    await user.click(summary)
    await user.keyboard('{Escape}')
    expect(menu.open).toBe(false)
    expect(summary).toHaveFocus()
  })

  it('closes once the keyboard tabs out of it', async () => {
    const user = userEvent.setup()
    render(
      <>
        <MoreMenu label="Más">
          <button type="button" className={moreItemClass()}>
            Editar monto
          </button>
        </MoreMenu>
        <button type="button">Siguiente fila</button>
      </>,
    )
    const summary = screen.getByText('Más').closest('summary')!
    const menu = summary.closest('details')!

    await user.click(summary)
    await user.tab()
    expect(screen.getByRole('button', { name: 'Editar monto' })).toHaveFocus()
    expect(menu.open).toBe(true)
    await user.tab()
    expect(screen.getByRole('button', { name: 'Siguiente fila' })).toHaveFocus()
    expect(menu.open).toBe(false)
  })
})
