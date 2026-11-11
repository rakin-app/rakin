import { useEffect, useState, useSyncExternalStore } from 'react'
import type { RunState } from './timerEngine'

/**
 * What the timer does besides its numbers: a beep and a buzz at the 10-second warning and
 * at each switch, and the screen kept on while it runs. Each switch sounds its own way, so
 * the mat hears whether to fight or to stop without looking: a bell to start a round, a
 * long low tone to stop for the rest, and a chime when one block gives way to the next.
 *
 * The sound is made with Web Audio, so there is no file to load offline. A phone plays it
 * only once a tap has allowed it, which is what `unlockSound` is for: "Comenzar" calls it,
 * and so does any tap on the running timer, for a class opened again after a reload or a
 * context the phone suspended since.
 */
let audio: AudioContext | null = null
// Set when this browser has no Web Audio, or refused to make one on the last attempt.
let unsupported = false

/** `warn`: ten seconds left. `fight`: a round starts. `rest`: a round stops for the rest.
 * `block`: a block ran out, and the next starts. */
export type Signal = 'warn' | 'fight' | 'rest' | 'block'

export const VIBRATION: Record<Signal, number | number[]> = {
  warn: 200,
  fight: [150, 100, 150],
  rest: [1000],
  block: [400, 150, 400, 150, 600],
}

/** The signal for the switch from `before` to `after`, a phase that ran out: `block` when
 * the block changed (or the class ended), else `rest` or `fight` for the phase now on. */
export function switchSignal(before: RunState, after: RunState): Signal {
  if (after.index !== before.index || after.endedAt !== null) return 'block'
  return after.resting ? 'rest' : 'fight'
}

/** Allow sound, inside a tap. The first tap makes the context and plays a silent blip in
 * it, which iOS asks before it lets one play; a later tap only resumes one that was
 * suspended (iOS does, in the background) or makes a new one for one that was closed. */
export function unlockSound(): void {
  // Asked again on every attempt: a failure once is not a phone without sound.
  if (typeof window.AudioContext !== 'function') return setUnsupported(true)
  if (audio?.state === 'running') return
  if (audio?.state === 'closed') audio = null
  if (!audio) {
    try {
      audio = new window.AudioContext()
    } catch {
      // No sound on this phone; the vibration and the screen still say it.
      return setUnsupported(true)
    }
    audio.addEventListener('statechange', notify)
    setUnsupported(false)
    try {
      // Safari 17+: play through the ringer switch, as a timer must.
      const session = (navigator as Navigator & { audioSession?: { type: string } }).audioSession
      if (session) session.type = 'playback'
      const silent = audio.createBufferSource()
      silent.buffer = audio.createBuffer(1, 1, audio.sampleRate)
      silent.connect(audio.destination)
      silent.start(0)
    } catch {
      // Without the blip the resume may still be enough.
    }
  }
  audio.resume().then(notify, () => undefined)
}

export type SoundState = 'on' | 'locked' | 'unsupported'

/** `locked`: no tap has allowed sound yet on this page (a class opened after a reload), or
 * the phone suspended or closed it since: the next tap brings it back. */
export function soundState(): SoundState {
  if (unsupported) return 'unsupported'
  return audio?.state === 'running' ? 'on' : 'locked'
}

// Who shows the sound state, told when it changes: it changes after a tap, in a promise,
// and a paused timer has no tick to notice it by.
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

function setUnsupported(value: boolean): void {
  if (unsupported === value) return
  unsupported = value
  notify()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The sound state, rendered again whenever it changes. */
export function useSoundState(): SoundState {
  return useSyncExternalStore(subscribe, soundState, () => 'on')
}

function beep(frequency: number, seconds: number, at: number, type: OscillatorType = 'sine'): void {
  if (!audio) return
  const tone = audio.createOscillator()
  const gain = audio.createGain()
  tone.type = type
  tone.frequency.value = frequency
  gain.gain.setValueAtTime(0.4, audio.currentTime + at)
  gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + at + seconds)
  tone.connect(gain).connect(audio.destination)
  tone.start(audio.currentTime + at)
  tone.stop(audio.currentTime + at + seconds)
}

export function signal(kind: Signal): void {
  try {
    if (kind === 'warn') {
      beep(880, 0.15, 0)
    } else if (kind === 'fight') {
      // A bell: two bright strikes, each with a ringing overtone.
      for (const at of [0, 0.3]) {
        beep(1320, 0.28, at, 'triangle')
        beep(2640, 0.18, at)
      }
    } else if (kind === 'rest') {
      beep(330, 1.2, 0, 'square')
    } else {
      beep(660, 0.25, 0)
      beep(660, 0.25, 0.35)
      beep(990, 0.6, 0.7)
    }
  } catch {
    // A sound that fails is no reason to stop the timer.
  }
  if (typeof navigator.vibrate === 'function') navigator.vibrate(VIBRATION[kind])
}

export type WakeLockState = 'on' | 'unsupported' | 'off'

/** Keep the screen on while `active`: asked again when the page comes back into view,
 * since the phone lets go of it on every lock. `unsupported` when the phone cannot. */
export function useWakeLock(active: boolean): WakeLockState {
  const supported = typeof navigator !== 'undefined' && 'wakeLock' in navigator
  const [state, setState] = useState<WakeLockState>(supported ? 'off' : 'unsupported')

  useEffect(() => {
    if (!active || !supported) return
    let lock: WakeLockSentinel | null = null
    let stopped = false
    const request = () => {
      if (document.visibilityState !== 'visible' || (lock && !lock.released)) return
      navigator.wakeLock.request('screen').then(
        (sentinel) => {
          if (stopped) {
            void sentinel.release()
            return
          }
          lock = sentinel
          setState('on')
          sentinel.addEventListener('release', () => {
            if (!stopped) setState('off')
          })
        },
        // Refused (a battery saver, a page not in view): the note says what to do.
        () => setState('unsupported'),
      )
    }
    request()
    document.addEventListener('visibilitychange', request)
    return () => {
      stopped = true
      document.removeEventListener('visibilitychange', request)
      void lock?.release()
    }
  }, [active, supported])

  return state
}
