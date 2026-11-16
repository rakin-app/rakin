# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown==3.9"]
# ///
"""Builds rakin.app, the landing page (#343), into a folder Caddy serves as is.

    uv run site/build.py [--out DIR] [--fonts DIR]

Writes, under `--out` (default `site/dist`):

* `index.html`: `site/index.html`, with `site/styles.css` inlined, the dark
  lockup drawn inline and `CONTACT_EMAIL` filled in;
* `privacidad/index.html`: Rakin's own privacy notice,
  `docs/legal/aviso-de-privacidad-rakin.md`, rendered from its policy on;
* `img/`, the screenshots (`site/screenshots.py` takes them), `fonts/` and the
  icons and link preview the app also serves (`frontend/public/`).

`--fonts` is the `@fontsource` directory holding Figtree and Bricolage
Grotesque; by default, the one `npm install` puts under `frontend/node_modules`.
The web image runs this in its own stage (deploy/web.Dockerfile).
"""

import argparse
import html
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PUBLIC = ROOT / "frontend" / "public"
NOTICE = ROOT / "docs" / "legal" / "aviso-de-privacidad-rakin.md"
LOCKUP_DARK = ROOT / "docs" / "brand" / "lockup-dark.svg"

# TODO(#343): the alias the owner provides; one line to change.
CONTACT_EMAIL = "hola@rakin.app"

# The notice's links to its sibling documents go to the repo, where they are published.
DOCS_URL = "https://github.com/rakin-app/rakin/blob/main/docs/legal/"

FONTS = (
    "figtree/files/figtree-latin-400-normal.woff2",
    "figtree/files/figtree-latin-600-normal.woff2",
    "bricolage-grotesque/files/bricolage-grotesque-latin-600-normal.woff2",
)
ICONS = ("favicon.svg", "favicon.ico", "apple-touch-icon.png", "og-image.png")

NOTICE_PAGE = """<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Aviso de privacidad · Rakin</title>
    <meta name="description" content="Qué datos trata Rakin, para qué y cómo ejercer tus derechos." />
    <meta name="theme-color" content="#0f2e1b" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="icon" href="/favicon.ico" sizes="32x32" />
    <link rel="canonical" href="https://rakin.app/privacidad/" />
    <style>{{STYLES}}</style>
  </head>
  <body>
    <a class="skip" href="#contenido">Saltar al contenido</a>
    <header class="doc-header">
      <div class="wrap narrow"><a class="logo" href="/" aria-label="Rakin, inicio">{{LOCKUP_DARK}}</a></div>
    </header>
    <main id="contenido" class="doc">
      <div class="wrap narrow">
{{BODY}}
      </div>
    </main>
    <footer class="footer">
      <div class="wrap">
        <p>Rakin · Membresías y pagos para academias</p>
        <p><a href="/">Inicio</a> · <a href="mailto:{{CONTACT_EMAIL}}">{{CONTACT_EMAIL}}</a></p>
      </div>
    </footer>
  </body>
</html>
"""


def fill(template: str, **values: str) -> str:
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], template)


def lockup() -> str:
    """The dark lockup, inline: a decorative drawing inside a labelled link."""
    svg = LOCKUP_DARK.read_text().strip()
    return svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)


def notice_html() -> str:
    """The notice from its policy on, under the draft line it opens with.

    The text before the policy says where the notice is published, for the repo's
    readers; a visitor needs only the draft line and the policy itself."""
    text = NOTICE.read_text()
    draft = text.split("\n", 1)[0]
    if not draft.startswith("> "):
        raise SystemExit(f"build: {NOTICE.name} no longer opens with its draft line")
    policy = text.index("## Política de privacidad de Rakin")
    # One level up: the policy's title is the page's h1.
    body = draft + "\n\n" + text[policy + 1 :].replace("\n#", "\n")
    # Sibling documents, and the research one folder up, go to the repo on GitHub.
    body = re.sub(
        r"\]\(\.\./([\w-]+\.md)", r"](https://github.com/rakin-app/rakin/blob/main/docs/\1", body
    )
    body = re.sub(r"\]\(([\w-]+\.md)", rf"]({DOCS_URL}\1", body)
    return markdown.markdown(body, extensions=["tables", "toc"], output_format="html")


def build(out: Path, fonts: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "privacidad").mkdir(parents=True)
    styles = (SITE / "styles.css").read_text()
    common = {
        "STYLES": styles,
        "LOCKUP_DARK": lockup(),
        "CONTACT_EMAIL": html.escape(CONTACT_EMAIL),
    }

    (out / "index.html").write_text(fill((SITE / "index.html").read_text(), **common))
    (out / "privacidad" / "index.html").write_text(fill(NOTICE_PAGE, BODY=notice_html(), **common))

    shutil.copytree(SITE / "img", out / "img")
    (out / "fonts").mkdir()
    for font in FONTS:
        shutil.copy2(fonts / font, out / "fonts")
    for icon in ICONS:
        shutil.copy2(PUBLIC / icon, out)
    print(f"build: rakin.app in {out}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=SITE / "dist")
    parser.add_argument(
        "--fonts", type=Path, default=ROOT / "frontend" / "node_modules" / "@fontsource"
    )
    args = parser.parse_args()
    build(args.out, args.fonts)


if __name__ == "__main__":
    main()
