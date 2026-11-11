import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useId, useState, type ChangeEvent } from 'react'
import { ApiError } from '../api/client'
import { gymSettingsQuery, removeLogo, uploadLogo, type GymSettings, type LogoCrop } from '../api/gym'
import { hostQuery, type Host } from '../api/host'
import { myselfQuery, type MyRole } from '../api/me'
import { useSubmit } from '../api/submit'
import { Button, buttonClass } from '../components/Button'
import { GymMark } from '../components/GymMark'
import { LogoCropper } from '../components/LogoCropper'
import { t } from '../i18n/es'
import { LOGO_TYPES, MAX_LOGO_BYTES } from '../logo'

const copy = t.admin.settings.gym.logo

type Refusal = keyof typeof copy.refused

/** What the API's refusal of an upload means, in the words of `copy.refused`. */
function refusalOf(error: unknown): Refusal {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail
    if (detail === 'logo_type') return 'type'
    if (detail === 'logo_too_large' || error.status === 413) return 'tooLarge'
    if (detail === 'logo_unreadable') return 'unreadable'
  }
  return 'failed'
}

/** Why the browser refuses `file` before sending it, or null when it may go. */
export function pickedRefusal(file: File): Refusal | null {
  if (!(LOGO_TYPES as readonly string[]).includes(file.type)) return 'type'
  if (file.size > MAX_LOGO_BYTES) return 'tooLarge'
  return null
}

/**
 * "Logo" in Ajustes › Gimnasio (#223): the gym's logo as it shows, round, beside its name,
 * and the way to upload, replace or remove it. A picked file is checked here first
 * (PNG, JPEG or WebP, up to 5 MB: never SVG, which can carry script), then framed in
 * the circle (`LogoCropper`) and sent with that square; the server cuts and resizes it.
 * Saved on its own, not with the form's "Guardar": every screen shows it at once.
 */
export function LogoSettings({ settings }: { settings: GymSettings }) {
  const queryClient = useQueryClient()
  const inputId = useId()
  const [picked, setPicked] = useState<{ file: File; url: string } | null>(null)
  const [crop, setCrop] = useState<LogoCrop | null>(null)
  const [refused, setRefused] = useState<Refusal | null>(null)
  const [done, setDone] = useState<'saved' | 'removed' | null>(null)

  // The picked file's address, given back once it is no longer shown.
  useEffect(() => () => {
    if (picked) URL.revokeObjectURL(picked.url)
  }, [picked])

  function settled(answer: GymSettings) {
    queryClient.setQueryData(gymSettingsQuery().queryKey, answer)
    // The shell, the student page and the tab show it at once.
    queryClient.setQueryData<MyRole>(myselfQuery().queryKey, (me) => me && { ...me, gym_logo: answer.logo })
    queryClient.setQueryData<Host>(hostQuery().queryKey, (host) =>
      host?.gym ? { gym: { ...host.gym, logo: answer.logo } } : host,
    )
  }

  const save = useSubmit({
    mutationFn: ({ file, square }: { file: File; square: LogoCrop }) => uploadLogo(file, square),
    onSuccess: (answer) => {
      settled(answer)
      setPicked(null)
      setDone('saved')
    },
    onError: (error) => setRefused(refusalOf(error)),
  })
  const remove = useSubmit({
    mutationFn: removeLogo,
    onSuccess: (answer) => {
      settled(answer)
      setDone('removed')
    },
  })

  function pick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // The same file picked again is a change too.
    event.target.value = ''
    if (!file) return
    setDone(null)
    save.reset()
    remove.reset()
    const why = pickedRefusal(file)
    setRefused(why)
    setPicked(why ? null : { file, url: URL.createObjectURL(file) })
    setCrop(null)
  }

  const cropped = useCallback((square: LogoCrop | null) => setCrop(square), [])
  const busy = save.isPending || remove.isPending

  return (
    <fieldset className="settings__card">
      <legend className="settings__legend">{copy.title}</legend>
      <p className="settings__hint">{copy.hint}</p>
      {picked ? (
        <>
          <p className="settings__hint">{copy.cropHint}</p>
          <LogoCropper src={picked.url} labels={{ frame: copy.frame, zoom: copy.zoom }} onChange={cropped} />
          <div className="logo-settings__actions">
            <Button
              variant="primary"
              disabled={busy || crop === null}
              busy={save.isPending}
              onClick={() => crop && save.mutate({ file: picked.file, square: crop })}
            >
              {save.isPending ? copy.saving : copy.save}
            </Button>
            <Button disabled={busy} onClick={() => setPicked(null)}>
              {copy.cancel}
            </Button>
          </div>
        </>
      ) : (
        <div className="logo-settings__current">
          <GymMark name={settings.name} logo={settings.logo} size="large" />
          <span className="settings__hint">{settings.logo ? copy.current : copy.none}</span>
        </div>
      )}
      {!picked && (
        <div className="logo-settings__actions">
          {/* The input sits before its label, which CSS shows as the button and outlines
              while the hidden input has focus, as in the proof upload. */}
          <input
            id={inputId}
            type="file"
            accept={LOGO_TYPES.join(',')}
            className="visually-hidden logo-settings__file"
            disabled={busy}
            onChange={pick}
          />
          <label htmlFor={inputId} className={buttonClass()}>
            {settings.logo ? copy.replace : copy.upload}
          </label>
          {settings.logo && (
            <Button variant="danger" disabled={busy} busy={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? copy.removing : copy.remove}
            </Button>
          )}
        </div>
      )}
      {refused && (
        <p className="settings__error" role="alert">
          {copy.refused[refused]}
        </p>
      )}
      {remove.isError && (
        <p className="settings__error" role="alert">
          {copy.removeFailed}
        </p>
      )}
      {done && (
        <p className="settings__done" role="status">
          {done === 'saved' ? copy.saved : copy.removed}
        </p>
      )}
    </fieldset>
  )
}
