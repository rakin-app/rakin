# Rakin's logo

The mark is four tatami mats turning around a half mat, with a ring at the tile's
edge. The mat is where every class happens, whatever the discipline, so the mark
belongs to no single sport. The half mat in the centre is the accent, and the same
square ends the wordmark: «rakin▪». The ring keeps the tile's edge on dark
surfaces, and it is part of the mark everywhere.

Tagline: **Membresías y pagos para academias** (short form: «para academias»).
Name no sport in Rakin's copy.

The logo is Rakin's own and is not covered by the code's license; see
[TRADEMARK.md](../../TRADEMARK.md). A gym's own logo (#223) is a different thing,
and the two never merge.

## Files

| File | Use |
| --- | --- |
| `symbol.svg` | The symbol on its tile: app icons, avatars, anywhere square. |
| `symbol-maskable.svg` | Full bleed, mats inside the safe zone, no ring (the platform crops the edge): Android's adaptive icons. |
| `lockup.svg` | Symbol and wordmark, on light ground. |
| `lockup-dark.svg` | Symbol and wordmark, on dark ground. |
| `og-image.svg` | The 1200×630 link preview of rakin.app. |

`build.py` draws all of these, and the files the app serves from
`frontend/public/` (favicons, touch and PWA icons, the Open Graph image, the
email footer's logo). Change the geometry or a colour there, never in an output,
and rebuild:

```bash
cd frontend && npm install   # the fonts it outlines, from @fontsource
cd .. && uv run docs/brand/build.py
```

The wordmark is outlined from Bricolage Grotesque 600 with −0.02em tracking, so
the files need no font installed. In the app it is live text in the display
font, beside an inline copy of the symbol (`frontend/src/components/RakinLogo.tsx`),
so it takes the theme's colours.

## Colours

The logo wears Bosque, Rakin's own theme. In the app it follows the gym's theme
through the tokens; the files outside the app are always Bosque.

| Part | Token | Bosque |
| --- | --- | --- |
| Tile | `--color-inverse` | `#153c25` |
| Mats | `--color-inverse-text` | `#f5f6eb` |
| Centre mat, square on dark, ring | `--color-moss` | `#a0c79b` |
| Square on light | `--color-focus` | `#4e7f58` |
| Wordmark on light | `--color-heading` | `#153c25` |
| Wordmark on dark | `--color-sidebar-text` | `#e5ebd8` |

## Clear space and size

- **Clear space:** keep a margin of one mat's width (6/32 of the symbol's height)
  free around the symbol or the lockup.
- **Minimum size:** the symbol at 16 px, the size it was drawn to (every edge on a
  whole pixel there). The lockup at 20 px high, where the wordmark is still 16 px.
- On a dark surface use `lockup-dark.svg`, whose wordmark is light.

## Don'ts

- Don't redraw, stretch, rotate or mirror the mats: the pinwheel turns one way.
- Don't recolour the mark outside the three themes, drop its ring, or add stripes,
  shadows or gradients to it.
- Don't set the wordmark in another font, or end it with a round dot: the square
  is the centre mat.
- Don't put the lockup on a photo or a busy background; use the symbol on its tile.
- Don't combine it with a gym's logo into one mark: a gym's pages show the gym's
  logo, and Rakin appears beside it, as "a través de Rakin".
