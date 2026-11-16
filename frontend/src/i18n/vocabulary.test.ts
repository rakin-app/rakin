import { afterEach, describe, expect, it } from 'vitest'
import { es } from './es'
import copySource from './es.ts?raw'
import { currentVocabulary, DEFAULT_VOCABULARY, wearVocabulary, w } from './vocabulary'

afterEach(() => wearVocabulary(null))

// Every string under `node`, functions called with stand-in arguments: what a screen
// built from that part of the copy can say.
function resolved(node: unknown): unknown {
  if (typeof node === 'function') {
    try {
      return (node as (...args: unknown[]) => unknown)(2, 3, 4)
    } catch {
      return '<fn>'
    }
  }
  if (Array.isArray(node)) return node.map(resolved)
  if (node !== null && typeof node === 'object') {
    const out: Record<string, unknown> = {}
    for (const key of Object.keys(node)) out[key] = resolved((node as Record<string, unknown>)[key])
    return out
  }
  return node
}

describe("a gym's words", () => {
  it('reads exactly as before with none set: nav, Hoy and Alumnos', () => {
    // The snapshot was written from the copy before #344, which had no words at all.
    expect(resolved({ nav: es.nav, today: es.admin.today, students: es.admin.students })).toMatchSnapshot()
  })

  it('reads a club of socios in every place that names them', () => {
    wearVocabulary({ place: 'club', members: 'socios', coach: 'entrenador' })

    expect(es.nav.students).toBe('Socios')
    expect(es.admin.students.title).toBe('Socios')
    expect(es.admin.students.newLink).toBe('Nuevo socio')
    expect(es.admin.newMember.title).toBe('Nuevo socio')
    expect(es.admin.today.setup.title).toBe('Configura tu club')
    expect(es.admin.today.setup.steps.staff.hint).toBe('Admins y entrenadores, cada uno con su acceso.')
    expect(es.admin.students.count(3)).toBe('3 socios')
    expect(es.admin.member.since('mar 2024')).toBe('Socio desde mar 2024')
    // The join form's words.
    expect(es.join.intro).toBe('Llena tus datos y el club confirmará tu inscripción.')
    expect(es.join.consentBefore).toBe('Acepto que el club trate estos datos para gestionar mi inscripción, según su ')
    expect(es.join.invalid).toBe('Este link ya no es válido. Pídele uno nuevo al club.')
    expect(es.join.phoneHint).toContain('El club te avisa por WhatsApp')
  })

  it('agrees with a feminine place, and says the coach the gym says', () => {
    wearVocabulary({ place: 'escuela', members: 'deportistas', coach: 'sensei' })

    expect(es.admin.today.setup.title).toBe('Configura tu escuela')
    expect(es.admin.today.setup.steps.gym.title).toBe('Datos de la escuela y cuenta bancaria')
    expect(es.join.invalid).toBe('Este link ya no es válido. Pídele uno nuevo a la escuela.')
    expect(es.privacy.missing).toBe('Esta escuela todavía no publica su política de privacidad.')
    expect(es.matTime.emptyMine).toContain('cuando tu sensei use el cronómetro')
    expect(es.admin.newMember.former.submit).toBe('Guardar exdeportista')
  })

  it('leaves a word it does not know at today’s', () => {
    wearVocabulary({ place: 'estadio' as never, members: 'socios', coach: undefined })
    expect(currentVocabulary()).toEqual({ ...DEFAULT_VOCABULARY, members: 'socios' })
    expect(w.thePlace).toBe('la academia')
  })

  it('names no academia and no alumno in the copy itself', () => {
    // Every one comes from the gym's words (`vocabulary.ts`); comments and object keys
    // (`tabs.alumnos`, the API's own name for the tab) are not copy.
    const source = copySource
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/.*$/gm, '')
    const words = [...source.matchAll(/\b(ex)?(academias?|alumn[oa]s?)\b(?!\s*(\(\)|:))/gi)].map((m) => m[0])
    expect(words).toEqual([])
  })
})
