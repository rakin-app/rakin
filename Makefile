# Shortcuts for the Compose stack; see README "Run locally".

.PHONY: seed
# Load the demo gym, Academia Sur. Safe to re-run: it inserts only what is missing.
seed:
	docker compose run --rm api python -m app.seed
