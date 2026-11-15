#!/usr/bin/env bash
# Install the PII guard's git hooks (#302): `make hooks`, or run this directly.
#
#   pre-commit  scans the lines the commit adds
#   commit-msg  scans the commit message
#
# Git shares one hooks directory across a repo's worktrees, so one install covers
# every worker. A hook already there is kept and chained as `<hook>.pii-chained`.
# task-force's ci-guard owns `commit-msg` and chains `commit-msg.local`, so when
# its hook is in place this one takes the `.local` slot instead and the chain
# runs ci-guard, then this, then whatever `.local` held before. Re-running is
# safe. See docs/privacy-guard.md.
set -euo pipefail

MARKER="rakin:pii-guard-hook"
TASK_FORCE_MARKER="task-force:ci-guard-hook"

hooks_dir=$(git rev-parse --path-format=absolute --git-path hooks)
mkdir -p "$hooks_dir"

hook_body() { # $1 = hook name, $2 = guard command
  cat <<HOOK
#!/usr/bin/env bash
# $MARKER: installed by \`make hooks\` (scripts/install-hooks.sh); see
# docs/privacy-guard.md. Delete this file to uninstall.
set -euo pipefail

guard="\$(git rev-parse --show-toplevel)/scripts/pii_guard.py"
if [ -f "\$guard" ]; then
  python3 -I "\$guard" $2 || exit 1
else
  echo "pii-guard: no scripts/pii_guard.py in this checkout; $1 not scanned." >&2
fi

prev="\$(dirname "\$0")/$1.pii-chained"
if [ -x "\$prev" ]; then exec "\$prev" "\$@"; fi
exit 0
HOOK
}

install_hook() { # $1 = hook name, $2 = guard command
  local name="$1" slot="$hooks_dir/$1" chained="$hooks_dir/$1.pii-chained"
  if [ "$name" = commit-msg ] && grep -qF "$TASK_FORCE_MARKER" "$slot" 2>/dev/null; then
    slot="$hooks_dir/commit-msg.local"
  fi
  if [ -e "$slot" ] && ! grep -qF "$MARKER" "$slot"; then
    if [ -e "$chained" ]; then
      echo "pii-guard: both $slot and $chained exist; leaving them alone." >&2
      echo "  Chain $name by hand (see docs/privacy-guard.md)." >&2
      return 1
    fi
    mv "$slot" "$chained"
    echo "pii-guard: kept the existing $(basename "$slot") hook as $(basename "$chained") (chained)."
  fi
  hook_body "$name" "$2" >"$slot"
  chmod +x "$slot"
  echo "pii-guard: $name hook installed at $slot"
}

status=0
install_hook pre-commit staged || status=1
# shellcheck disable=SC2016 # `$1` is the hook's own argument, expanded when it runs
install_hook commit-msg 'commit-msg "$1"' || status=1
exit "$status"
