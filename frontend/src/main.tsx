// Latin only: Spanish needs nothing past it, and the files stay small (#199).
import '@fontsource/figtree/latin-400.css'
import '@fontsource/figtree/latin-500.css'
import '@fontsource/figtree/latin-600.css'
import '@fontsource/figtree/latin-700.css'
import '@fontsource/bricolage-grotesque/latin-600.css'
import './styles/tokens.css'
import './styles/global.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createQueryClient } from './api/queryClient'
import { App } from './App'
import { createAppRouter } from './router'
import { applyTheme, storedTheme } from './theme'

// The theme the last visit wore, before the first paint; the gym's answer follows.
applyTheme(storedTheme())

const queryClient = createQueryClient()
const router = createAppRouter({ queryClient })

const root = document.getElementById('root')
if (!root) throw new Error('#root element missing from index.html')

createRoot(root).render(
  <StrictMode>
    <App queryClient={queryClient} router={router} />
  </StrictMode>,
)
