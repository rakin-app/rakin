#!/usr/bin/env bash
# Usage: check-dco.sh <base> <head>
#
# Fails unless every non-merge commit in <base>..<head> carries a
# `Signed-off-by:` trailer naming its author's email (the DCO, see CONTRIBUTING.md).
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <base> <head>" >&2
  exit 2
fi

failed=0
count=0
for sha in $(git rev-list --no-merges "$1..$2"); do
  count=$((count + 1))
  author=$(git log -1 --format='%ae' "$sha")
  signoffs=$(git log -1 --format='%(trailers:key=Signed-off-by,valueonly)' "$sha")
  if ! grep -qiF "<$author>" <<<"$signoffs"; then
    echo "::error::$(git log -1 --format='%h %s' "$sha"): no Signed-off-by for author <$author>"
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "Sign off each commit with \`git commit -s\` (amend or rebase with --signoff), then push again."
  exit 1
fi
echo "DCO: $count commit(s) signed off."
