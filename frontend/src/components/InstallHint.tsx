import { useState } from 'react'
import { t } from '../i18n/es'
import { Button } from './Button'
import { CloseIcon, ShareIcon } from './icons'
import './InstallHint.css'

const copy = t.installHint

// Set once the hint is closed: it is never shown again in this browser.
const STORAGE_KEY = 'rakin.installHint'

/**
 * Safari on an iPhone or iPad, where adding to the home screen is in the share sheet
 * and the browser never offers it. An iPad asks for the desktop site and calls itself a
 * Mac, which has no touch screen. Chrome, Firefox, Edge and Opera on iOS, and the
 * browsers inside Instagram or Facebook, put it elsewhere or not at all.
 */
export function isIosSafari(userAgent: string, maxTouchPoints: number): boolean {
  const ios = /iPhone|iPad|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1)
  return ios && /Safari\//.test(userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS|FBAN|FBAV|Instagram/.test(userAgent)
}

/** Opened from the home screen already: Safari's own flag, or the manifest's display mode. */
function standalone(): boolean {
  const nav = navigator as Navigator & { standalone?: boolean }
  return nav.standalone === true || window.matchMedia?.('(display-mode: standalone)').matches === true
}

function dismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== null
  } catch {
    // Storage refused (a private window): shown, and closed for this visit only.
    return false
  }
}

function shouldShow(): boolean {
  return isIosSafari(navigator.userAgent, navigator.maxTouchPoints) && !standalone() && !dismissed()
}

/**
 * "Agrega Rakin a tu inicio" (#68): on iOS Safari, outside the installed app, how to add
 * it to the home screen, until it is closed once. Shown inside the signed-in shells, so the
 * app is added with the session on: Safari hands its cookies to the app it installs. On
 * Android the browser offers the install itself, from the manifest.
 */
export function InstallHint() {
  const [open, setOpen] = useState(shouldShow)
  if (!open) return null
  const close = () => {
    setOpen(false)
    try {
      localStorage.setItem(STORAGE_KEY, 'dismissed')
    } catch {
      // Not remembered: it shows again on the next visit.
    }
  }
  return (
    <aside className="install-hint" aria-label={copy.label}>
      <div className="install-hint__text">
        <p className="install-hint__title">{copy.title}</p>
        <p className="install-hint__body">
          {copy.before}
          <span className="install-hint__share">
            <ShareIcon />
          </span>
          {copy.after}
        </p>
      </div>
      <Button icon variant="ghost" aria-label={copy.close} onClick={close}>
        <CloseIcon />
      </Button>
    </aside>
  )
}
