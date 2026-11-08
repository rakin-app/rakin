# Rakin frontend

One Vite SPA serving two route trees: `/admin/*` for gym owners and coaches,
`/me/*` for students. React, TanStack Query, TanStack Router, TypeScript. See
[ADR 0001](../docs/adr/0001-frontend-framework.md) for why.

## Develop

Requires Node 22.22+ or 24.15+ (see `engines` in `package.json`).

```sh
npm ci
npm run dev        # http://localhost:5173
```

The dev server proxies `/api` and `/healthz` to the backend at
`http://localhost:8000` (override with `RAKIN_API_URL`), so the SPA and the API
share an origin as they do in production behind Caddy.

## Check

```sh
npm run typecheck
npm run lint
npm test
npm run build      # outputs dist/
```

## Conventions

- **Strings:** every user-facing string goes in `src/i18n/es.ts`. ESLint rejects
  inline JSX text.
- **Styles:** use the design tokens in `src/styles/tokens.css` (extracted from
  `docs/design/ui-design.html`), not raw colours or sizes.
- **API:** call the backend through `apiFetch` in `src/api/client.ts` with a
  path starting with `/`, and wrap it in a TanStack Query `queryOptions`.
- **Routes:** add routes in `src/router.tsx` under the `admin` or `me` tree.
