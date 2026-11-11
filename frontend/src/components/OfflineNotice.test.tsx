import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../api/client'
import { useSubmit, type OfflinePolicy } from '../api/submit'
import { es } from '../i18n/es'
import { OfflineNotice } from './OfflineNotice'

const copy = es.offline

function stubFetch() {
  const fetch = vi.fn<typeof globalThis.fetch>(
    async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
  )
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const LABEL = 'Guardar'

function Form({ offline }: { offline?: OfflinePolicy }) {
  const save = useSubmit({ offline, mutationFn: () => apiFetch('/api/people', { method: 'POST', body: '{}' }) })
  return (
    <button type="button" onClick={() => save.mutate()}>
      {LABEL}
    </button>
  )
}

function renderForm(offline?: OfflinePolicy) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <Form offline={offline} />
      <OfflineNotice />
    </QueryClientProvider>,
  )
}

// The live region, there when it has nothing to say too.
const notice = () => document.querySelector('[aria-live="polite"].offline-notice')

function setOnline(online: boolean) {
  act(() => {
    onlineManager.setOnline(online)
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  onlineManager.setOnline(true)
})

describe('OfflineNotice', () => {
  it('says nothing while online', async () => {
    stubFetch()
    renderForm()
    await userEvent.click(screen.getByRole('button', { name: LABEL }))
    expect(notice()).toBeEmptyDOMElement()
  })

  it('says a submission paused offline will be saved, until it is', async () => {
    const fetch = stubFetch()
    renderForm()
    setOnline(false)
    await userEvent.click(screen.getByRole('button', { name: LABEL }))

    expect(await screen.findByText(copy.waiting)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()

    setOnline(true)
    await waitFor(() => expect(notice()).toBeEmptyDOMElement())
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('says a refused submission was not saved, while still offline', async () => {
    const fetch = stubFetch()
    renderForm('refuse')
    setOnline(false)
    await userEvent.click(screen.getByRole('button', { name: LABEL }))

    expect(await screen.findByText(copy.refused)).toBeInTheDocument()
    expect(screen.queryByText(copy.waiting)).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()

    setOnline(true)
    expect(notice()).toBeEmptyDOMElement()
    expect(fetch).not.toHaveBeenCalled()
  })
})
