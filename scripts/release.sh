#!/usr/bin/env bash
# Usage: scripts/release.sh [--dry-run] [--notes <file>] vX.Y.Z
#
# The one way to release Rakin (RELEASING.md). From a checkout of `main` it
# checks the commit:
#   on `main`, clean, equal to `origin/main`;
#   vX.Y.Z is new and greater than the latest v* tag;
#   `ci` and `images` concluded success for that exact commit (it waits while
#   they run);
# then makes a signed annotated tag whose message is the version and, under
# it, the notes file (the owner reads them on the approval page), pushes it,
# waits for the deploy run's staging job and prints its result and the run's
# URL, where production now waits for the owner's approval.
#
# It never connects to a host and never deploys production: the backup, the
# deploys and their checks are deploy.yml's. --dry-run runs every check and
# stops before tagging; the notes are needed only for the real run.
#
# RELEASE_POLL_SECONDS (default 30) and RELEASE_POLLS (default 120) bound each
# wait. GIT, GH and SLEEP name the commands, for the tests.
set -euo pipefail

GIT=${GIT:-git}
GH=${GH:-gh}
SLEEP=${SLEEP:-sleep}
poll_seconds=${RELEASE_POLL_SECONDS:-30}
polls=${RELEASE_POLLS:-120}

usage() {
  echo "usage: $0 [--dry-run] [--notes <file>] vX.Y.Z" >&2
  exit 2
}
refuse() {
  echo "release: $*" >&2
  echo "release: nothing was tagged" >&2
  exit 1
}
ok() { echo "ok   - $*"; }

dry_run=0 notes='' version=''
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) dry_run=1; shift ;;
    --notes) [ $# -ge 2 ] || usage; notes=$2; shift 2 ;;
    -*) usage ;;
    *) [ -z "$version" ] || usage; version=$1; shift ;;
  esac
done
[ -n "$version" ] || usage

semver='^v([0-9]+)\.([0-9]+)\.([0-9]+)$'
[[ $version =~ $semver ]] || refuse "'$version' is not vX.Y.Z"
ok "$version is vX.Y.Z"

if [ -n "$notes" ]; then
  [ -f "$notes" ] && [ -r "$notes" ] || refuse "no notes file $notes"
  grep -q '[^[:space:]]' "$notes" || refuse "the notes file $notes is empty"
  ok "notes from $notes"
elif [ $dry_run = 0 ]; then
  refuse "a release needs --notes <file>: what changed, in plain words, for the owner's approval page"
else
  echo "skip - notes: none given; the release itself needs --notes <file>"
fi

# The commit.
branch=$($GIT symbolic-ref --quiet --short HEAD) || refuse "HEAD is detached: check out main"
[ "$branch" = main ] || refuse "on branch $branch: releases are made from main"
ok "on main"
[ -z "$($GIT status --porcelain)" ] || refuse "the working tree is not clean: commit, or set the changes aside"
ok "the working tree is clean"
$GIT fetch --quiet --tags origin main || refuse "could not fetch origin"
sha=$($GIT rev-parse HEAD)
remote=$($GIT rev-parse origin/main)
[ "$sha" = "$remote" ] || refuse "HEAD ($sha) is not origin/main ($remote): pull, or push through a PR"
ok "HEAD is origin/main (${sha:0:12})"

# The version.
if $GIT rev-parse --quiet --verify "refs/tags/$version" >/dev/null \
  || [ -n "$($GIT ls-remote --tags origin "refs/tags/$version")" ]; then
  refuse "$version already exists"
fi
greater() { # greater vA.B.C vX.Y.Z: is the first greater than the second?
  local a b i
  [[ $1 =~ $semver ]]; a=("${BASH_REMATCH[@]:1}")
  [[ $2 =~ $semver ]]; b=("${BASH_REMATCH[@]:1}")
  for i in 0 1 2; do
    if ((10#${a[i]} != 10#${b[i]})); then ((10#${a[i]} > 10#${b[i]})); return; fi
  done
  return 1
}
latest=''
while read -r tag; do
  [[ $tag =~ $semver ]] || continue
  if [ -z "$latest" ] || greater "$tag" "$latest"; then latest=$tag; fi
done < <($GIT tag --list 'v*')
if [ -n "$latest" ]; then
  greater "$version" "$latest" || refuse "$version is not greater than the latest tag, $latest"
  ok "$version is new and greater than $latest"
else
  ok "$version is new (no earlier v* tag)"
fi

# The commit's checks. A run just queued for a fresh merge may not be listed
# yet, so a missing run is waited for like a running one.
green() { # green <workflow file>
  local workflow=$1 i state
  for ((i = 1; i <= polls; i++)); do
    state=$($GH run list --workflow "$workflow" --commit "$sha" --event push --limit 1 \
      --json status,conclusion,url --jq '.[0] // empty | "\(.status) \(.conclusion // "none") \(.url)"') \
      || refuse "could not ask GitHub for $workflow's runs"
    case $state in
      "completed success "*) ok "$workflow passed for ${sha:0:12} (${state##* })"; return ;;
      completed\ *) read -r _ conclusion url <<<"$state"
        refuse "$workflow concluded '${conclusion:-none}' for ${sha:0:12}: $url" ;;
      "") echo "wait - no $workflow run for ${sha:0:12} yet" ;;
      *) echo "wait - $workflow is ${state%% *} (${state##* })" ;;
    esac
    [ "$i" = "$polls" ] || $SLEEP "$poll_seconds"
  done
  refuse "$workflow did not pass for ${sha:0:12} in time"
}
green ci.yml
green images.yml

# The tag is signed, so the key must be set up once (RELEASING.md).
$GIT config --get user.signingkey >/dev/null \
  || refuse "no signing key: set git's user.signingkey (RELEASING.md, before the first release)"
ok "git has a signing key"

if [ $dry_run = 1 ]; then
  echo "dry run: every check passed; $version was not tagged"
  exit 0
fi

# Verbatim: the default cleanup would drop the notes' "#" lines as comments.
printf '%s\n\n%s\n' "$version" "$(cat "$notes")" | $GIT tag -s --cleanup=verbatim "$version" -F - "$sha" \
  || refuse "git could not make the signed tag $version"
ok "tagged ${sha:0:12} as $version (signed)"
$GIT push --quiet origin "refs/tags/$version" \
  || { echo "release: $version was tagged here but not pushed: re-run 'git push origin refs/tags/$version'" >&2; exit 1; }
ok "pushed $version"

# The deploy run, and its staging job.
run='' url=''
for ((i = 1; i <= polls; i++)); do
  read -r run url < <($GH run list --workflow deploy.yml --commit "$sha" --event push --limit 20 \
    --json databaseId,headBranch,url \
    --jq "[.[] | select(.headBranch == \"$version\")][0] // empty | \"\(.databaseId) \(.url)\"") || true
  [ -z "$run" ] || break
  echo "wait - no deploy run for $version yet"
  [ "$i" = "$polls" ] || $SLEEP "$poll_seconds"
done
[ -n "$run" ] || { echo "release: $version is pushed, but no deploy run started: look at the Actions tab" >&2; exit 1; }
ok "deploy run: $url"

for ((i = 1; i <= polls; i++)); do
  # "<run status> <run conclusion> <staging status> <staging conclusion> <host step conclusion>"
  # An unfinished conclusion is "", so every field is "-" when empty.
  # shellcheck disable=SC2016  # $job is jq's
  state=$($GH run view "$run" --json status,conclusion,jobs --jq '
    def v: if . == null or . == "" then "-" else . end;
    ([.jobs[] | select(.name | startswith("staging"))][0]) as $job
    | "\(.status | v) \(.conclusion | v) \($job.status | v) \($job.conclusion | v) \(
        [$job.steps[]? | select(.name == "Run it on the host") | .conclusion][0] | v)"') || state=''
  read -r run_status run_conclusion job_status job_conclusion host_step <<<"${state:-- - - - -}"
  if [ "$job_status" = completed ]; then
    if [ "$job_conclusion" = skipped ]; then
      echo "release: staging did not run for $version (did the release job fail?), so production is not offered: $url" >&2
      exit 1
    fi
    if [ "$job_conclusion" != success ]; then
      echo "release: staging $job_conclusion for $version, so production is not offered: $url" >&2
      echo "release: the job's summary has the rollback line; tell the PM" >&2
      exit 1
    fi
    if [ "$host_step" = skipped ]; then
      echo "note - staging's secrets are unset: the staging job passed without deploying anything"
    fi
    ok "staging passed for $version"
    echo
    echo "Production now waits for the owner's approval, at:"
    echo "  $url"
    echo "The owner reads that run's summary (notes, commits, migrations) before approving."
    exit 0
  fi
  if [ "$run_status" = completed ]; then
    echo "release: the deploy run ended ($run_conclusion) before staging: $url" >&2
    exit 1
  fi
  echo "wait - staging is ${job_status/-/not started}"
  [ "$i" = "$polls" ] || $SLEEP "$poll_seconds"
done
echo "release: staging had not finished in time; follow it at $url" >&2
exit 1
