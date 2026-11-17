/**
 * What the gym calls itself, its members and its coach (#344): "academia", "club" or
 * "dojo"; "alumnos" or "socios"; "profe" or "sensei". The gym picks each from a short
 * list in Ajustes › Gimnasio (backend `app.domain.vocabulary`, which holds the keys and
 * what each activity preset brings); this file holds each option's forms and gender, so
 * the copy in `es.ts` agrees with it: "la academia", "el club", "Nuevo socio".
 *
 * The words come from the gym: `/api/me/role` once someone is signed in, `/api/host`
 * on its own address before, and the join form and privacy notice from their own
 * answers. Until one has answered, and in a gym that never picked any, they are
 * today's: academia, alumnos, profe.
 */

export const PLACES = ['academia', 'club', 'gimnasio', 'centro', 'escuela', 'dojo'] as const
export const MEMBERS = ['alumnos', 'socios', 'deportistas', 'miembros'] as const
export const COACHES = ['profe', 'sensei', 'coach', 'entrenador', 'instructor', 'profesor'] as const

export type Place = (typeof PLACES)[number]
export type Members = (typeof MEMBERS)[number]
export type Coach = (typeof COACHES)[number]

export type Vocabulary = { place: Place; members: Members; coach: Coach }

/** A noun as the copy needs it: singular, plural, and whether it is feminine. */
type Noun = { one: string; many: string; feminine: boolean }

const noun = (one: string, many: string, feminine = false): Noun => ({ one, many, feminine })

export const PLACE_NOUNS: Record<Place, Noun> = {
  academia: noun('academia', 'academias', true),
  club: noun('club', 'clubes'),
  gimnasio: noun('gimnasio', 'gimnasios'),
  centro: noun('centro', 'centros'),
  escuela: noun('escuela', 'escuelas', true),
  dojo: noun('dojo', 'dojos'),
}

export const MEMBER_NOUNS: Record<Members, Noun> = {
  alumnos: noun('alumno', 'alumnos'),
  socios: noun('socio', 'socios'),
  deportistas: noun('deportista', 'deportistas'),
  miembros: noun('miembro', 'miembros'),
}

export const COACH_NOUNS: Record<Coach, Noun> = {
  profe: noun('profe', 'profes'),
  sensei: noun('sensei', 'senseis'),
  coach: noun('coach', 'coaches'),
  entrenador: noun('entrenador', 'entrenadores'),
  instructor: noun('instructor', 'instructores'),
  profesor: noun('profesor', 'profesores'),
}

const cap = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** How each option reads in Ajustes' selects: "Academia", "Alumnos", "Profe". */
export const placeLabel = (key: Place) => cap(PLACE_NOUNS[key].one)
export const membersLabel = (key: Members) => cap(MEMBER_NOUNS[key].many)
export const coachLabel = (key: Coach) => cap(COACH_NOUNS[key].one)

export const sameWords = (a: Vocabulary, b: Vocabulary) =>
  a.place === b.place && a.members === b.members && a.coach === b.coach

/** Today's words: a gym that never picked any reads exactly as before. */
export const DEFAULT_VOCABULARY: Vocabulary = { place: 'academia', members: 'alumnos', coach: 'profe' }

let current: Vocabulary = DEFAULT_VOCABULARY

const isOf = <T extends string>(options: readonly T[], value: unknown): value is T =>
  typeof value === 'string' && (options as readonly string[]).includes(value)

/**
 * The words every screen reads from now on: the gym's, or today's for none. A word this
 * build does not know (a newer backend's option) reads as today's, never as blank.
 * Called before the screens that read them render (`router.tsx`, `App.tsx`).
 */
export function wearVocabulary(vocabulary: Partial<Vocabulary> | null | undefined): void {
  current = {
    place: isOf(PLACES, vocabulary?.place) ? vocabulary.place : DEFAULT_VOCABULARY.place,
    members: isOf(MEMBERS, vocabulary?.members) ? vocabulary.members : DEFAULT_VOCABULARY.members,
    coach: isOf(COACHES, vocabulary?.coach) ? vocabulary.coach : DEFAULT_VOCABULARY.coach,
  }
}

/** The words being worn. */
export function currentVocabulary(): Vocabulary {
  return current
}

/**
 * What the gym calls its free practice and the open mat made of it (#346, backend
 * `app.domain.practice`): "Sparring" and "Open mat" in BJJ, "Randori" in judo,
 * "Escalada libre" in a climbing gym, "Práctica libre" with no activity yet. Names, not
 * nouns with a gender, so the copy uses them without an article: "rounds de randori".
 */
export type PracticeNames = { block: string; open_mat: string }

/** Today's, for a gym that has not answered yet. */
const DEFAULT_PRACTICE: PracticeNames = { block: 'Sparring', open_mat: 'Open mat' }

let practice: PracticeNames = DEFAULT_PRACTICE

/** The names every screen reads from now on, from `/api/me/role`; today's for none. */
export function wearPractice(names: Partial<PracticeNames> | null | undefined): void {
  const block = names?.block || DEFAULT_PRACTICE.block
  practice = { block, open_mat: names?.open_mat || (names?.block ? block : DEFAULT_PRACTICE.open_mat) }
}

/** A name inside a sentence: "escalada libre", but "MMA" as written. */
const inSentence = (name: string) => {
  const second = name.charAt(1)
  return second !== second.toLowerCase() ? name : name.charAt(0).toLowerCase() + name.slice(1)
}

const place = () => PLACE_NOUNS[current.place]
const member = () => MEMBER_NOUNS[current.members]
const coach = () => COACH_NOUNS[current.coach]

/**
 * The gym's words, as the copy reads them: read at the moment a string is built, so a
 * string in `es.ts` that uses one is a getter or a function. Lower case unless named
 * with a capital: `w.members` is "alumnos", `w.Members` "Alumnos".
 */
export const w = {
  // The place: "academia", "la academia", "del club".
  get place() {
    return place().one
  },
  get Place() {
    return cap(place().one)
  },
  get thePlace() {
    return `${place().feminine ? 'la' : 'el'} ${place().one}`
  },
  get ThePlace() {
    return cap(w.thePlace)
  },
  get ofThePlace() {
    return place().feminine ? `de la ${place().one}` : `del ${place().one}`
  },
  get toThePlace() {
    return place().feminine ? `a la ${place().one}` : `al ${place().one}`
  },
  get aPlace() {
    return `${place().feminine ? 'una' : 'un'} ${place().one}`
  },
  get places() {
    return place().many
  },
  /** `masculine` or `feminine`, as the place's noun is: "tu academia, configurada". */
  placeIs: (masculine: string, feminine: string) => (place().feminine ? feminine : masculine),

  // The members: "alumno", "alumnos", "exalumno".
  get member() {
    return member().one
  },
  get Member() {
    return cap(member().one)
  },
  get members() {
    return member().many
  },
  get Members() {
    return cap(member().many)
  },
  get theMember() {
    return `${member().feminine ? 'la' : 'el'} ${member().one}`
  },
  get ofTheMember() {
    return member().feminine ? `de la ${member().one}` : `del ${member().one}`
  },
  get toTheMember() {
    return member().feminine ? `a la ${member().one}` : `al ${member().one}`
  },
  get aMember() {
    return `${member().feminine ? 'una' : 'un'} ${member().one}`
  },
  get theMembers() {
    return `${member().feminine ? 'las' : 'los'} ${member().many}`
  },
  get TheMembers() {
    return cap(w.theMembers)
  },
  get formerMember() {
    return `ex${member().one}`
  },
  get FormerMember() {
    return cap(w.formerMember)
  },
  get formerMembers() {
    return `ex${member().many}`
  },
  get FormerMembers() {
    return cap(w.formerMembers)
  },
  /** `masculine` or `feminine`, as the members' noun is: "Nuevo alumno". */
  memberIs: (masculine: string, feminine: string) => (member().feminine ? feminine : masculine),
  /** "1 alumno", "3 alumnos"; `n` as the caller wrote it, such as with thousands. */
  memberCount: (count: number, n: string = String(count)) =>
    count === 1 ? `1 ${member().one}` : `${n} ${member().many}`,

  // The coach: "profe", "el profe", "profes".
  get coach() {
    return coach().one
  },
  get coaches() {
    return coach().many
  },
  get theCoach() {
    return `${coach().feminine ? 'la' : 'el'} ${coach().one}`
  },

  // The free practice and its open mat: "sparring", "Escalada libre", "open mat".
  get practice() {
    return inSentence(practice.block)
  },
  get Practice() {
    return cap(practice.block)
  },
  get openMat() {
    return inSentence(practice.open_mat)
  },
  get OpenMat() {
    return cap(practice.open_mat)
  },
  /** Whether the open mat has a name of its own, as BJJ's "Open mat". */
  get openMatNamed() {
    return practice.open_mat !== practice.block
  },
}
