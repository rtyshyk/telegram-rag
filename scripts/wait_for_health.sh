#!/usr/bin/env bash
set -euo pipefail

RETRIES=${RETRIES:-30}

wait_for() {
	local name=$1
	local url=$2
	local count=0
	until curl -fsS "$url" >/dev/null; do
		count=$((count + 1))
		if [[ $count -ge $RETRIES ]]; then
			echo "$name did not become healthy" >&2
			exit 1
		fi
		sleep 1
	done
	echo "$name is up"
}

wait_for "API" "http://localhost:8000/healthz"
wait_for "UI" "http://localhost:3000/"
wait_for "Vespa" "http://localhost:19071/ApplicationStatus"

docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-postgres}" >/dev/null

echo "Postgres is up"
