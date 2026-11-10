#!/usr/bin/env bash
# Restore a backup into a scratch Postgres and check it, never the live one.
# Run on the host, in /srv/rakin, with the age private key on stdin; from a
# laptop that keeps it off the host's disk:
#
#   ssh deploy@<host> 'cd /srv/rakin && ./restore.sh latest' <rakin-backup.key
#   ./restore.sh rakin/staging/20261110T060000Z.dump.age   # then paste the key, Ctrl-D
#
# The `backup` service's image downloads the backup (python -m app.backup
# fetch) and decrypts it with the key from stdin into a Docker volume; a
# throwaway postgres container with no network restores it. Then every
# table's row count in the restored database is checked against the rows the
# dump holds. The volume and the container are removed whatever happens.
#
# Restoring to the live database is a separate, deliberate step that this
# script never takes: docs/deploy.md#restoring-to-live.
set -euo pipefail

usage="usage: $0 <object key | latest>   (the age private key on stdin)"
key=${1:?$usage}
if [ "$key" != latest ] && ! [[ $key =~ ^[A-Za-z0-9/_-]+\.dump\.age$ ]]; then
	echo "restore: not a backup's key: $key" >&2
	exit 2
fi

docker=${DOCKER:-docker}
# The live database's image (deploy/docker-compose.yml's `postgres`).
image=postgres:17
name=rakin-restore-$$

# shellcheck disable=SC2329 # run by the trap
cleanup() {
	"$docker" rm -f -v "$name" >/dev/null 2>&1 || true
	"$docker" volume rm "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$docker" volume create "$name" >/dev/null

# Download and decrypt; the key arrives on age's stdin and is never written.
# shellcheck disable=SC2016 # expanded by the container's shell
key=$("$docker" compose run --rm -T --no-deps -v "$name:/restore" backup sh -c '
	set -e
	key=$(python -m app.backup fetch "$1" /restore/backup.dump.age | tail -n 1)
	age --decrypt -i - -o /restore/backup.dump /restore/backup.dump.age
	rm /restore/backup.dump.age
	echo "$key"' sh "$key")
echo "restore: fetched and decrypted $key"

password=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
"$docker" run -d --name "$name" --network none -v "$name:/restore" \
	-e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=restore "$image" >/dev/null
db() { "$docker" exec "$name" "$@"; }
# Over TCP: the entrypoint's init-phase server answers on the socket only.
tries=0
until db env PGPASSWORD="$password" psql -h 127.0.0.1 -U postgres -d restore -Atqc 'SELECT 1' >/dev/null 2>&1; do
	tries=$((tries + 1))
	[ "$tries" -lt 60 ] || { echo "restore: the scratch database never started" >&2; exit 1; }
	sleep 1
done

# Roles are cluster-wide, so a dump has none: create, without logins, every
# role the schema owns things as, grants to or names in a policy.
# shellcheck disable=SC2016 # the sed scripts run in the container
roles=$(db sh -c 'pg_restore --schema-only -f - /restore/backup.dump | sed -nE \
	-e "s/^ALTER .* OWNER TO ([a-z_][a-z0-9_]*);\$/\1/p" \
	-e "s/^GRANT .* TO ([a-z_][a-z0-9_]*);\$/\1/p" \
	-e "s/^REVOKE .* FROM ([a-z_][a-z0-9_]*);\$/\1/p" \
	-e "s/^CREATE POLICY [^ ]+ ON [^ ]+( AS [A-Z]+)?( FOR [A-Z]+)? TO ([a-z_][a-z0-9_]*).*/\3/p" |
	sort -u')
for role in $roles; do
	db psql -U postgres -d restore -v ON_ERROR_STOP=1 -qc \
		"DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$role') THEN CREATE ROLE $role NOLOGIN; END IF; END \$\$" >/dev/null
done

db pg_restore -U postgres -d restore --exit-on-error /restore/backup.dump
echo "restore: restored into a scratch database"

# The rows each table's COPY block in the dump holds: one line per row.
expected=$(db pg_restore --data-only -f - /restore/backup.dump | awk '
	/^COPY / { table = $2; rows = 0; next }
	table != "" && /^\\\.$/ { print table, rows; table = ""; next }
	table != "" { rows++ }')
if [ -z "$expected" ]; then
	echo "restore: FAIL - the dump holds no tables" >&2
	exit 1
fi

fails=0
tables=0
total=0
while read -r table rows; do
	got=$(db psql -U postgres -d restore -Atc "SELECT count(*) FROM $table")
	tables=$((tables + 1))
	total=$((total + rows))
	if [ "$got" = "$rows" ]; then
		echo "ok   - $table: $rows rows"
	else
		echo "FAIL - $table: the dump holds $rows rows, the restore has $got"
		fails=1
	fi
done <<<"$expected"

if [ "$fails" = 0 ]; then
	echo "restore: $key is good: $tables tables, $total rows, every count matches"
else
	echo "restore: $key restored, but some counts differ" >&2
fi
exit "$fails"
