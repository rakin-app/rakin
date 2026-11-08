#!/usr/bin/env bash
# Tests for check-dco.sh against a throwaway repo.
set -euo pipefail

check=$(cd "$(dirname "$0")" && pwd)/check-dco.sh
repo=$(mktemp -d)
trap 'rm -rf "$repo"' EXIT
cd "$repo"
git init -q -b main
export GIT_AUTHOR_NAME=Ana GIT_AUTHOR_EMAIL=ana@example.com
export GIT_COMMITTER_NAME=Ana GIT_COMMITTER_EMAIL=ana@example.com
git commit -q --allow-empty -m base
base=$(git rev-parse HEAD)

fails=0
expect() { # expect <ok|fail> <description>
  if "$check" "$base" HEAD >/dev/null 2>&1; then got=ok; else got=fail; fi
  if [ "$got" = "$1" ]; then echo "ok   - $2"; else echo "FAIL - $2 (got $got)"; fails=1; fi
}

expect ok "an empty range passes"

git commit -q --allow-empty -s -m signed
expect ok "a signed-off commit passes"

git commit -q --allow-empty -m buried -m "Signed-off-by: Ana <ana@example.com>" -m "A last paragraph that is not a trailer."
expect fail "a sign-off outside the trailers fails"
git reset -q --hard HEAD~1

git commit -q --allow-empty -m unsigned
expect fail "an unsigned commit fails"
git reset -q --hard HEAD~1

git commit -q --allow-empty -m other -m "Signed-off-by: Bob <bob@example.com>"
expect fail "a sign-off by someone other than the author fails"
git reset -q --hard HEAD~1

git commit -q --allow-empty -m caps -m "Signed-off-by: Ana <ANA@example.com>"
expect ok "the email match ignores case"

git checkout -q -b side "$base"
git commit -q --allow-empty -s -m side
git checkout -q main
git merge -q --no-ff --no-edit side
expect ok "an unsigned merge commit is ignored"

exit "$fails"
