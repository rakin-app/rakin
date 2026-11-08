# ADR 0001: React, TanStack Query and TanStack Router for the SPA

- **Status:** accepted
- **Date:** 2026-11-08
- **Issue:** #3

## Context

The frontend is one Vite SPA with two route trees: `/admin` for owners and
coaches, `/me` for students reached by magic link
([technical design](../technical.md#architecture)). It talks to a FastAPI
backend on the same origin through TanStack Query, ships as a PWA through
`vite-plugin-pwa`, and keeps every user-facing string in one Spanish i18n file.

TanStack Query supports both React and Vue, so the framework was open. The
choice also fixes the router, since the router is where the two trees, their
layout shells and their data loading meet.

## Decision

**React** (19), with **TanStack Query** for server state and **TanStack
Router** for routing, in TypeScript.

### Why React over Vue

- The largest pool of contributors for an open-source project that wants
  outside help: most people who might send a PR to a small AGPL app know React.
- TanStack Query, TanStack Router and `vite-plugin-pwa` are all developed
  React-first; their docs and examples assume it.
- The PM decision on #3 settled it; Vue is no longer under consideration.

### Why TanStack Router over React Router

- **Type-checked paths.** A `<Link to="/admin/pagos">` to a route that does not
  exist, or with missing params, fails `tsc`. With two route trees and a nav in
  each, broken links should be a build error, not a 404 in a gym.
- **Built for TanStack Query.** The router context carries the `QueryClient`,
  so a route loader can `ensureQueryData` and a component can read the same
  query with `useSuspenseQuery`: one cache and no request waterfall between
  route and component. React Router's loaders keep their own data and
  revalidation model alongside Query's.
- **Validated search params.** The ledger and member lists filter by period,
  status and plan. TanStack Router parses and types search params per route;
  React Router hands back a raw `URLSearchParams`.

The cost is a smaller community than React Router, and a less familiar API for
new contributors. We accept it for the type safety above.

## Consequences

- The SPA lives in `frontend/`, separate from `backend/`.
- Routes are defined in code in `frontend/src/router.tsx`, without the file-based
  route generator, to avoid a codegen step while the tree is small. Revisit
  when the tree outgrows one file.
- Requests go through `apiFetch` in `frontend/src/api/client.ts`, which accepts
  same-origin paths only and sends the session cookie. The Vite dev server
  proxies `/api` and `/healthz` to the backend, so development is same-origin
  too and the API needs no CORS configuration.
- ESLint fails on any inline JSX text (`react/jsx-no-literals`) and on literal
  `aria-label`, `title`, `alt` or `placeholder` values, so copy has to go
  through `frontend/src/i18n/es.ts`.
- Fonts (Inter, Space Grotesk) are bundled from `@fontsource` packages rather
  than loaded from Google Fonts, so the PWA works offline and student visits do
  not hit a third party.
