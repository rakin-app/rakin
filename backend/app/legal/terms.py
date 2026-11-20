"""The two texts a gym accepts, rendered for that gym (#499).

`load` reads `terminos-de-servicio.md` and `terminos-de-encargo.md` from the legal
directory (`legal_dir`): the image's `/app/legal`, which `backend/Dockerfile` copies
from `docs/legal/` through the `legal` build context, or the repo's `docs/legal/` in
development and tests. Each becomes a `Text`: its version, its body and its
`## Cambios de versión` section, split off the body into one entry per version.

Of the Markdown, what a gym reads is the contract, and only it: the draft line the
file opens with goes, and so do the drafting notes for the lawyer and for later work
(`` `[ABOGADO: …]` ``, `` `[PENDIENTE: …]` ``, as `site/build.py` strips them).

A blank keeps its `[…]` form in the Markdown, so the file still reads well on
GitHub. `BLANKS` maps each exact label to a field, filled by the app (the gym's name
and slug) or by the titular on the page (`app.schemas.terms.TermsFilled`). Each is
rendered as `<span class="legal-blank" data-blank="<field>">`, holding the value,
HTML-escaped, or the label while the field is still empty, so the page can fill
them as the titular types without ever parsing what they type as markup: the text
they read is the one the server renders on acceptance, and hashes. A label not in
`BLANKS` fails the render; `[...]`, a quotation's cut, stays as it is.

Links between sections become anchors within the page, prefixed with the text's own
(`servicio-`, `encargo-`), since both are on one page; links to other documents go to
the repo on GitHub, where they are published.

The acceptance block (`acceptance_block`) is not part of the text: it describes the
acceptance of that text, and goes under it on the copy the titular downloads and is
emailed (`copy_document`).
"""

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
from markdown.extensions.toc import TocExtension, slugify_unicode

from app.settings import Settings

SERVICE = "service"
PROCESSOR = "processor"
KEYS = (SERVICE, PROCESSOR)

FILES = {SERVICE: "terminos-de-servicio.md", PROCESSOR: "terminos-de-encargo.md"}
TITLES = {SERVICE: "Términos de servicio", PROCESSOR: "Términos de encargo"}
# What each text's anchors start with, so the two on one page do not collide.
PREFIXES = {SERVICE: "servicio", PROCESSOR: "encargo"}

IMAGE_DIR = Path("/app/legal")
REPO_DIR = Path(__file__).resolve().parents[3] / "docs" / "legal"
REPO_URL = "https://github.com/rakin-app/rakin/blob/main/"

# Each blank's exact label in the texts, and the field that fills it.
BLANKS = {
    "Razón social del gimnasio": "legal_name",
    "RUT del gimnasio": "rut",
    "Nombre del gimnasio": "gym_name",
    "slug": "slug",
    "domicilio del gimnasio": "address",
    "nombre del representante": "representative",
    # Clause 12's contact for breaches, and the second one, with another email.
    "nombre y cargo": "contact_name",
    "correo": "contact_email",
    "teléfono": "contact_phone",
    "segundo contacto": "second_contact",
}
# What the app fills in; the titular fills the rest.
APP_FIELDS = frozenset({"gym_name", "slug"})

# A label in brackets, not a link's text (`[…](…)`) nor a reference (`[…][…]`).
BLANK = re.compile(r"\[([^\[\]\n]+)\](?![(\[])")
# `[...]`: a cut in a quotation, never a blank.
ELLIPSIS = "..."
# The drafting notes, in the texts' own markup (docs/legal/README.md), as
# `site/build.py`'s `NOTES` matches them.
NOTES = re.compile(r" ?`\[(?:ABOGADO|PENDIENTE):.*?\]`")
DRAFT = re.compile(r"\A> \*\*BORRADOR[^\n]*\n+")
VERSION = re.compile(r"\*\*Versión: (\d{4}-\d{2}-\d{2})\.\*\*")
CHANGES = "\n## Cambios de versión\n"
CHANGE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\n", re.MULTILINE)
ANNEX_A = "\n## Anexo A"

CHILE = ZoneInfo("America/Santiago")
_MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


class LegalTextError(ValueError):
    """A text the app cannot show as it is: a blank it does not know, a missing line."""


@dataclass(frozen=True)
class Text:
    key: str
    title: str
    version: str
    # The contract, Markdown, its blanks still in brackets.
    body: str
    # Each version's changes, Markdown, the latest first.
    changes: tuple[tuple[str, str], ...]


def legal_dir(settings: Settings) -> Path:
    """Where the texts are: `LEGAL_DIR`, else the image's, else the repo's."""
    if settings.legal_dir is not None:
        return settings.legal_dir
    return IMAGE_DIR if IMAGE_DIR.is_dir() else REPO_DIR


def parse(key: str, source: str) -> Text:
    """`source`, the Markdown of the text `key`, as the app shows it."""
    found = VERSION.search(source)
    if found is None:
        raise LegalTextError(f"{FILES[key]} has no **Versión: YYYY-MM-DD.** line")
    body = NOTES.sub("", DRAFT.sub("", source, count=1))
    changes: list[tuple[str, str]] = []
    if CHANGES in body:
        body, log = body.split(CHANGES, 1)
        parts = CHANGE.split(log)
        # parts: what precedes the first heading, then each version and its text.
        changes = [
            (version, text.strip()) for version, text in zip(parts[1::2], parts[2::2], strict=True)
        ]
    if re.search(r"ABOGADO|PENDIENTE|BORRADOR", body):
        raise LegalTextError(f"a drafting note in {FILES[key]} is not in the `[ABOGADO: …]` form")
    for label in BLANK.findall(body):
        if label != ELLIPSIS and label not in BLANKS:
            raise LegalTextError(f"{FILES[key]} has a blank the app does not know: [{label}]")
    return Text(key, TITLES[key], found.group(1), body.strip() + "\n", tuple(changes))


@cache
def _load(directory: Path) -> dict[str, Text]:
    return {key: parse(key, (directory / FILES[key]).read_text()) for key in KEYS}


def load(settings: Settings) -> dict[str, Text]:
    """Both texts, read once per directory."""
    return _load(legal_dir(settings))


def _links(source: str) -> str:
    """Links to other documents, to the repo on GitHub; those within the text, kept."""

    def target(match: re.Match[str]) -> str:
        url = match.group(1)
        if url.startswith(("#", "http://", "https://", "mailto:")):
            return match.group(0)
        path = (Path("docs/legal") / url.split("#")[0]).as_posix()
        # `../legal-research.md` is `docs/legal-research.md`, `../../X` the repo's.
        parts: list[str] = []
        for part in path.split("/"):
            if part == "..":
                parts.pop()
            else:
                parts.append(part)
        anchor = url[len(url.split("#")[0]) :]
        return f"]({REPO_URL}{'/'.join(parts)}{anchor})"

    return re.sub(r"\]\(([^)\s]+)\)", target, source)


def _prefixed(rendered: str, prefix: str) -> str:
    """`rendered` with its ids, and the links to them, under `prefix`."""
    rendered = re.sub(r' id="([^"]+)"', rf' id="{prefix}-\1"', rendered)
    return re.sub(r' href="#([^"]+)"', rf' href="#{prefix}-\1"', rendered)


def _markdown(source: str) -> str:
    return markdown.markdown(
        source,
        extensions=["tables", TocExtension(slugify=slugify_unicode)],
        output_format="html",
    )


def blank_span(field: str, value: str) -> str:
    """How a blank is rendered: `value` escaped, in a span the page can find."""
    return f'<span class="legal-blank" data-blank="{field}">{html.escape(value)}</span>'


def render(text: Text, values: Mapping[str, str | None]) -> str:
    """`text` as HTML, each blank filled with its field's value in `values`, or showing
    its label while that is None or missing."""
    tokens: dict[str, str] = {}

    def token(match: re.Match[str]) -> str:
        label = match.group(1)
        if label == ELLIPSIS:
            return match.group(0)
        field = BLANKS[label]
        value = values.get(field)
        name = f"RKNBLANK{len(tokens)}RKN"
        tokens[name] = blank_span(field, f"[{label}]" if value is None else value)
        return name

    rendered = _prefixed(_markdown(BLANK.sub(token, _links(text.body))), PREFIXES[text.key])
    # Links are rendered by now, so a bracket left is a blank `BLANK` did not take.
    left = [b for b in re.findall(r"\[[^\]]*\]", rendered) if b != f"[{ELLIPSIS}]"]
    if left:
        raise LegalTextError(f"{FILES[text.key]} renders with brackets left: {', '.join(left)}")
    for name, span in tokens.items():
        rendered = rendered.replace(name, span)
    return rendered


def render_changes(text: Text, since: str | None) -> list[tuple[str, str]]:
    """The changes of every version after `since` (all, with None), the latest first,
    each as HTML."""
    return [
        (version, _prefixed(_markdown(_links(change)), PREFIXES[text.key]))
        for version, change in text.changes
        if since is None or version > since
    ]


def subprocessors(text: Text) -> list[str]:
    """The subencargados the Anexo A of the Términos de encargo names, in its order."""
    if ANNEX_A not in text.body:
        raise LegalTextError(f"{FILES[text.key]} has no Anexo A")
    annex = text.body.split(ANNEX_A, 1)[1].split("\n## ", 1)[0]
    rows = [line for line in annex.splitlines() if line.startswith("|")]
    # The header and its rule are the first two rows.
    return [row.strip("|").split("|")[0].strip() for row in rows[2:]]


def spanish_list(items: Sequence[str]) -> str:
    """`a, b y c`."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} y {items[-1]}"


def declarations(legal_name: str, names: Sequence[str]) -> dict[str, str]:
    """What each checkbox says, as the titular ticks it (#500, requirement 12): in the
    gym's name, the representation it declares, and each subencargado by name."""
    return {
        SERVICE: (
            f"Acepto los Términos de servicio en nombre de {legal_name},"
            " y declaro que puedo representarla."
        ),
        PROCESSOR: (
            f"Acepto los Términos de encargo en nombre de {legal_name}, incluida la"
            f" autorización a cada subencargado del Anexo A: {spanish_list(names)}."
        ),
    }


def chile_time(value: datetime) -> str:
    """An instant as Chile reads it: 20 de noviembre de 2026, 14:35."""
    local = value.astimezone(CHILE)
    return f"{local.day} de {_MESES[local.month - 1]} de {local.year}, {local:%H:%M}"


def acceptance_block(
    *,
    name: str,
    legal_name: str,
    accepted_at: datetime,
    email: str,
    version: str,
    sha256: bytes,
) -> str:
    """Who accepted a text, for whom, when, with which address, and its fingerprint:
    what goes under the text on its copy (#500, question 5)."""
    return (
        '<p class="legal-acceptance"><strong>Aceptado electrónicamente</strong>'
        f" por {html.escape(name)}, en representación de {html.escape(legal_name)},"
        f" el {chile_time(accepted_at)}, hora de Chile, con el correo {html.escape(email)}."
        f" Versión {html.escape(version)}. Huella SHA-256 del texto aceptado:"
        f" <code>{sha256.hex()}</code>.</p>"
    )


@dataclass(frozen=True)
class Accepted:
    """One acceptance in the app, as its copy shows it."""

    gym_name: str
    name: str
    legal_name: str
    email: str
    accepted_at: datetime
    service_version: str
    processor_version: str
    service_html: str
    processor_html: str
    service_sha256: bytes
    processor_sha256: bytes
    service_declaration: str
    processor_declaration: str


COPY_STYLE = """
body { margin: 0; background: #f4f4f5; color: #18181b;
  font: 16px/1.6 system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
main { max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem; background: #fff; }
h1 { font-size: 1.6rem; line-height: 1.25; }
h2 { font-size: 1.25rem; margin-top: 2rem; }
h3 { font-size: 1.05rem; }
table { border-collapse: collapse; width: 100%; font-size: .95rem; }
th, td { border: 1px solid #d4d4d8; padding: .4rem .5rem; text-align: left; vertical-align: top; }
code { font-size: .9em; word-break: break-all; }
hr { border: 0; border-top: 1px solid #d4d4d8; margin: 2.5rem 0; }
.legal-acceptance { margin-top: 2rem; padding: 1rem; border: 1px solid #a1a1aa;
  border-radius: 6px; background: #fafafa; }
.legal-declaration { font-style: italic; }
@media print { body { background: #fff; } main { max-width: none; padding: 0; } }
""".strip()


def copy_document(accepted: Accepted) -> str:
    """The copy of an acceptance (#500, requirements 13 and 14): a page of its own,
    with both texts exactly as stored, each followed by what its checkbox said and its
    acceptance block. What the email attaches and the admin downloads."""
    parts = []
    for title, body, declaration, version, digest in (
        (
            TITLES[SERVICE],
            accepted.service_html,
            accepted.service_declaration,
            accepted.service_version,
            accepted.service_sha256,
        ),
        (
            TITLES[PROCESSOR],
            accepted.processor_html,
            accepted.processor_declaration,
            accepted.processor_version,
            accepted.processor_sha256,
        ),
    ):
        block = acceptance_block(
            name=accepted.name,
            legal_name=accepted.legal_name,
            accepted_at=accepted.accepted_at,
            email=accepted.email,
            version=version,
            sha256=digest,
        )
        parts.append(
            f'<section aria-label="{html.escape(title)}">\n{body}\n'
            f'<p class="legal-declaration">Casilla marcada: «{html.escape(declaration)}»</p>\n'
            f"{block}\n</section>"
        )
    gym = html.escape(accepted.gym_name)
    return (
        '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>Términos aceptados por {gym}</title>\n<style>{COPY_STYLE}</style>\n"
        "</head>\n<body>\n<main>\n"
        f"<p>Copia de los términos que {html.escape(accepted.name)} aceptó en Rakin"
        f" para {gym} el {chile_time(accepted.accepted_at)}, hora de Chile.</p>\n"
        + "\n<hr>\n".join(parts)
        + "\n</main>\n</body>\n</html>\n"
    )
