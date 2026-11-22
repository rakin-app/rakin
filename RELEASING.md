# Releasing Rakin

There is one way to put a new version of Rakin in front of a gym. It goes through **staging** first (a copy of Rakin with made-up data, at `staging.rakin.app`), and reaches **production** (the real gyms, at `rakin.app`) only after the owner approves it in GitHub. Nobody deploys by hand, except to roll back as described below.

## Who does what

| Who | Does |
| --- | --- |
| The PM | merges the reviewed PRs, writes the release notes, runs `scripts/release.sh`, checks staging by hand |
| GitHub (the `deploy` workflow) | deploys to staging and checks it; after the approval, backs up production, deploys and checks it |
| The owner | reads the release's summary page and approves production, or does not |

The approval is always the owner's own click, never the PM's.

## What happens on a release

1. **Merged and green.** Everything in the release is merged to `main` through a reviewed PR, and GitHub's `ci` and `images` checks passed on that exact commit.
2. **The PM runs the release script**, from an up-to-date checkout of `main`:
   ```sh
   scripts/release.sh --dry-run v0.2.0                       # only checks
   scripts/release.sh --notes notes.md v0.2.0                # releases
   ```
   It refuses, and tags nothing, unless it is on `main`, nothing is uncommitted, the commit is the one on GitHub, the version is new and higher than the last one, and `ci` and `images` passed for that commit (it waits while they run). Then it makes the signed tag, with the notes as its message, pushes it, and follows the deploy until staging is done. It never connects to a server and never deploys production.
3. **Staging deploys and checks itself**: the new version is running, the database is up to date, no errors in the logs, the site answers. If any of that fails, the run stops there and production is never offered.
4. **The PM checks staging by hand** (the list below).
5. **The owner approves production** from the link the script printed, after reading its summary (below).
6. **Production backs up, deploys and checks itself**: it takes a backup first and stops if the backup did not upload; then the same checks as staging.

## The release notes

A short file, in plain words, saying what changes for a gym: new screens, fixes people will notice, anything the gym owner should be told. It becomes the tag's message and the first thing on the owner's approval page.

## What the PM checks on staging

If the release has migrations, first run `./reset-staging.sh` on the staging host (`/srv/rakin`): a deploy migrates staging but does not reseed it, so the seed gym stays in the old shape until the next nightly reset.

On `https://staging.rakin.app`, signed in with the PM's own address (staging only sends mail to the team's addresses), in a phone-sized window and a desktop one:

- the sign-in works, and `/plataforma` opens;
- the seed gym, `https://academia-sur.staging.rakin.app`, opens;
- every screen the release changed does what its PR says;
- uploading a transfer proof still works (from a phone-sized window): sign in to the seed gym with the **first** address in `STAGING_OPERATORS`, which the nightly reset gives to the student Felipe Díaz, whose payment is past due (Vencido, with Subir comprobante);
- that proof reaches **Validar comprobante**: sign in with the **second** address, which the reset gives to the owner, Martín Fuentes;
- the browser console shows no errors.

Sign in with the **code** in the email, never its link: opening the link spends the code. Both addresses must be in the host's `MAIL_ALLOW`, or no code arrives (`reset.log` warns of it). See [docs/deploy.md](docs/deploy.md#the-nightly-reset).

Then the PM tells the owner the release is ready to approve, or that it is not and why.

## What the owner looks at before approving

The run's page in GitHub (the link `release.sh` printed, or **Actions → deploy**) has a summary at the top:

- **Notes**: do they make sense, and is it what you expected?
- **Commits**: what changed since the version production runs now.
- **Migrations**: if it says **"Has migrations"**, the release changes the database. It can still be undone, but only by restarting the old version on the new database, not by undoing the change.
- **Staging**: the staging job is green, and the PM said staging looked right.

If all of that is fine: **Review deployments → production → Approve and deploy**. If not, **Reject** and tell the PM; nothing reaches the gyms.

## If something breaks

A failed check stops the run and prints, at the top of the failed job's page, the exact line to roll back with. Tell the PM, with that link.

**To roll back** to the version that ran before (the PM does this; production still needs the owner's approval):

- In GitHub: **Actions → deploy → Run workflow**, with the previous tag, **rollback** ticked, and **target** `staging` or `production`. A rollback takes no backup and changes nothing in the database.
- If GitHub cannot reach the server: on that server, `cd /srv/rakin && ./deploy.sh --rollback <previous tag>`, the line the failed job printed. This is the only time anyone deploys by hand.

A release whose database change is itself the problem is not rolled back: it is fixed by a new release with a corrected change. More detail in [`docs/deploy.md`](docs/deploy.md#6-rollback).

## What never to do

- Make or push a `v*` tag by hand, or tag a commit that is not on `main`: always `scripts/release.sh`.
- Deploy production by hand, except the rollback above.
- Approve production for someone else, or without reading the summary.
- Run `python -m app.seed` on production (it refuses there, and must keep refusing), or `alembic downgrade` on any server.
- Copy a production secret onto the staging server.

## Once, before the first release

The PM's machine needs `gh` signed in (`gh auth login`) and a key that signs tags. With an SSH key:

```sh
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
```

and add the same public key on GitHub as a **signing key** (Settings → SSH and GPG keys), so the tag shows as verified.
