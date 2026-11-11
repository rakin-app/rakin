import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GymSettings } from '../api/gym'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { clampOffset, cropOf, VIEW } from '../components/LogoCropper'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.gym.logo

const LOGO = '/api/logos/gym/0123456789abcdef'
const NEW_LOGO = '/api/logos/gym/fedcba9876543210'

const SETTINGS: GymSettings = {
  name: 'Academia Sur',
  slug: 'academia-sur',
  web_address: 'academia-sur.rakin.app',
  timezone: 'America/Santiago',
  theme: 'bosque',
  logo: null,
  grace_days: 5,
  reminder_every_days: 3,
  channels: { whatsapp: true },
  bank_account: null,
  privacy: null,
}

type Call = { method: string; path: string; body: unknown; contentType: string | null }
type Answer = { status?: number; body?: unknown }

function stubApi({ logo = null, upload }: { logo?: string | null; upload?: Answer } = {}) {
  const calls: Call[] = []
  let current: GymSettings = { ...SETTINGS, logo }
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const contentType = new Headers(init?.headers).get('Content-Type')
      calls.push({ method, path: `${url.pathname}${url.search}`, body: init?.body, contentType })
      const answer = route(url.pathname, method)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string): Answer {
    if (path === '/api/me/role') {
      return {
        body: {
          role: 'owner',
          person_id: 'me',
          name: 'Carla Soto',
          email: 'carla@example.cl',
          gym_name: 'Academia Sur',
          student_page: false,
          theme: 'bosque',
          gym_logo: current.logo,
        },
      }
    }
    if (path === '/api/host') {
      return { body: { gym: { slug: 'academia-sur', name: 'Academia Sur', theme: 'bosque', logo: current.logo } } }
    }
    if (path === '/api/gym/settings') return { body: current }
    if (path === '/api/gym/logo' && method === 'PUT') {
      if (upload) return upload
      current = { ...current, logo: NEW_LOGO }
      return { body: current }
    }
    if (path === '/api/gym/logo' && method === 'DELETE') {
      current = { ...current, logo: null }
      return { body: current }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

function file(name: string, type: string, size = 1000): File {
  const picked = new File(['x'], name, { type })
  Object.defineProperty(picked, 'size', { value: size })
  return picked
}

async function panel() {
  const legend = await screen.findByText(copy.title, { selector: 'legend' })
  return within(legend.closest('fieldset')!)
}

/** The picked picture's `load`, which jsdom never fires: `width` × `height` pixels. */
function loadPicture(width: number, height: number) {
  const frame = screen.getByRole('group', { name: copy.frame })
  const image = frame.querySelector('img')!
  Object.defineProperty(image, 'naturalWidth', { value: width })
  Object.defineProperty(image, 'naturalHeight', { value: height })
  fireEvent.load(image)
  return frame
}

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:picked'), revokeObjectURL: vi.fn() }))
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.head.querySelectorAll('link[rel="icon"]').forEach((link) => link.remove())
})

describe('the crop square', () => {
  it('starts as the middle square of the picture', () => {
    const natural = { width: 1200, height: 600 }
    const scale = VIEW / 600
    const centred = { x: (VIEW - 1200 * scale) / 2, y: 0 }
    expect(cropOf(natural, 1, centred)).toEqual({ x: 300, y: 0, size: 600 })
  })

  it('follows the zoom and the drag, in the picture’s own pixels', () => {
    const natural = { width: 1000, height: 1000 }
    // Twice as close, dragged to the bottom-right corner.
    const offset = clampOffset(natural, 2, { x: -10_000, y: -10_000 })
    expect(offset).toEqual({ x: -VIEW, y: -VIEW })
    expect(cropOf(natural, 2, offset)).toEqual({ x: 500, y: 500, size: 500 })
  })

  it('never lets the picture leave a gap in the circle', () => {
    expect(clampOffset({ width: 800, height: 400 }, 1, { x: 50, y: 50 })).toEqual({ x: 0, y: 0 })
  })
})

describe('Ajustes: Gimnasio, logo', () => {
  it('shows the initials while the gym has no logo', async () => {
    stubApi()
    renderAt('/admin/ajustes/gimnasio')
    const logo = await panel()
    expect(logo.getByText(copy.none)).toBeInTheDocument()
    expect(logo.getByText('AS')).toBeInTheDocument()
    expect(logo.queryByRole('button', { name: copy.remove })).not.toBeInTheDocument()
  })

  it('refuses an SVG and a file over 5 MB in Spanish, sending nothing', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')
    const logo = await panel()
    const input = logo.getByLabelText(copy.upload)

    await userEvent.upload(input, file('logo.svg', 'image/svg+xml'), { applyAccept: false })
    expect(await logo.findByRole('alert')).toHaveTextContent(copy.refused.type)

    await userEvent.upload(input, file('logo.png', 'image/png', 5 * 1024 * 1024 + 1))
    expect(await logo.findByRole('alert')).toHaveTextContent(copy.refused.tooLarge)

    expect(calls.filter((c) => c.path.startsWith('/api/gym/logo'))).toEqual([])
  })

  it('uploads the picked file with the square framed in the circle, and shows it everywhere at once', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')
    const logo = await panel()
    const picked = file('logo.png', 'image/png')
    await userEvent.upload(logo.getByLabelText(copy.upload), picked)

    const save = logo.getByRole('button', { name: copy.save })
    expect(save).toBeDisabled()
    const frame = loadPicture(800, 400)
    // Two steps right with the keyboard: the square moves left over the picture.
    frame.focus()
    await userEvent.keyboard('{ArrowRight}{ArrowRight}')
    await userEvent.click(save)

    expect(await logo.findByRole('status')).toHaveTextContent(copy.saved)
    const put = calls.find((c) => c.method === 'PUT')!
    // 240 px show 400 of the picture's: the middle starts at 200, and 16 px are 27 of its.
    expect(put.path).toBe('/api/gym/logo?x=227&y=0&size=400')
    expect(put.body).toBe(picked)
    expect(put.contentType).toBe('image/png')

    // In the panel, and in the shell beside the gym's name.
    await waitFor(() => expect(document.querySelector(`img.gym-mark[src^="${NEW_LOGO}/"]`)).not.toBeNull())
    const shell = screen.getByRole('navigation', { name: es.nav.label })
    const mark = shell.querySelector('img.gym-mark')!
    expect(mark.getAttribute('alt')).toBe('')
    expect(mark.getAttribute('srcset')).toContain(`${NEW_LOGO}/128.webp 128w`)
    expect(logo.getByRole('button', { name: copy.remove })).toBeInTheDocument()
  })

  it('says why the API refused a file it could not read', async () => {
    stubApi({ upload: { status: 422, body: { detail: 'logo_unreadable' } } })
    renderAt('/admin/ajustes/gimnasio')
    const logo = await panel()
    await userEvent.upload(logo.getByLabelText(copy.upload), file('logo.png', 'image/png'))
    loadPicture(100, 100)
    await userEvent.click(logo.getByRole('button', { name: copy.save }))
    expect(await logo.findByRole('alert')).toHaveTextContent(copy.refused.unreadable)
  })

  it('replaces and removes the logo, back to the initials', async () => {
    const calls = stubApi({ logo: LOGO })
    renderAt('/admin/ajustes/gimnasio')
    const logo = await panel()
    expect(logo.getByText(copy.current)).toBeInTheDocument()
    expect(logo.getByLabelText(copy.replace)).toBeInTheDocument()

    await userEvent.click(logo.getByRole('button', { name: copy.remove }))
    expect(await logo.findByRole('status')).toHaveTextContent(copy.removed)
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/gym/logo')).toBe(true)
    expect(logo.getByText('AS')).toBeInTheDocument()
    expect(document.querySelector('img.gym-mark')).toBeNull()
  })

  it("shows the gym's logo in the tab on its own address", async () => {
    const icon = document.createElement('link')
    icon.rel = 'icon'
    icon.href = '/favicon.svg'
    document.head.append(icon)
    stubApi({ logo: LOGO })
    renderAt('/admin/ajustes/gimnasio')
    await waitFor(() => expect(icon.getAttribute('href')).toBe(`${LOGO}/64.webp`))
  })
})
