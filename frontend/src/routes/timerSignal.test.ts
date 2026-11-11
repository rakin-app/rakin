import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { startRun, type RunState, type TimerBlock } from './timerEngine'
import { switchSignal, VIBRATION } from './timerSignal'

const sparring: TimerBlock = {
  id: 'sp',
  kindId: 'k-sp',
  kindName: 'Sparring',
  sparring: true,
  seconds: 0,
  rounds: 3,
  roundSeconds: 300,
  restSeconds: 60,
}
const warmup: TimerBlock = { ...sparring, id: 'wu', kindName: 'Calentamiento', sparring: false, seconds: 600 }
const at = (state: Partial<RunState>): RunState => ({ ...startRun([warmup, sparring], 0), ...state })

describe('switchSignal', () => {
  it.each([
    ['a block to the next', at({ index: 0 }), at({ index: 1 }), 'block'],
    ['the last block to the end', at({ index: 1, round: 3 }), at({ index: 2, endedAt: 1 }), 'block'],
    ['a round to its rest', at({ index: 1, round: 1 }), at({ index: 1, round: 1, resting: true }), 'rest'],
    ['a rest to the next round', at({ index: 1, round: 1, resting: true }), at({ index: 1, round: 2 }), 'fight'],
    ['a round to the next, with no rest', at({ index: 1, round: 1 }), at({ index: 1, round: 2 }), 'fight'],
  ] as const)('%s: %s', (_what, before, after, expected) => {
    expect(switchSignal(before, after)).toBe(expected)
  })

  it('buzzes each signal its own way', () => {
    const patterns = Object.values(VIBRATION).map((p) => JSON.stringify(p))
    expect(new Set(patterns).size).toBe(patterns.length)
  })
})

describe('the sounds', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  // A Web Audio that records the contexts made, the blips and the tones asked of it.
  function fakeAudio({ failFirst = false } = {}) {
    const tones: { frequency: number; type: string }[] = []
    const contexts: FakeContext[] = []
    let blips = 0
    let fail = failFirst
    const node = () => ({ connect: (next: unknown) => next })
    class FakeContext extends EventTarget {
      state: AudioContextState = 'suspended'
      currentTime = 0
      sampleRate = 44_100
      destination = {}
      constructor() {
        super()
        if (fail) {
          fail = false
          throw new Error('NotAllowedError')
        }
        contexts.push(this)
      }
      to(state: AudioContextState) {
        this.state = state
        this.dispatchEvent(new Event('statechange'))
      }
      resume() {
        this.to('running')
        return Promise.resolve()
      }
      createBuffer() {
        return {}
      }
      createBufferSource() {
        return {
          ...node(),
          buffer: null,
          start() {
            blips += 1
          },
        }
      }
      createGain() {
        return { ...node(), gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} } }
      }
      createOscillator() {
        const tone = { type: 'sine', frequency: { value: 0 } }
        return {
          ...node(),
          set type(value: string) {
            tone.type = value
          },
          frequency: tone.frequency,
          start() {
            tones.push({ frequency: tone.frequency.value, type: tone.type })
          },
          stop() {},
        }
      }
    }
    vi.stubGlobal('AudioContext', FakeContext)
    return { tones, contexts, blips: () => blips }
  }

  it('is locked until a tap, then on', async () => {
    fakeAudio()
    const { soundState, unlockSound } = await import('./timerSignal')
    expect(soundState()).toBe('locked')
    unlockSound()
    await Promise.resolve()
    expect(soundState()).toBe('on')
  })

  it('is unsupported without Web Audio', async () => {
    vi.stubGlobal('AudioContext', undefined)
    const { soundState, unlockSound } = await import('./timerSignal')
    unlockSound()
    expect(soundState()).toBe('unsupported')
  })

  it('rings a bright double bell for a round, a long low tone for the rest, the chime for a block', async () => {
    const { tones } = fakeAudio()
    const { signal, unlockSound } = await import('./timerSignal')
    unlockSound()
    const heard = (kind: Parameters<typeof signal>[0]) => {
      tones.length = 0
      signal(kind)
      return tones.map((t) => t.frequency)
    }
    expect(heard('fight')).toEqual([1320, 2640, 1320, 2640])
    expect(heard('rest')).toEqual([330])
    expect(heard('block')).toEqual([660, 660, 990])
    expect(heard('warn')).toEqual([880])
  })

  it('unlocks once: a later tap on a running context makes nothing new', async () => {
    const audio = fakeAudio()
    const { unlockSound } = await import('./timerSignal')
    unlockSound()
    unlockSound()
    unlockSound()
    expect(audio.contexts).toHaveLength(1)
    expect(audio.blips()).toBe(1)
  })

  it('resumes a context the phone suspended, and makes a new one for a closed one', async () => {
    const audio = fakeAudio()
    const { soundState, unlockSound } = await import('./timerSignal')
    unlockSound()
    audio.contexts[0]!.to('suspended')
    expect(soundState()).toBe('locked')
    unlockSound()
    expect(soundState()).toBe('on')
    expect(audio.contexts).toHaveLength(1)

    audio.contexts[0]!.to('closed')
    expect(soundState()).toBe('locked')
    unlockSound()
    expect(audio.contexts).toHaveLength(2)
    expect(soundState()).toBe('on')
  })

  it('does not hold one failed attempt against the next', async () => {
    fakeAudio({ failFirst: true })
    const { soundState, unlockSound } = await import('./timerSignal')
    unlockSound()
    expect(soundState()).toBe('unsupported')
    unlockSound()
    expect(soundState()).toBe('on')
  })

  it('renders again when sound comes on or goes, with no tick to wait for', async () => {
    const audio = fakeAudio()
    const { unlockSound, useSoundState } = await import('./timerSignal')
    const { result } = renderHook(() => useSoundState())
    expect(result.current).toBe('locked')
    act(() => unlockSound())
    expect(result.current).toBe('on')
    act(() => audio.contexts[0]!.to('suspended'))
    expect(result.current).toBe('locked')
  })
})
