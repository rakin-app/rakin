#!/usr/bin/env bash
# Tests for scripts/release.sh, with a fake `git` whose answers come from the
# environment (BRANCH, DIRTY, HEAD_SHA, ORIGIN_SHA, TAGS, REMOTE_TAGS,
# SIGNINGKEY) and a fake `gh` that answers each call with the next JSON
# document queued for it, passed through the script's own --jq filter.
# The checks are functions that `check` calls by name:
# shellcheck disable=SC2329
set -euo pipefail

src=$(cd "$(dirname "$0")/.." && pwd)
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cp "$src/scripts/release.sh" "$dir/"
cat >"$dir/git" <<'SH'
#!/usr/bin/env bash
d=$(dirname "$0")
echo "git $*" >>"$d/calls"
has() { printf '%s\n' $1 | grep -qxF -- "$2"; }
last=${*: -1} tag=${last#refs/tags/}
case "$*" in
  "symbolic-ref --quiet --short HEAD") [ -n "$BRANCH" ] && echo "$BRANCH" ;;
  "status --porcelain") printf '%b' "$DIRTY" ;;
  "fetch "*) [ -z "${FETCH_FAILS:-}" ] ;;
  "rev-parse HEAD") echo "$HEAD_SHA" ;;
  "rev-parse origin/main") echo "$ORIGIN_SHA" ;;
  "rev-parse --quiet --verify refs/tags/"*) has "$TAGS" "$tag" ;;
  "ls-remote --tags origin refs/tags/"*) ! has "$REMOTE_TAGS" "$tag" || echo "abc	$last" ;;
  "tag --list v*") printf '%s\n' $TAGS ;;
  "config --get user.signingkey") [ -n "$SIGNINGKEY" ] && echo "$SIGNINGKEY" ;;
  "tag -s "*) cat >"$d/tagmsg"; [ -z "${TAG_FAILS:-}" ] ;;
  "push "*) [ -z "${PUSH_FAILS:-}" ] ;;
  *) echo "fake git: unexpected $*" >&2; exit 99 ;;
esac
SH
# gh: the queue is a file of one JSON document per line, named for the
# workflow (`list.ci.yml`) or `view`; the last document repeats.
cat >"$dir/gh" <<'SH'
#!/usr/bin/env bash
d=$(dirname "$0")
echo "gh $*" >>"$d/calls"
[ -z "${GH_FAILS:-}" ] || exit 1
args=("$@") queue='' filter=''
for ((i = 0; i < ${#args[@]}; i++)); do
  case ${args[i]} in
    --workflow) queue=list.${args[i + 1]} ;;
    --jq) filter=${args[i + 1]} ;;
  esac
done
[ "$1 $2" = "run view" ] && queue=view
[ -n "$queue" ] && [ -f "$d/$queue" ] || { echo "fake gh: nothing queued for $*" >&2; exit 99; }
doc=$(head -n 1 "$d/$queue")
[ "$(wc -l <"$d/$queue")" -le 1 ] || sed -i.bak 1d "$d/$queue"
jq -r "$filter" <<<"$doc"
SH
cat >"$dir/sleep" <<'SH'
#!/usr/bin/env bash
echo "sleep $*" >>"$(dirname "$0")/calls"
SH
chmod +x "$dir/git" "$dir/gh" "$dir/sleep"
export GIT=$dir/git GH=$dir/gh SLEEP=$dir/sleep RELEASE_POLL_SECONDS=7 RELEASE_POLLS=4

sha=0123456789abcdef0123456789abcdef01234567
printf 'Pagos: el comprobante se puede subir desde el teléfono.\n' >"$dir/notes"
: >"$dir/empty"

run_doc() { # run_doc <status> <conclusion>
  printf '[{"status":"%s","conclusion":"%s","url":"https://github.test/runs/1"}]\n' "$1" "$2"
}
deploy_doc() { # deploy_doc <tag>
  printf '[{"databaseId":7,"headBranch":"%s","url":"https://github.test/runs/7"}]\n' "$1"
}
view_doc() { # view_doc <run status> <staging status> <staging conclusion> [<host step conclusion>]
  printf '{"status":"%s","conclusion":"","jobs":[{"name":"release","status":"completed","conclusion":"success","steps":[]}' "$1"
  [ "$2" = none ] || printf ',{"name":"staging / staging","status":"%s","conclusion":"%s","steps":[{"name":"Check the secrets","conclusion":"success"},{"name":"Run it on the host","conclusion":"%s"}]}' "$2" "$3" "${4:-success}"
  printf ']}\n'
}
queue() { # queue <name> <document>...: replace what the fake gh answers
  local name=$1; shift
  printf '%s\n' "$@" >"$dir/$name"
}
green() {
  export BRANCH=main DIRTY='' HEAD_SHA=$sha ORIGIN_SHA=$sha TAGS='v0.1.9 v0.1.48 v0.0.1 vtest' REMOTE_TAGS='v0.1.9 v0.1.48' SIGNINGKEY=key.pub
  unset FETCH_FAILS GH_FAILS TAG_FAILS PUSH_FAILS
  queue list.ci.yml "$(run_doc completed success)"
  queue list.images.yml "$(run_doc completed success)"
  queue list.deploy.yml "$(deploy_doc v0.1.49)"
  queue view "$(view_doc waiting completed success)"
}

fails=0
check() { # check <description> <command...>
  local what=$1; shift
  if "$@"; then echo "ok   - $what"; else echo "FAIL - $what"; fails=1; fi
}
run() { : >"$dir/calls"; rm -f "$dir/tagmsg"; "$dir/release.sh" "$@" >"$dir/out" 2>&1; }
refused() { ! run "$@"; }
said() { grep -qF -- "$1" "$dir/out"; }
called() { grep -qF -- "$1" "$dir/calls"; }
not_called() { ! called "$1"; }
not_tagged() { not_called "git tag -s" && not_called "git push"; }

green
check "refuses no version" refused
check "refuses an unknown option" refused --force v0.1.49
check "refuses two versions" refused v0.1.49 v0.1.50
check "refuses a version that is not vX.Y.Z" refused --dry-run 0.1.49
check "and says so" said "'0.1.49' is not vX.Y.Z"
check "refuses a suffixed version" refused --dry-run v0.1.49-rc1
check "refuses a release without notes" refused v0.1.49
check "and says it needs --notes" said "needs --notes"
check "and asks nothing of git" [ ! -s "$dir/calls" ]
check "refuses a notes file that is not there" refused --notes "$dir/nope" v0.1.49
check "refuses an empty notes file" refused --notes "$dir/empty" v0.1.49

# The commit.
BRANCH=feature check "refuses another branch" refused --dry-run v0.1.49
check "and names it" said "on branch feature"
BRANCH='' check "refuses a detached HEAD" refused --dry-run v0.1.49
DIRTY=' M backend/app/main.py\n' check "refuses a dirty tree" refused --dry-run v0.1.49
check "and says so" said "not clean"
DIRTY='?? scratch.txt\n' check "an untracked file is dirty too" refused --dry-run v0.1.49
FETCH_FAILS=1 check "refuses when origin cannot be fetched" refused --dry-run v0.1.49
ORIGIN_SHA=fedcba9876543210fedcba9876543210fedcba98 check "refuses HEAD behind or ahead of origin/main" refused --dry-run v0.1.49
check "and names both commits" said "is not origin/main (fedcba98"

# The version.
check "refuses an existing tag" refused --dry-run v0.1.48
check "and says it exists" said "v0.1.48 already exists"
REMOTE_TAGS='v0.1.48 v0.1.49' check "refuses a tag only origin has" refused --dry-run v0.1.49
check "refuses a version below the latest" refused --dry-run v0.1.47
check "and names the latest" said "not greater than the latest tag, v0.1.48"
check "versions compare as numbers, not text" refused --dry-run v0.1.10
check "a newer minor is greater" run --dry-run v0.2.0
check "a newer major is greater" run --dry-run v1.0.0
TAGS='' REMOTE_TAGS='' check "the first release needs no earlier tag" run --dry-run v0.0.1

# The commit's checks.
queue list.ci.yml "$(run_doc completed failure)"
check "refuses a red ci" refused --dry-run v0.1.49
check "and names the run" said "ci.yml concluded 'failure' for 0123456789ab: https://github.test/runs/1"
green; queue list.images.yml "$(run_doc completed cancelled)"
check "refuses a cancelled images" refused --dry-run v0.1.49
green; queue list.ci.yml '[]' "$(run_doc queued '')" "$(run_doc in_progress '')" "$(run_doc completed success)"
check "waits for a ci run to appear and finish" run --dry-run v0.1.49
check "and says what it waits for" said "wait - ci.yml is in_progress"
check "sleeping RELEASE_POLL_SECONDS between polls" [ "$(grep -c '^sleep 7$' "$dir/calls")" = 3 ]
green; queue list.ci.yml "$(run_doc in_progress '')"
check "refuses a ci still running after RELEASE_POLLS" refused --dry-run v0.1.49
check "and says it timed out" said "ci.yml did not pass for 0123456789ab in time"
check "having polled RELEASE_POLLS times" [ "$(grep -c 'run list --workflow ci.yml' "$dir/calls")" = 4 ]
green; queue list.ci.yml '[]'
check "refuses when no ci run ever appears" refused --dry-run v0.1.49
green
check "asks for this commit's push runs" called "gh run list --workflow ci.yml --commit $sha --event push"
GH_FAILS=1 check "refuses when GitHub cannot be asked" refused --dry-run v0.1.49

# --dry-run.
green
check "a dry run passes on a green main" run --dry-run v0.1.49
check "and prints every check" said "ok   - images.yml passed for 0123456789ab"
check "and says the notes are needed for real" said "skip - notes"
check "and tags nothing" not_tagged
check "and never looks for a deploy" not_called "deploy.yml"
check "a dry run checks notes it is given" refused --dry-run --notes "$dir/empty" v0.1.49

# The release.
green
check "a release passes on a green main" run --notes "$dir/notes" v0.1.49
check "makes a signed annotated tag on HEAD" called "git tag -s v0.1.49 -F - $sha"
check "whose message is the version, then the notes" \
  [ "$(cat "$dir/tagmsg")" = "$(printf 'v0.1.49\n\nPagos: el comprobante se puede subir desde el teléfono.')" ]
check "pushes only that tag" called "git push --quiet origin refs/tags/v0.1.49"
check "says production waits for the owner" said "Production now waits for the owner's approval"
check "at the run's URL" said "https://github.test/runs/7"
check "tags only after both checks" \
  [ "$(grep -n 'images.yml' "$dir/calls" | tail -n 1 | cut -d: -f1)" -lt "$(grep -n 'git tag -s' "$dir/calls" | cut -d: -f1)" ]
check "never connects to a host" not_called "ssh"
check "never dispatches a workflow" not_called "workflow run"
SIGNINGKEY='' check "refuses without a signing key" refused --notes "$dir/notes" v0.1.49
check "before tagging" not_tagged
green; TAG_FAILS=1 check "refuses when git cannot sign" refused --notes "$dir/notes" v0.1.49
check "and pushes nothing" not_called "git push"
green; PUSH_FAILS=1 check "fails when the push fails" refused --notes "$dir/notes" v0.1.49
check "and says how to push it" said "re-run 'git push origin refs/tags/v0.1.49'"

# Following the run.
green; queue list.deploy.yml '[]' "$(deploy_doc v0.1.48)" "$(deploy_doc v0.1.49)"
check "waits for this tag's deploy run, not another tag's" run --notes "$dir/notes" v0.1.49
check "and says so" said "wait - no deploy run for v0.1.49 yet"
green; queue list.deploy.yml '[]'
check "fails when no deploy run starts" refused --notes "$dir/notes" v0.1.49
green; queue view "$(view_doc in_progress none -)" "$(view_doc in_progress in_progress '')" "$(view_doc waiting completed success)"
check "waits for the staging job" run --notes "$dir/notes" v0.1.49
check "and says what it waits for" said "wait - staging is not started"
green; queue view "$(view_doc in_progress completed failure)"
check "fails when staging fails" refused --notes "$dir/notes" v0.1.49
check "and says production is not offered" said "staging failure for v0.1.49, so production is not offered"
green; queue view "$(view_doc completed completed skipped skipped)"
check "fails when staging was skipped" refused --notes "$dir/notes" v0.1.49
check "and says staging did not run" said "staging did not run for v0.1.49"
green; queue view "$(view_doc completed none -)"
check "fails when the run ends before staging" refused --notes "$dir/notes" v0.1.49
green; queue view "$(view_doc waiting completed success skipped)"
check "a staging job with unset secrets passes" run --notes "$dir/notes" v0.1.49
check "but says it deployed nothing" said "passed without deploying anything"
green; queue view "$(view_doc in_progress in_progress '')"
check "fails when staging outlasts RELEASE_POLLS" refused --notes "$dir/notes" v0.1.49
check "and says where to follow it" said "follow it at https://github.test/runs/7"

exit $fails
