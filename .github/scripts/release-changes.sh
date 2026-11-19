#!/usr/bin/env bash
# Usage: release-changes.sh [--rollback] <tag> [<previous tag>]
#
# Prints, as Markdown, what deploying <tag> to production changes: the tag's
# notes (its annotation), the commits since <previous tag> (what production
# runs now) and the migrations among them. deploy.yml writes it to the run's
# job summary, which is the page the owner reads before approving. With no
# previous tag, or one git does not know, the changes cannot be listed and it
# says so. With --rollback, the commits listed are the ones leaving production.
set -euo pipefail

rollback=0
if [ "${1:-}" = "--rollback" ]; then rollback=1; shift; fi
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "usage: $0 [--rollback] <tag> [<previous tag>]" >&2
  exit 2
fi
tag=$1 previous=${2:-} unknown=
migrations_dir=backend/alembic/versions
rollback_docs=${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-rakin-app/rakin}/blob/main/docs/deploy.md#6-rollback

sha=$(git rev-parse --verify --quiet "refs/tags/$tag^{commit}") \
  || { echo "release-changes: no tag $tag" >&2; exit 1; }
if [ -n "$previous" ] && ! git rev-parse --verify --quiet "refs/tags/$previous^{commit}" >/dev/null; then
  unknown=$previous
  previous=
fi

if [ $rollback = 1 ]; then
  echo "# Roll production back to $tag"
else
  echo "# Release $tag to production"
fi
echo
echo "| | |"
echo "| --- | --- |"
echo "| Tag | \`$tag\` ($(git log -1 --format=%h "$sha")) |"
echo "| Production runs now | ${previous:+\`$previous\`}${unknown:+\`$unknown\` (not a tag in this repository)}$([ -n "$previous$unknown" ] || echo 'none recorded') |"
echo

echo "## Notes"
echo
if [ "$(git for-each-ref --format='%(objecttype)' "refs/tags/$tag")" = tag ]; then
  git for-each-ref --format='%(contents:subject)' "refs/tags/$tag"
  body=$(git for-each-ref --format='%(contents:body)' "refs/tags/$tag")
  [ -z "$body" ] || printf '\n%s\n' "$body"
else
  echo "_$tag is a lightweight tag: it has no notes._"
fi
echo

if [ -z "$previous" ]; then
  echo "## Changes"
  echo
  if [ -n "$unknown" ]; then
    echo "Production's tag \`$unknown\` is not in this repository, so the changes cannot be listed. Read the notes, and treat it as a release **with migrations**."
  else
    echo "No earlier production deploy is recorded, so the changes cannot be listed. Read the notes, and treat it as a release **with migrations**."
  fi
  exit 0
fi

if [ "$sha" = "$(git rev-parse "refs/tags/$previous^{commit}")" ]; then
  echo "## Changes"
  echo
  echo "None: production already runs this commit."
  exit 0
fi

if git merge-base --is-ancestor "$sha" "refs/tags/$previous^{commit}"; then
  leaving=1
  from=$tag to=$previous
  echo "## Commits leaving production ($tag..$previous)"
else
  from=$previous to=$tag
  echo "## Commits ($previous..$tag)"
fi
echo
git log --no-merges --format='- %h %s' "refs/tags/$from..refs/tags/$to"
echo

echo "## Migrations"
echo
migrations=$(git diff --name-only "refs/tags/$from" "refs/tags/$to" -- "$migrations_dir")
if [ -z "$migrations" ]; then
  echo "None."
elif [ -n "${leaving:-}" ]; then
  while read -r file; do echo "- \`$file\`"; done <<<"$migrations"
  echo
  echo "**These migrations stay applied**: a rollback is restart-only, and $tag runs on the newer schema. See [docs/deploy.md, Rollback]($rollback_docs)."
else
  while read -r file; do echo "- \`$file\`"; done <<<"$migrations"
  echo
  echo "**Has migrations: rollback is restart-only.** Going back after this release leaves the schema as it is; a broken migration is fixed by rolling forward. See [docs/deploy.md, Rollback]($rollback_docs)."
fi
