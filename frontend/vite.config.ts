/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// The SPA and the API share one origin (docs/technical.md#architecture): in
// production Caddy serves both, in development Vite proxies the API paths to
// the FastAPI dev server. Either way the browser never makes a cross-origin
// request, so there is no CORS to configure.
const apiTarget = process.env.RAKIN_API_URL ?? 'http://localhost:8000'

// The sign-in link's pages are plain HTML from the API (backend/app/auth.py), with no
// bundle to find Vite's fingerprinted fonts in: they load these copies, under names
// that never change, from /fonts.
const FIXED_FONTS = [
  '@fontsource/inter/files/inter-latin-400-normal.woff2',
  '@fontsource/inter/files/inter-latin-600-normal.woff2',
  '@fontsource/space-grotesk/files/space-grotesk-latin-700-normal.woff2',
]

function fixedFonts(): Plugin {
  const require = createRequire(import.meta.url)
  const files = new Map(
    FIXED_FONTS.map((spec) => [`fonts/${spec.split('/').pop()}`, require.resolve(spec)]),
  )
  return {
    name: 'rakin-fixed-fonts',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const file = files.get((req.url ?? '').split('?')[0]!.slice(1))
        if (!file) return next()
        res.setHeader('Content-Type', 'font/woff2')
        res.end(readFileSync(file))
      })
    },
    generateBundle() {
      for (const [fileName, file] of files) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(file) })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), fixedFonts()],
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
