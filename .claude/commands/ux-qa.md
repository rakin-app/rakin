---
description: UX QA — audits every screen against a fixed checklist on seed data, posts one dated comment on the standing "UX QA runs" issue, files new work as a few ux-qa batch tickets
argument-hint: [<standing-issue-url>]
---

You are now in UX QA mode.

You are a UI/UX designer reviewing Rakin as a whole, run as a worker. The PM dispatched you with `task-work ux-qa-<yyyymmdd> <standing issue URL> --auto`; the standing issue is "UX QA runs", [#341](https://github.com/rakin-app/rakin/issues/341). Your job is to run the checklist below on a local stack in this worktree and report. Refer to `.claude/gh-workflow.md` for the repo, the project and radio.

$ARGUMENTS

## Rules

- **Seed data only.** The stack runs in this worktree, on free ports, with `make seed` and the demo gyms below. Never point a browser at staging or production, and never import a real gym's sheet, so no screenshot ever holds a real member.
- **Screenshots stay local.** Save them under `.ux-qa/` in this worktree (git ignores it) and nowhere else. Never commit them, attach them to an issue or comment, or upload them anywhere. Describe what you saw in words.
- **No product code.** A run changes nothing under `backend/`, `frontend/` or `docs/` and opens no PR. Its output is one comment on the standing issue and a few tickets. A fix you are sure of goes in a ticket, not a commit.
- **No real data in what you post.** The repo and its issues are public: the PII guard ([docs/privacy-guard.md](../../docs/privacy-guard.md)) applies to your comment and tickets. Name screens and the seed's invented people only; no local paths. Bodies go in on stdin from a quote-delimited heredoc (`--body-file -` with `<<'BODY'`).

## Setup

Run it from this worktree. Compose names its containers and volumes after the worktree's directory, so this stack is separate from any other.

1. **Free ports.** `.env` is git-ignored; `PUBLIC_BASE_URL` must name the same port, or sign-in links point at 8080:
   ```bash
   free() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
   HTTP=$(free); PG=$(free)
   printf 'HTTP_PORT=%s\nPOSTGRES_PORT=%s\nPUBLIC_BASE_URL=http://localhost:%s\n' "$HTTP" "$PG" "$HTTP" > .env
   ```
2. **Stack and seed.** Academia Sur, the seeded gym, wears Bosque, the default theme:
   ```bash
   docker compose up -d --wait
   make seed
   ```
3. **One demo gym per theme**, empty, for the empty states and each theme. A gym's owner is the email given, so each signs in straight to its gym:
   ```bash
   for t in bosque oceano volcan; do
     docker compose run --rm api python -m app.gyms create --slug "demo-$t" \
       --name "Demo $t" --owner-email "owner.$t@example.com" --owner-name "Dueña $t"
   done
   docker compose exec -T postgres psql -U rakin -d rakin -c \
     "UPDATE gym SET theme = substring(slug from 6) WHERE slug LIKE 'demo-%'"
   ```
   To see a theme on real data too, switch Academia Sur's in Ajustes › Gimnasio › Tema as its owner, and back to Bosque when done.
4. **Sign-ins.** No email is sent locally: a link is written to the API's log. Ask for one and print it:
   ```bash
   . ./.env
   link() {
     curl -fsS -X POST -H 'content-type: application/json' -d "{\"email\":\"$1\"}" "$PUBLIC_BASE_URL/api/auth/link" >/dev/null
     sleep 1
     docker compose logs api --no-log-prefix | grep -o "$PUBLIC_BASE_URL/api/auth/callback?token=[^\"\\\\]*" | tail -1
   }
   link martin.fuentes@example.com     # owner, Academia Sur
   link sebastian.araya@example.com    # coach, Academia Sur
   link diego.morales@example.com      # student: /me
   link owner.oceano@example.com       # owner of an empty gym (and .bosque, .volcan)
   ```
   With Chrome DevTools, open each link in a page of its own `isolatedContext` (`owner`, `coach`, `student`, `oceano`, …), so the sessions live side by side, and press **Entrar**. Staff land on `/admin`, the student on `/me`.
5. **Viewports.** Set sizes with `emulate` (`viewport: "390x844x3,mobile,touch"`, `"1280x800x1"`), not `resize_page`: a window does not shrink below about 500px. Check `document.documentElement.scrollWidth` against `innerWidth` for sideways scroll.
6. **Afterwards**, `docker compose down -v` takes the stack and its data away.

## Screens

Every main screen, at **390×844** and **1280×800**. Keep this list current: when `frontend/src/router.tsx` or `SETTINGS_SECTIONS` in `frontend/src/routes/Settings.tsx` has a screen this list lacks, audit it and add it in the run's ticket for this file.

| Screen | Path | As |
|--------|------|----|
| Entrar, and the link's page | `/ingresar`, `/api/auth/callback?…` | signed out |
| Hoy, with data and empty | `/admin` | owner, coach, empty-gym owner (its setup checklist) |
| Alumnos, its filters and Exalumnos | `/admin/alumnos` | owner, coach |
| Nuevo alumno, and a former student | `/admin/alumnos/nuevo` | owner |
| Importar: Alumnos, Grados, Pagos tabs, recent imports and Deshacer importación | `/admin/alumnos/importar` (try `backend/app/seed/demo_import.csv`) | owner |
| Ficha: plan, data, family, grades and Grados anteriores, history, Pagos anteriores, custom fields, the Libro and Corregir | `/admin/alumnos/<id>` | owner, coach |
| Clases | `/admin/clases` | owner, coach |
| A class: roster and attendance | `/admin/clases/<id>` | coach |
| The class timer | `/admin/clases/<id>/timer` | coach |
| Pagos and the Libro | `/admin/pagos` | owner |
| Validar comprobante | `/admin/pagos/comprobantes` | owner |
| Cobros extra, a new one, one cobro | `/admin/pagos/cobros`, `…/nuevo`, `…/<id>` | owner |
| Ajustes, every section: Gimnasio (theme, logo), Planes, Programas, Horario, Etiquetas, Bloques, Graduación, Campos, Equipo, Inscripción, Cuenta | `/admin/ajustes/<section>` | owner |
| Mi página: plans, paying and sending a proof, grades | `/me` | student |
| The join form | `/unirse/<token>` (the link from Ajustes › Inscripción) | signed out |
| Política de privacidad | `/privacidad` | signed out |
| Not found | any unknown path | signed in |

## Checklist

Read `docs/design/ui-design.html` (the design reference), `frontend/src/styles/tokens.css` and `global.css`, and the components in `frontend/src/components` first, and note where screens diverge from them. Weigh every finding against the real users: a gym owner on a phone between classes, a coach at the mat with one hand, students and parents opening a link from WhatsApp.

1. **Layout**: every screen at 390×844 and 1280×800, and holding from 360 to 1440 wide with no sideways scroll; long Spanish names, large amounts in CLP and empty data without breaking.
2. **Themes**: Bosque, Océano and Volcán on the main screens. Contrast holds in each; nothing is hardcoded to one theme's colours; the Rakin logo and a gym's own logo sit well together.
3. **Accessibility**, WCAG 2.1 AA: text and control contrast, tap targets of 44px and up, focus order and a visible focus, labels on every control, headings and landmarks a screen reader can follow.
4. **Copy**: Spanish microcopy, buttons, empty states and errors: plain, consistent, in the gym's words.
5. **Design system**: spacing, type scale, control heights, radii, shadows and colours against the design reference and the tokens; buttons, inputs, selects, chips, cards, pills and empty states as one set; one-off styles where a token or component exists; duplicated or dead CSS.
6. **States**: loading, errors, offline (the app is a PWA: `emulate` with `networkConditions: "Offline"`), disabled and confirmation states, and motion (with `prefersReducedMotion: "reduce"` too).
7. **Sport-agnostic look**: imagery, icons, illustrations and empty states that read as martial arts only. A climbing gym or a rowing club should not feel like a guest in a dojo app. Flag only what is visual; wording is the copy item's.

Use the design skills on the screenshots:
- `design:design-critique` for hierarchy, consistency and usability;
- `design:accessibility-review` for item 3;
- `design:ux-copy` for item 4;
- `design:design-system` for item 5.

## Output

1. **Before filing**, read what is already open and what earlier runs said:
   ```bash
   gh issue list --repo rakin-app/rakin --label ux-qa --state open --limit 100
   gh issue view 341 --repo rakin-app/rakin --comments
   ```
   A problem that has an open ticket is linked, not filed again.
2. **One comment on the standing issue**, headed with the date and the commit audited (`git rev-parse --short HEAD`):
   - the top problems ranked by impact, each with the screen, what is wrong and the proposed fix, linking its ticket;
   - what earlier runs found that is now fixed;
   - what is still open from earlier runs;
   - a short note per theme.
   ```bash
   gh issue comment 341 --repo rakin-app/rakin --body-file - <<'BODY'
   ## Run <n>: <yyyy-mm-dd>, commit <sha>
   …
   BODY
   ```
3. **New work as a few batch tickets**, each buildable in one PR, with acceptance criteria and the before and after it expects, labelled `ux-qa` and `area:admin` or `area:student`. File them before the comment, so it can link them.
4. **The run list**: add the run's row (number, date, commit, link to the comment) to the table in #341's body.
5. **Report back** to the PM, then clean up:
   ```bash
   radio send --to pm --intent ux-qa-run-complete --issue 341 <<'BODY'
   UX QA run <n> posted: <comment url>. Tickets: #…, #…
   BODY
   docker compose down -v
   task-done --remove-worktree
   ```
   If `radio send` does not say `delivered` or `queued`, keep the tab open and say so instead of running `task-done`.
