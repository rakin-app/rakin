/// <reference types="node" />
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import { Button, buttonClass } from './Button'
import { EmptyState, ListRow, SectionHeader } from './Card'
import { Chip, ChipGroup, SegmentedControl } from './Chip'
import { Field, FieldError, Input, Select, Textarea } from './Field'
import { Grid, PageContainer } from './Layout'
import { STATUS_TONE, StatusPill } from './StatusPill'

// Vitest does not load CSS, so the tests read the files as text.
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('Button', () => {
  it('is a secondary 44px button by default, and never submits unless told', () => {
    render(<Button>Guardar</Button>)
    const button = screen.getByRole('button', { name: 'Guardar' })
    expect(button).toHaveAttribute('type', 'button')
    expect(button).toHaveClass('button', 'button--secondary')
    expect(button).not.toHaveClass('button--lg')
  })

  it('takes a variant, a size, full width, an icon shape and the dark surface', () => {
    render(
      <Button type="submit" variant="danger" size="lg" fullWidth icon inverse className="extra" aria-label="Quitar">
        x
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Quitar' })
    expect(button).toHaveAttribute('type', 'submit')
    expect(button).toHaveClass('button--danger', 'button--lg', 'button--full', 'button--icon', 'button--inverse', 'extra')
  })

  it('gives a link the same look', () => {
    expect(buttonClass({ variant: 'primary' })).toBe('button button--primary')
    expect(buttonClass()).toBe('button button--secondary')
  })
})

describe('Field', () => {
  it('labels its control and reads out its hint and error with it', () => {
    render(
      <Field label="RUT" hint="Con guion" error="No es un RUT">
        {(props) => <Input {...props} />}
      </Field>,
    )
    const input = screen.getByLabelText('RUT')
    expect(input).toHaveClass('control')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Con guion No es un RUT')
  })

  it('is valid and undescribed with neither', () => {
    render(<Field label="Nombre">{(props) => <Input {...props} />}</Field>)
    const input = screen.getByLabelText('Nombre')
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(input).not.toHaveAttribute('aria-describedby')
  })

  it('styles selects and textareas as controls too', () => {
    render(
      <>
        <Select aria-label="Plan">
          <option>Mensual</option>
        </Select>
        <Textarea aria-label="Nota" />
        <FieldError>Falta</FieldError>
      </>,
    )
    expect(screen.getByRole('combobox', { name: 'Plan' })).toHaveClass('control', 'control--select')
    expect(screen.getByRole('textbox', { name: 'Nota' })).toHaveClass('control', 'control--textarea')
    expect(screen.getByText('Falta')).toHaveClass('field__error')
  })
})

describe('Chip and SegmentedControl', () => {
  it('a chip says whether it is pressed', async () => {
    const onClick = vi.fn()
    render(
      <ChipGroup label="Estado">
        <Chip pressed onClick={onClick}>
          Activo
        </Chip>
        <Chip pressed={false}>Prueba</Chip>
      </ChipGroup>,
    )
    expect(screen.getByRole('group', { name: 'Estado' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Activo' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Prueba' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(screen.getByRole('button', { name: 'Activo' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('a chip row fades the edge more chips lie past (#358)', () => {
    render(
      <ChipGroup label="Estado">
        <Chip pressed={false}>Activo</Chip>
      </ChipGroup>,
    )
    const row = screen.getByRole('group', { name: 'Estado' })
    expect(row).not.toHaveAttribute('data-more-end')

    // jsdom lays nothing out: a row 300px wide holding 500px of chips.
    Object.defineProperty(row, 'clientWidth', { configurable: true, value: 300 })
    Object.defineProperty(row, 'scrollWidth', { configurable: true, value: 500 })
    fireEvent.scroll(row)
    expect(row).toHaveAttribute('data-more-end')
    expect(row).not.toHaveAttribute('data-more-start')

    row.scrollLeft = 200
    fireEvent.scroll(row)
    expect(row).toHaveAttribute('data-more-start')
    expect(row).not.toHaveAttribute('data-more-end')
  })

  it('a chip row measures again when its chips change, with no scroll (#418)', async () => {
    const { rerender } = render(
      <ChipGroup label="Estado">
        <Chip pressed={false}>Activo</Chip>
      </ChipGroup>,
    )
    const row = screen.getByRole('group', { name: 'Estado' })
    Object.defineProperty(row, 'clientWidth', { configurable: true, value: 300 })
    Object.defineProperty(row, 'scrollWidth', { configurable: true, value: 500 })
    expect(row).not.toHaveAttribute('data-more-end')

    rerender(
      <ChipGroup label="Estado">
        <Chip pressed={false}>Activo</Chip>
        <Chip pressed={false}>Prueba</Chip>
      </ChipGroup>,
    )

    await waitFor(() => expect(row).toHaveAttribute('data-more-end'))
  })

  it('a segmented control presses one option at a time', async () => {
    const onChange = vi.fn()
    render(
      <SegmentedControl
        label="Periodo"
        options={[
          { value: 'month', label: 'Este mes' },
          { value: 'all', label: 'Siempre' },
        ]}
        value="month"
        onChange={onChange}
      />,
    )
    expect(screen.getByRole('button', { name: 'Este mes' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Siempre' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(screen.getByRole('button', { name: 'Siempre' }))
    expect(onChange).toHaveBeenCalledWith('all')
  })
})

describe('Layout', () => {
  it('wraps a screen in the page container', () => {
    render(<PageContainer className="extra">x</PageContainer>)
    expect(screen.getByText('x')).toHaveClass('page-container', 'extra')
  })

  it('lays out two columns unless asked for three', () => {
    render(
      <>
        <Grid>two</Grid>
        <Grid columns={3}>three</Grid>
      </>,
    )
    expect(screen.getByText('two')).toHaveClass('grid', 'grid--2')
    expect(screen.getByText('three')).toHaveClass('grid', 'grid--3')
  })

  it('stays one column below 1024px and caps the page at the wide width', () => {
    const css = read('./Layout.css')
    const [phone, wide] = css.split('@media (--wide)')
    expect(phone).toMatch(/\.grid \{[^}]*grid-template-columns: minmax\(0, 1fr\)/)
    expect(phone).not.toMatch(/grid--[23] \{/)
    expect(wide).toMatch(/\.grid--3 \{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/)
    expect(css).toMatch(/max-width: var\(--content-wide\)/)
  })
})

describe('StatusPill', () => {
  it.each([
    ['active', 'success'],
    ['validated', 'success'],
    ['pending', 'accent'],
    ['overdue', 'warning'],
    ['rejected', 'danger'],
    ['lapsed', 'neutral'],
    ['trial', 'neutral'],
    ['frozen', 'neutral'],
  ] as const)('shows %s in the %s tone', (status, tone) => {
    render(<StatusPill status={status}>x</StatusPill>)
    expect(screen.getByText('x')).toHaveClass('status-pill', `status-pill--${tone}`)
    expect(STATUS_TONE[status]).toBe(tone)
  })

  it('keeps orange for overdue alone', () => {
    const warning = Object.entries(STATUS_TONE).filter(([, tone]) => tone === 'warning').map(([status]) => status)
    expect(warning).toEqual(['overdue'])
  })

  it('is not a control', () => {
    render(<StatusPill status="active">Activo</StatusPill>)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Activo').tagName).toBe('SPAN')
  })
})

describe('SectionHeader, ListRow and EmptyState', () => {
  it('lay out their slots', () => {
    render(
      <>
        <SectionHeader title="Por cobrar" trailing="3" />
        <ListRow title="Ana" detail="Mensual" trailing={<span>Vencido</span>} />
        <EmptyState action={<Button>Agregar</Button>}>Aún no hay alumnos.</EmptyState>
      </>,
    )
    expect(screen.getByRole('heading', { name: 'Por cobrar' })).toBeInTheDocument()
    expect(screen.getByText('3')).toHaveClass('section-header__trailing')
    expect(screen.getByText('Mensual')).toHaveClass('list-row__detail')
    expect(screen.getByText('Aún no hay alumnos.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agregar' })).toBeInTheDocument()
  })
})
