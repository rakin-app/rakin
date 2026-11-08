import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom has no layout; the router's scroll restoration calls this on navigation.
window.scrollTo = () => {}

afterEach(() => {
  cleanup()
})
