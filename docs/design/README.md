# Design reference

`ui-design.html` is the owner's design file. Open it in a browser: its boards render
from bundled assets inside frames, so reading the file as text shows none of them.

## v3 (#199, November 2026)

Made with Lovable and Claude Design. It replaces v2 and is a **template, not a spec**:
it sets the visual language, and every feature the app already has stays, styled in
that language, whether or not a board shows it.

Boards: Admin · Resumen (the app's **Hoy**), Alumnos, Ficha de alumno, Pagos
(escritorio), Registrar pago (diálogo), Validar comprobante; Coach · Asistencia;
Alumno · Mi página; Sistema (tokens, temas, movimiento); and the three themes on a phone.

What changed from v2:

- **Three themes**, chosen per gym in Ajustes › Gimnasio › Tema: Bosque (green, the
  default), Océano (blue) and Volcán (red-brown). Each rewrites the same tokens, so
  components never know which they are in. The sign-in and join pages wear the gym's
  theme too.
- **Type:** Figtree for text (400, 500, 600) and Bricolage Grotesque 600 for titles,
  the mark and big figures, with tracking −0.02em. Figures are tabular. Both fonts are
  self-hosted, Latin only.
- **Shape:** cards at 20px with a soft shadow, controls at 10px.
- **Shell:** a dark sidebar (248px) on a desktop, and a dark top bar over the tab bar
  on a phone, with the gym's mark beside its name.
- **Colour roles:** a dark brand shade for titles and the primary button, a light
  "moss" fill for a secondary call to action, and a dark gradient for the one hero
  figure on a page.
- **Motion:** content rises into place once on a route change (opacity 0→1, 8px→0,
  0.5s, `cubic-bezier(0.2, 0.7, 0.2, 1)`); controls change colour only (150ms), with
  no scale and no bounce. Under reduced motion only opacity changes.

## Ajustes: one layout for every section (#241)

The boards draw no Ajustes, so the app sets its own pattern, and every section keeps it:

1. **Head.** One line on what the section holds and, for a section that lists things,
   its one primary button ("Nuevo plan", "Invitar"). Side by side from 1024px, the
   button at the end of the row; stacked on a phone.
2. **Groups.** One card per group, in one column at every width. A card's title comes
   first in display type, then its hint, then its fields (two to a row from 1024px) or
   its rows. A list is a card of rows; an item opens in place to edit.
3. **Buttons.** At the end of the form they act on: Cancelar, then the primary, at the
   end of the row from 1024px and across it on a phone. Gimnasio's and Graduación's
   Guardar stays in view on a desktop while the long form scrolls. Those two forms save
   the whole page and show only Guardar: there is nothing to cancel back to but the page
   as loaded, and Gimnasio's one Cancelar is in Tema's preview strip, for the theme
   being tried. A secondary action
   inside a card ("Agregar grado", "Nueva clase") is a secondary button at the card's
   start, as wide as its words.

Picking a theme in Gimnasio › Tema wears it at once on every screen, as a preview;
Guardar keeps it, and Cancelar or leaving Gimnasio puts the saved one back.

## Where the app differs from the file, and why

- **Success stays green in every theme.** In the file, Océano and Volcán move
  `--success` to the brand hue, so in Volcán "Pagado" is red like "Vencido". The
  timer's fight and rest colours (#187) stay green and red for the same reason: a
  status means the same thing in every gym.
- **Some shades are darker than the file's**, wherever the file's value fell under
  WCAG AA: an input's edge (3:1), the warning text, and danger text on its own tint.
- **Hoy keeps its name and its lists.** The board's "Resumen" has a month's takings
  and an "Activos" tile; Hoy keeps its four counters (overdue, to validate, classes
  without attendance, away 14 days) and its lists, in the board's tiles and cards.
- **Registrar pago stays inline.** The board draws it as a dialog; the app opens it in
  place. In the ficha it opens inside the payment card, now as a sunken well; in Pagos
  it opens in its own card under the header, as before. A dialog would change how it
  opens and closes, which this redesign leaves alone.
- **No "Registrar pago" in the shell or "Pagar" on every Alumnos row.** Both are new
  ways in, not a new look; they wait for the owner's say.
- **No counts on the filters.** The board's chips say "Vencidos 6"; the API does not
  count per filter, and the chips stay 44px tall, the app's touch target.
- **Overdue stays orange.** The board's "Vencidos" figure is red; in the app orange
  means overdue and nothing else, and red is a refusal.
- **The timer keeps its own screen.** Fight and rest fill it green and red in every
  theme (#187); only its set-up and the buttons around it take the theme.
- **Eyebrows stay small capitals.** The line over a page's title ("ADULTOS · 7 NOV",
  the gym's name on Hoy) is not on the boards; it keeps its small capitals, so a page's
  title and its context read apart. Section headings inside a page are display type.
- **The student's "Subir comprobante" stays the light button on the dark card.** The
  board fills it with moss; the app's buttons keep their four variants, and on a dark
  card the main one is the light one, as before.
- **Pages before sign-in wear the gym's theme on its own address.** The join form, the
  sign-in screen and the sign-in link's pages read the theme from the host
  (`/api/host`); on the shared address, which is no gym's, they wear the default or
  what the browser last wore.
- **Hex, not oklch.** The file writes oklch; `tokens.css` holds the same colours in
  hex, as the sign-in link's server-rendered pages (`backend/app/auth.py`) copy them.

## Contrast (WCAG 2.1 AA)

`frontend/src/components/controls.test.tsx` checks every pair in every theme.
Some of them:

| Pair | Needs | Bosque | Océano | Volcán |
|---|---|---|---|---|
| Body text on the page (`--color-text` on `--color-bg`) | 4.5:1 | 14.8 | 15.0 | 15.1 |
| Titles (`--color-heading` on `--color-bg`) | 4.5:1 | 11.5 | 11.7 | 12.1 |
| Secondary text on a well (`--color-text-muted` on `--color-surface-sunken`) | 4.5:1 | 5.1 | 5.1 | 5.1 |
| Faintest text (`--color-text-subtle` on `--color-bg`) | 4.5:1 | 4.9 | 4.9 | 5.0 |
| "Por validar" pill (`--color-accent` on `--color-accent-soft`) | 4.5:1 | 5.9 | 6.1 | 6.4 |
| Primary button (`--color-inverse-text` on `--color-inverse`) | 4.5:1 | 11.3 | 11.5 | 11.9 |
| Secondary text on the dark card (`--color-inverse-text-muted` on `--color-inverse`) | 4.5:1 | 8.1 | 8.2 | 8.5 |
| Moss button (`--color-moss-text` on `--color-moss`) | 4.5:1 | 8.3 | 8.4 | 8.2 |
| Selected sidebar item (`--color-sidebar-text` on `--color-sidebar-raised`) | 4.5:1 | 9.7 | 9.9 | 10.1 |
| "Pagado" pill (`--color-success-strong` on `--color-success-pill`) | 4.5:1 | 6.5 | 6.5 | 6.5 |
| Overdue text (`--color-warning` on `--color-surface`) | 4.5:1 | 5.4 | 5.4 | 5.3 |
| "Vence" pill (`--color-warning-strong` on `--color-warning-soft`) | 4.5:1 | 11.5 | 11.5 | 11.4 |
| "Vencido" / refused pill (`--color-danger` on `--color-danger-soft`) | 4.5:1 | 4.8 | 4.8 | 4.8 |
| An input's edge (`--color-border-input` on `--color-surface`) | 3:1 | 3.5 | 3.6 | 3.6 |
| Focus ring (`--color-focus` on `--color-bg`) | 3:1 | 4.4 | 4.5 | 4.7 |
