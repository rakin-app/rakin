import { useEffect, useId, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { LogoCrop } from '../api/gym'
import './LogoCropper.css'

/** The viewport's side, in CSS pixels: the circle the logo will fill. */
export const VIEW = 240
const MAX_ZOOM = 4
// How far an arrow key moves the picture.
const STEP = 8

type Labels = { frame: string; zoom: string }

type Props = {
  src: string
  labels: Labels
  /** The square kept, in the picture's own pixels, each time it changes; null until it loads. */
  onChange: (crop: LogoCrop | null) => void
}

type Natural = { width: number; height: number }
type Offset = { x: number; y: number }

/** The picture's scale on screen at `zoom`: 1 fills the circle with its shorter side. */
export function scaleOf(natural: Natural, zoom: number): number {
  return (VIEW / Math.min(natural.width, natural.height)) * zoom
}

/** `offset` (the picture's top-left in the viewport) kept so the picture covers the viewport. */
export function clampOffset(natural: Natural, zoom: number, offset: Offset): Offset {
  const scale = scaleOf(natural, zoom)
  const clamp = (value: number, length: number) => Math.min(0, Math.max(VIEW - length * scale, value))
  return { x: clamp(offset.x, natural.width), y: clamp(offset.y, natural.height) }
}

/** The square of the picture the viewport shows, in the picture's pixels. */
export function cropOf(natural: Natural, zoom: number, offset: Offset): LogoCrop {
  const scale = scaleOf(natural, zoom)
  const size = Math.min(Math.round(VIEW / scale), natural.width, natural.height)
  const fit = (start: number, length: number) => Math.min(Math.max(0, Math.round(-start / scale)), length - size)
  return { x: fit(offset.x, natural.width), y: fit(offset.y, natural.height), size }
}

/**
 * The crop step for the gym's logo (#223): the picture behind a circular window, to drag
 * into place (or move with the arrow keys) and zoom with the slider. What the circle
 * shows is what the logo will be. The browser shows the picture upright, as the server
 * reads it, so the square is in the same pixels on both sides.
 */
export function LogoCropper({ src, labels, onChange }: Props) {
  const zoomId = useId()
  const [natural, setNatural] = useState<Natural | null>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState<Offset>({ x: 0, y: 0 })
  const [drag, setDrag] = useState<{ pointer: number; x: number; y: number; from: Offset } | null>(null)

  useEffect(() => {
    onChange(natural ? cropOf(natural, zoom, offset) : null)
  }, [natural, zoom, offset, onChange])

  function loaded(image: HTMLImageElement) {
    const found = { width: image.naturalWidth, height: image.naturalHeight }
    if (!found.width || !found.height) return
    const scale = scaleOf(found, 1)
    setNatural(found)
    setZoom(1)
    // Centred, as the server cuts a picture sent with no square.
    setOffset({ x: (VIEW - found.width * scale) / 2, y: (VIEW - found.height * scale) / 2 })
  }

  function zoomTo(next: number) {
    if (!natural) return
    // About the circle's centre, so what is in the middle stays there.
    const before = scaleOf(natural, zoom)
    const after = scaleOf(natural, next)
    const centre = (start: number) => VIEW / 2 - ((VIEW / 2 - start) / before) * after
    setZoom(next)
    setOffset(clampOffset(natural, next, { x: centre(offset.x), y: centre(offset.y) }))
  }

  function move(to: Offset) {
    if (natural) setOffset(clampOffset(natural, zoom, to))
  }

  function down(event: PointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setDrag({ pointer: event.pointerId, x: event.clientX, y: event.clientY, from: offset })
  }

  function moved(event: PointerEvent<HTMLDivElement>) {
    if (!drag || drag.pointer !== event.pointerId) return
    move({ x: drag.from.x + event.clientX - drag.x, y: drag.from.y + event.clientY - drag.y })
  }

  function key(event: KeyboardEvent<HTMLDivElement>) {
    const by = {
      ArrowLeft: { x: STEP, y: 0 },
      ArrowRight: { x: -STEP, y: 0 },
      ArrowUp: { x: 0, y: STEP },
      ArrowDown: { x: 0, y: -STEP },
    }[event.key]
    if (!by) return
    event.preventDefault()
    move({ x: offset.x + by.x, y: offset.y + by.y })
  }

  const scale = natural ? scaleOf(natural, zoom) : 0
  return (
    <div className="logo-crop">
      <div
        className="logo-crop__frame"
        style={{ width: VIEW, height: VIEW }}
        role="group"
        aria-label={labels.frame}
        tabIndex={0}
        onPointerDown={down}
        onPointerMove={moved}
        onPointerUp={() => setDrag(null)}
        onPointerCancel={() => setDrag(null)}
        onKeyDown={key}
      >
        <img
          className="logo-crop__image"
          src={src}
          // The frame's label says what it is.
          alt={''}
          draggable={false}
          onLoad={(event) => loaded(event.currentTarget)}
          style={
            natural
              ? { left: offset.x, top: offset.y, width: natural.width * scale, height: natural.height * scale }
              : { visibility: 'hidden' }
          }
        />
        <span className="logo-crop__mask" aria-hidden="true" />
      </div>
      <label className="logo-crop__zoom" htmlFor={zoomId}>
        <span>{labels.zoom}</span>
        <input
          id={zoomId}
          type="range"
          min={1}
          max={MAX_ZOOM}
          step={0.01}
          value={zoom}
          disabled={!natural}
          onChange={(event) => zoomTo(Number(event.target.value))}
        />
      </label>
    </div>
  )
}
