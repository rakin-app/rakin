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

  // A Web Audio that records the tones asked of it.
  function fakeAudio() {
    const tones: { frequency: number; type: string }[] = []
    const node = () => ({ connect: (next: unknown) => next })
    class FakeContext {
      state = 'suspended'
      currentTime = 0
      sampleRate = 44_100
      destination = {}
      resume() {
        this.state = 'running'
        return Promise.resolve()
      }
      createBuffer() {
        return {}
      }
      createBufferSource() {
        return { ...node(), buffer: null, start() {} }
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
    return tones
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
    const tones = fakeAudio()
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
})
