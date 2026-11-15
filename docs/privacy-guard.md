# Privacy guard

The repo, its issues, PRs and the project board are public. The pilot gym's real members live on staging. The privacy guard ([#302](https://github.com/rakin-app/rakin/issues/302)) is a set of checks that stop a real person's name, RUT, phone or email from reaching GitHub through a commit, a PR or issue body, or a comment. They apply to humans and agents alike.

Every check runs one script, [`scripts/pii_guard.py`](../scripts/pii_guard.py). It uses only the standard library, so `python3 -I scripts/pii_guard.py …` or `uv run scripts/pii_guard.py …` runs it with no setup. A hit prints where it is and what kind of data it is (`docs/a.md:12:5: rut`), **never the value**, so a CI log or a refusal can't leak the data it caught.

## What is checked

**Patterns.** These need no list and run everywhere, always:

| Kind | Matches | Passes |
|------|---------|--------|
| `rut` | A RUT with a **valid** check digit: `15.234.871-1`, `15234871-1`, `…-K` | A wrong check digit; a RUT inside a longer number <!-- pii-ok: invented --> |
| `phone` | A Chilean mobile: `+56 9 xxxx xxxx`, `+569xxxxxxxx`, `56 9 …`, `0056 9 …`, `9 xxxx xxxx`, `9xxxxxxxx`, `(9) xxxx-xxxx` | Landlines, other countries |
| `email` | An address whose domain is not on `EMAIL_DOMAINS` | `example.com` / `.org` / `.net` / `.cl`, `*.test`, `*.example`, `*.invalid`, `rakin.app`, `rakin.test`, GitHub's noreply addresses, and their subdomains |

The textbook values the code's docstrings quote (`12.345.678-5`, `76.123.456-0`, `7.654.321-6`, `9 1234 5678`, `9 8765 4321`, …) and the demo gym's phones (`9 6123 45xx`) are on `EXAMPLE_VALUES` / `EXAMPLE_PREFIXES` and pass.

**The denylist.** These are the real people: names, emails, RUTs and phones exported from staging. Matching ignores case and accents (`Ñuñoa` is `nunoa`), and a name also matches inside an identifier or address (`ximena_nunez`, `ximena.nunez@…`). A name of two or more words matches only as that whole sequence, so a list entry "Ximena Ñúñez" never fires on a lone "Ximena". A single-word entry is ignored, with a warning that gives its line number, unless the list writes it `word: <it>`. Words must be in the same order, so a name written surname first (`Ñúñez Peñaloza, Ximena`) matches both orders, but `Ximena Ñúñez Peñaloza` matches only that one. The staging export writes names as they are stored; add a `Surnames, Given names` line for anyone the gym's sheets list surname first. A RUT or phone matches in any format, and needs at least 8 digits: a shorter entry is ignored with a warning, since it would fire inside unrelated numbers.

## Where the list lives

**Never in the repo**, not even hashed: a list of names is easy to brute-force from its hashes.

- **Locally**: `~/.config/rakin/pii-denylist.txt`, mode `600`, or the file named by `PII_DENYLIST_FILE`.
- **CI**: the repository secret `PII_DENYLIST`, holding the same content. The script reads the variable's content directly.

Without a list, the patterns still run. CI says `PII_DENYLIST is not set` in a notice, and so does a fork's PR, which gets no secrets.

The format is one entry per line, with `#` starting a comment:

```text
# exported 2026-11-15 from staging
Nombre Apellido
nombre.apellido@gmail.com   # pii-ok: an invented example
12.345.678-5
+56 9 1234 5678
word: Apellidoraro
Apellido Materno, Nombre
```

### Refreshing it from staging

The PM refreshes it after a gym imports or adds members. The query leaves out the demo gym, whose invented people are already in the repo:

```sh
ssh <staging> 'cd /srv/rakin && docker compose exec -T postgres psql -U rakin rakin -At' <<'SQL' \
  >~/.config/rakin/pii-denylist.txt
WITH real AS (SELECT id FROM gym WHERE name <> 'Academia Sur')
SELECT DISTINCT v FROM (
  SELECT unnest(ARRAY[name, email, phone, rut]) AS v FROM person WHERE gym_id IN (SELECT id FROM real)
  UNION ALL
  SELECT unnest(ARRAY[first_name || ' ' || last_name, email, phone, rut, guardian_name, guardian_phone])
  FROM join_request WHERE gym_id IN (SELECT id FROM real)
) s WHERE v IS NOT NULL AND btrim(v) <> '';
SQL
chmod 600 ~/.config/rakin/pii-denylist.txt
gh secret set PII_DENYLIST --repo rakin-app/rakin <~/.config/rakin/pii-denylist.txt
```

Add any other place a real person turns up, such as a staff member's address or a name from a WhatsApp thread, by hand.

## Where it runs

| Where | What it scans | Set up by |
|-------|---------------|-----------|
| `pre-commit` hook | The lines the commit adds | `make hooks` |
| `commit-msg` hook | The whole commit message, `#` lines included: `git commit -m` and `-F` keep them, and the hook cannot tell which kind of commit ran. Only the `>8` scissors tail is skipped. `…-by:` trailers and the editor template's `# Author:` / `# Date:` lines skip the patterns, since they repeat the commit's own author, but they still get the denylist. | `make hooks` |
| Claude Code `PreToolUse` hook on `Bash` | Any `gh issue\|pr\|api\|release` call: the command text, a heredoc body included, and every file it names with `--body-file`, `-F`, `--input`, `--notes-file` or `-F field=@file`, or reads into an argument with `$(cat file)`, `$(<file)` or backticks. `$VAR` and `~` in a path are expanded. A file the hook cannot read (an unset variable, a `$(…)` path, a file the same command writes first) blocks the call too, so write the body to a literal path in a separate step. A hit blocks the call and gives the reason. | [`.claude/settings.json`](../.claude/settings.json), inherited by every worktree |
| CI `pii / pr` job | The PR's diff (added lines), title and body. It re-runs when the title or body is edited. | [`.github/workflows/pii.yml`](../.github/workflows/pii.yml) |
| CI `pii / daily` job | Issues, PRs, comments and review comments created or edited in the last day. A hit fails the run, so the owner gets GitHub's email. It opens nothing public. | same |

Git shares one hooks directory across a clone's worktrees, so one `make hooks` covers every worker. Hooks that are already there are kept and chained, never replaced. task-force's `ci-guard` owns `commit-msg` and chains `commit-msg.local`, so this guard takes the `.local` slot and moves what was there to `commit-msg.pii-chained`. The chain then runs ci-guard, the PII guard, and the DCO sign-off, in that order. Re-running `make hooks` is safe.

`make pii` runs the guard's tests and scans every tracked file.

By hand:

```sh
python3 -I scripts/pii_guard.py scan notes.md        # files, or - for stdin (--name LABEL)
python3 -I scripts/pii_guard.py diff --range main...HEAD
python3 -I scripts/pii_guard.py tree                 # every tracked file
python3 -I scripts/pii_guard.py --no-denylist tree   # patterns only
```

## Invented values in fixtures

Tests and the demo gym need RUTs and phones that look real. Mark them; don't hide them:

- **One line**: put `pii-ok` anywhere on it, usually in a comment (`# pii-ok: invented`).
- **A whole file**: files under `FIXTURE_PATHS` in the script are exempt: `backend/tests/`, `backend/app/seed/`, `frontend/src/**/*.test.ts(x)`, the lock files, and the guard's own tests.

Both skip the **patterns only**. Nothing skips the denylist, since every entry on it is a real person. If a denylisted name is also a fixture's invented name, rename the fixture.

## On a hit

Edit the text and try again. If the value already reached GitHub:

- **An issue, PR body or comment**: edit it, which replaces the value on the page. The edit history still holds the old text: anyone with write access can open **edited ▾**, pick the old revision and delete it. A comment that is wrong throughout can simply be deleted.
- **A pushed commit**: rewrite history with [`git filter-repo`](https://github.com/newren/git-filter-repo) (`--replace-text`, with the value on the left-hand side of the rules file), then force-push every affected branch. `main` refuses force-pushes, so an owner lifts the protection for the push and restores it afterwards. Old SHAs stay reachable from PR refs and forks until GitHub garbage-collects them, so open a request with [GitHub Support](https://support.github.com/) to remove cached views and PR refs. See [Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
- **The daily job failed**: its log names the issue or comment and the line. Edit it as above.

In every case, tell the owner. Under Ley 21.719, a gym's members' data reaching the public is the gym's to know about.
