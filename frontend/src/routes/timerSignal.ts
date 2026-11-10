import { useEffect, useState } from 'react'

/**
 * What the timer does besides its numbers: a beep and a buzz at the 10-second warning and
 * when a round or block ends, and the screen kept on while it runs.
 *
 * The sound is made with Web Audio, so there is no file to load offline. A phone plays it
 * only once a tap has allowed it, which is what `unlockSound` is for: "Comenzar" calls it.
 */
let audio: AudioContext | null = null

export function unlockSound(): void {
  try {
    if (typeof window.AudioContext !== 'function') return
    audio ??= new window.AudioContext()
    void audio.resume()
  } catch {
    // No sound on this phone; the vibration and the screen still say it.
  }
}

function beep(frequency: number, seconds: number, at: number): void {
  if (!audio) return
  const tone = audio.createOscillator()
  const gain = audio.createGain()
  tone.frequency.value = frequency
  gain.gain.setValueAtTime(0.4, audio.currentTime + at)
  gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + at + seconds)
  tone.connect(gain).connect(audio.destination)
  tone.start(audio.currentTime + at)
  tone.stop(audio.currentTime + at + seconds)
}

/** `warn`: ten seconds left. `end`: a round, rest or block ran out. */
export function signal(kind: 'warn' | 'end'): void {
  try {
    if (kind === 'warn') {
      beep(880, 0.15, 0)
    } else {
      beep(660, 0.25, 0)
      beep(660, 0.25, 0.35)
      beep(990, 0.6, 0.7)
    }
  } catch {
    // A sound that fails is no reason to stop the timer.
  }
  if (typeof navigator.vibrate === 'function') navigator.vibrate(kind === 'warn' ? 200 : [400, 150, 400, 150, 600])
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
