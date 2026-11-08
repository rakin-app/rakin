/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The SPA and the API share one origin (docs/technical.md#architecture): in
// production Caddy serves both, in development Vite proxies the API paths to
// the FastAPI dev server. Either way the browser never makes a cross-origin
// request, so there is no CORS to configure.
const apiTarget = process.env.RAKIN_API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': apiTarget,
      '/healthz': apiTarget,
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
