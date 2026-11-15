# Shortcuts for the Compose stack; see README "Run locally".

.PHONY: seed
# Load the demo gym, Academia Sur. Safe to re-run: it inserts only what is missing.
seed:
	docker compose run --rm api python -m app.seed

.PHONY: hooks
# The PII guard's pre-commit and commit-msg hooks, for every worktree of this
# clone; see docs/privacy-guard.md.
hooks:
	scripts/install-hooks.sh

.PHONY: pii
# The PII guard's tests, then a scan of every tracked file.
pii:
	python3 -m unittest discover -s scripts -p 'test_*.py'
	python3 -I scripts/pii_guard.py tree
