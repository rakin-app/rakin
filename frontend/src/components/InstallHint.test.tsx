import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { es } from '../i18n/es'
import { InstallHint, isIosSafari } from './InstallHint'

const copy = es.installHint

const IPHONE_SAFARI =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
const IPHONE_CHROME =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/138.0.7204.156 Mobile/15E148 Safari/604.1'
const IPHONE_INSTAGRAM =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 389.0.0.0'
const IPAD_DESKTOP =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15'
const ANDROID_CHROME =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'

describe('isIosSafari', () => {
  it('is Safari on an iPhone, and on an iPad that asks for the desktop site', () => {
    expect(isIosSafari(IPHONE_SAFARI, 5)).toBe(true)
    expect(isIosSafari(IPAD_DESKTOP, 5)).toBe(true)
  })

  it('is not a Mac, other browsers on iOS, nor Android', () => {
    expect(isIosSafari(IPAD_DESKTOP, 0)).toBe(false)
    expect(isIosSafari(IPHONE_CHROME, 5)).toBe(false)
    expect(isIosSafari(IPHONE_INSTAGRAM, 5)).toBe(false)
    expect(isIosSafari(ANDROID_CHROME, 5)).toBe(false)
  })
})

function onDevice(userAgent: string, { standalone = false } = {}) {
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(userAgent)
  // jsdom has no touch screen: no `maxTouchPoints` to spy on.
  Object.defineProperty(navigator, 'maxTouchPoints', { value: 5, configurable: true })
  Object.defineProperty(navigator, 'standalone', { value: standalone, configurable: true })
}

describe('InstallHint', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    delete (navigator as { standalone?: boolean }).standalone
    delete (navigator as { maxTouchPoints?: number }).maxTouchPoints
    localStorage.clear()
  })

  it('tells iOS Safari how to add Rakin to the home screen', () => {
    onDevice(IPHONE_SAFARI)
    render(<InstallHint />)
    expect(screen.getByRole('complementary', { name: copy.label })).toHaveTextContent(copy.title)
  })

  it('is not shown in the installed app, nor on Android', () => {
    onDevice(IPHONE_SAFARI, { standalone: true })
    const { unmount } = render(<InstallHint />)
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    unmount()

    onDevice(ANDROID_CHROME)
    render(<InstallHint />)
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })

  it('once closed, is never shown again in this browser', async () => {
    onDevice(IPHONE_SAFARI)
    const { unmount } = render(<InstallHint />)
    await userEvent.click(screen.getByRole('button', { name: copy.close }))
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    unmount()

    render(<InstallHint />)
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })
})
