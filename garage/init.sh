#!/bin/sh
# One-shot bootstrap for the single-node Garage: assign the layout, import the
# api's access key, create the bucket and grant the key on it. Every step
# checks first, so re-running on every `docker compose up` changes nothing.
set -eu

: "${S3_BUCKET:?}" "${S3_ACCESS_KEY_ID:?}" "${S3_SECRET_ACCESS_KEY:?}"

# The CLI reads the node's id from the shared metadata volume and reaches the
# daemon at rpc_public_addr; wait until it answers.
tries=0
until garage status >/dev/null 2>&1; do
	tries=$((tries + 1))
	[ "$tries" -lt 30 ] || { echo "garage-init: garage never answered" >&2; exit 1; }
	sleep 1
done

if garage layout show | grep -q 'No nodes currently have a role'; then
	node_id=$(garage node id -q | cut -d@ -f1)
	garage layout assign -z local -c 1G "$node_id"
	garage layout apply --version 1
	echo "garage-init: layout applied"
fi

if ! garage key info "$S3_ACCESS_KEY_ID" >/dev/null 2>&1; then
	garage key import --yes -n rakin-api "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY"
	echo "garage-init: key imported"
fi

if ! garage bucket info "$S3_BUCKET" >/dev/null 2>&1; then
	garage bucket create "$S3_BUCKET"
	echo "garage-init: bucket $S3_BUCKET created"
fi

garage bucket allow --read --write --owner "$S3_BUCKET" --key "$S3_ACCESS_KEY_ID" >/dev/null
echo "garage-init: bucket $S3_BUCKET ready for key $S3_ACCESS_KEY_ID"
