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
  `docs/design/ui-design.html`), not raw colours or sizes. Text fields use
  `--text-input` (16px, or iOS Safari zooms on focus), every control is at least
  `--control-height` (44px), errors and destructive actions use `--color-danger`,
  and `--color-warning` means overdue and nothing else.
- **Themes:** a gym wears Bosque, Océano or Volcán (#199), set as `data-theme` on
  `<html>` by `src/theme.ts` and `App`'s `GymTheme`. Each theme writes the same
  `--color-*` names in `tokens.css`, so a component never knows which it is in and
  never names a colour itself. A new colour token goes in all three blocks, and
  `components/controls.test.tsx` holds each to WCAG AA. Success and the timer's
  fight and rest colours stay the same in every theme.
- **The gym's logo:** `GymMark` (#223) is the gym's mark wherever it is named: its
  logo in a circle, sized by `srcset` from the API's 64, 128 and 512 px files
  (`src/logo.ts`), or its initials on the accent when it has none or the file fails, the
  same size either way. It is decorative (`alt=""`): the name is always beside it.
  Ajustes › Gimnasio uploads it (`LogoSettings`, framed in `LogoCropper`), and on a
  gym's own address `App`'s `GymTabIcon` puts it in the tab (`setTabIcon`).
- **Motion:** a control changes colour only (`--duration-fast`); a page rises in on
  a route change (`useRise` in `src/motion.ts`); a `role="status"` or `"alert"`
  message fades in. Under `prefers-reduced-motion` only opacity changes.
- **Controls:** screens build on the shared components in `src/components/`, never
  a per-screen `*__button`, `*__input`, `*__chip` or `*__pill` class. A screen's CSS
  only places them (margins, grid, width).
  - `Button`: `variant` primary (the theme's dark shade; one per screen) / secondary / ghost /
    danger (deletes, removes, refuses), `size` md (44) / lg (52), `fullWidth`,
    `icon` (square, needs an `aria-label`), `inverse` (on a dark surface). A `Link`
    or file-input `label` that looks like a button takes `buttonClass({ … })`.
  - `Field` with `Input`, `Select`, `Textarea`: label, hint and error wired with
    `aria-describedby` / `aria-invalid`. `FieldError` for an error on its own.
  - `Chip` in a `ChipGroup` for filters; `SegmentedControl` for a few views of
    one thing.
  - `StatusPill`: a status, never a control. Its `status` picks the tone from the
    one shared mapping in `StatusPill.tsx`; the accent is "por validar" only, orange
    is overdue only, red is a refused payment.
  - `Card`, `SectionHeader`, `ListRow` / `listRowClass`, `EmptyState`.
  - `PageContainer`: a screen's header and body, up to `--content-wide` (1280px) and
    centred, with the breakpoint's side padding; a `PageHeader` inside it lines up
    with the body. `Grid`: one column
    below 1024px, then `columns` 2 (default) or 3. `useWide()` is true from that
    same 1024px, for what a screen shows (and fetches) only on a desktop.
- **API:** call the backend through `apiFetch` in `src/api/client.ts` with a
  path starting with `/`, and wrap it in a TanStack Query `queryOptions`.
- **Routes:** add routes in `src/router.tsx` under the `admin` or `me` tree.
