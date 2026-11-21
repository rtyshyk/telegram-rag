#!/usr/bin/env bash
# Run one-shot indexing without fighting the daemon for the Telethon SQLite session.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Stopping indexer daemon (if running) to release Telethon session…"
docker compose stop indexer 2>/dev/null || true

echo "Stopping stray one-shot indexer containers…"
while IFS= read -r cid; do
	if [[ -n $cid ]]; then
		docker stop "$cid" 2>/dev/null || true
	fi
done < <(docker ps -q --filter "name=indexer" 2>/dev/null || true)

# Pause so SQLite on the shared volume can release locks from stopped containers.
sleep 5

exec docker compose run --rm --build indexer python main.py --once "$@"
