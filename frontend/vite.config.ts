/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// The SPA and the API share one origin (docs/technical.md#architecture): in
// production Caddy serves both, in development Vite proxies the API paths to
// the FastAPI dev server. Either way the browser never makes a cross-origin
// request, so there is no CORS to configure.
const apiTarget = process.env.RAKIN_API_URL ?? 'http://localhost:8000'

// The sign-in link's pages are plain HTML from the API (backend/app/auth.py), with no
// bundle to find Vite's fingerprinted fonts in: they load these copies, under names
// that never change, from /fonts.
const FIXED_FONTS = [
  '@fontsource/figtree/files/figtree-latin-400-normal.woff2',
  '@fontsource/figtree/files/figtree-latin-600-normal.woff2',
  '@fontsource/bricolage-grotesque/files/bricolage-grotesque-latin-600-normal.woff2',
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

// The installed app (#68): a service worker that keeps the app shell (the HTML, the
// bundle, its fonts), so a screen opens with no signal, as the Clase screen must (#44).
// Nothing from the API is kept: /api/* and /healthz always go to the network, the
// sign-in link's pages and cookies included, and a screen's data and a save made
// offline stay React Query's and `localStorage`'s (#231).
//
// A page is asked of the network first, so a deploy is on screen at the next load:
// the kept shell answers only when the network fails. Workbox allows no timeout on a
// network-only route, and a route that times out to a cache per page would keep pages
// naming bundles the next worker deletes. The new
// worker takes over as soon as it is installed and drops the old shell, so no release
// waits behind one. The manifest stays `public/site.webmanifest`.
function installedApp() {
  return VitePWA({
    registerType: 'autoUpdate',
    injectRegister: 'script',
    manifest: false,
    workbox: {
      globPatterns: ['**/*.{js,css,html,woff2,svg,ico}'],
      // The sign-in link's pages load these from the API's HTML, never offline.
      globIgnores: ['fonts/**'],
      navigateFallback: null,
      cleanupOutdatedCaches: true,
      // The tab the app was first opened in is covered too, not only from its next load.
      clientsClaim: true,
      runtimeCaching: [
        {
          urlPattern: ({ request, url }) =>
            request.mode === 'navigate' && !url.pathname.startsWith('/api/') && url.pathname !== '/healthz',
          handler: 'NetworkOnly',
          options: { precacheFallback: { fallbackURL: 'index.html' } },
        },
      ],
    },
  })
}

export default defineConfig({
  plugins: [react(), fixedFonts(), installedApp()],
  // lightningcss, for `@custom-media`: the breakpoints live in `src/styles/media.css` alone.
  css: {
    transformer: 'lightningcss',
    lightningcss: { drafts: { customMedia: true } },
  },
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
    // The breakpoints, which `components/Layout.tsx` reads as text; other CSS stays stubbed.
    css: { include: [/styles\/media\.css/] },
  },
})
