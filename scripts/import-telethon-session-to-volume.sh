#!/usr/bin/env sh
# Copy a host Telethon session into the telethon_session Docker volume (one-time migration).
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$ROOT/indexer/sessions/telethon.session}"

if [ ! -f "$SRC" ]; then
	echo "Session file not found: $SRC" >&2
	echo "Run the indexer once with QR login, or pass the path to telethon.session." >&2
	exit 1
fi

cd "$ROOT"
docker compose run --rm --no-deps \
	-v "$SRC:/from/telethon.session:ro" \
	--entrypoint sh \
	indexer \
	-c 'cp /from/telethon.session /sessions/telethon.session && chmod 600 /sessions/telethon.session'

echo "Imported $(basename "$SRC") into telethon_session volume."
