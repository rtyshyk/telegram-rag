# Telegram RAG Chat

Self-hosted retrieval-augmented generation stack for searching and chatting over your personal Telegram history. The project ships with ingestion, hybrid retrieval, and an authenticated UI; everything runs locally via Docker Compose.

## Highlights

- Index DMs, groups, channels, and Saved Messages with Telethon and store content in Postgres
- Hybrid Vespa retrieval (vector + BM25 + recency) with optional VoyageAI rerank
- Chat workflow that compresses context, answers strictly from your data, and returns citations
- Astro + React interface with login, filters, live search results, and model selection
- Docker-first deployment with automatic Vespa package activation on startup

## System Architecture

```
[indexer] Telethon daemon or one-shot -> chunk -> cache -> OpenAI embed -> Vespa upsert
  |-- Postgres (sync state, embedding cache, chunks)
  `-- Telethon session persisted on Docker volume

[api] FastAPI -> /auth, /models, /search, /chat (LLM answer + citations)
[ui]  Astro + React -> login, filters, hybrid search, chat
[vespa] Hybrid retrieval + recency boosting (auto-deployed on startup)
```

## Prerequisites

- Docker and Docker Compose
- Telegram API ID + hash and a phone number for login
- OpenAI API key or Nebius Token Factory key (OpenAI-compatible API for embeddings and chat)
- Optional: VoyageAI API key for reranking

## Setup

1. Clone and configure the repository:
   ```bash
   git clone <repo> telegram-rag
   cd telegram-rag
   cp .env.example .env
   ```
2. Edit `.env` with your credentials. Required values include `APP_USER`, `APP_USER_HASH_BCRYPT`, `TG_API_ID`, `TG_API_HASH`, and `OPENAI_API_KEY`. On first indexer run, log in by scanning the QR code in Telegram (**Settings → Devices → Link Desktop Device**); the session is stored in the `telethon_session` volume. For [Nebius Token Factory](https://tokenfactory.nebius.com), set `OPENAI_BASE_URL=https://api.tokenfactory.nebius.com/v1/`, use your Token Factory API key as `OPENAI_API_KEY`, and align `EMBED_MODEL` / `EMBED_DIMENSIONS` with your Vespa index (for Nebius use `Qwen/Qwen3-Embedding-8B` with `EMBED_DIMENSIONS=1536` for `vector_small`). Chat models in the UI are loaded live from the provider; optional keys such as `VOYAGE_API_KEY` enable reranking.
3. Install local tooling (recommended for contributors):
   ```bash
   make install        # api + indexer dependencies
   make ui-install     # ui dependencies
   pre-commit install  # enable formatting/lint hooks
   ```

To generate a bcrypt hash for the login password:

```bash
python - <<'PY'
import bcrypt; print(bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode())
PY
```

## Running the Stack

### Postgres (shared vs local)

- **Shared Postgres:** run sibling `../common-infra/pg` (`docker compose up -d`), provision with `scripts/provision-role.sh`, set `DATABASE_URL` to host `common-pg` (see `.env.example`). Run `docker compose up -d --build` — the in-repo `postgres` service is omitted unless you use the profile below.
- **Local Postgres in this repo:** `docker compose --profile personal-db up -d --build` and point `DATABASE_URL` at host `postgres` (commented line in `.env.example`).
- **`scripts/wait_for_health.sh`** checks the DB with `pg_isready` on the local compose `postgres` when it is running; otherwise it uses `DATABASE_URL` from the environment or from `.env` (sourced by the script).

### Development

Start `../common-infra/pg` first. `.env` `DATABASE_URL` uses host `common-pg`.

```bash
docker compose up -d api vespa indexer vespa-deploy
(cd ui && npm run dev)
```

- UI: http://localhost:4321 (development server)
- API: http://localhost:8000 (health probe at `/healthz`)
- Vespa status: http://localhost:19071/ApplicationStatus

### Production-like

```bash
docker compose up -d --build
```

Use `--profile personal-db` if your `.env` targets host `postgres` inside this project. The `vespa-deploy` service waits for Vespa to become healthy and then pushes `vespa/application` automatically.

## Indexing Telegram Data

### Caveats & indexing modes

- **Near-live daemon**: `python main.py` (no `--once`) attaches Telethon event handlers, replays the last few minutes on startup/reconnect, and streams new messages into Vespa.
- **Initial backfill**: progress is checkpointed per chat in `/sessions/backfill_state.json` (override with `--backfill-state-path`). The daemon resumes from the last stored `message_id` automatically.
- **Hourly sweep**: by default the daemon re-scans the last 7 days every 60 minutes to catch late edits; tune with `--hourly-sweep-days` and `--hourly-sweep-interval-minutes`.
- Telegram deletions are intentionally ignored—once ingested, messages remain searchable to preserve historical context.

**Normal operation:** `docker compose up -d` runs the indexer daemon. Set `INDEXER_CHATS` and `INDEXER_INCREMENTAL_DAYS` in `.env` (empty `INDEXER_CHATS` indexes all chats). On first start the daemon backfills, then streams new messages.

**First Telegram login** (no session in the `telethon_session` volume yet): `./scripts/indexer-once.sh` (interactive terminal for QR or phone code and 2FA). When signed in, stop that run and use `docker compose up` for the daemon.

**One-shot backfill or dry-run** (with the daemon stopped): `./scripts/indexer-once.sh` with optional flags, e.g.:

```bash
./scripts/indexer-once.sh --chats @example --days 365 --dry-run
```

Read the final log block: messages scanned, chunks, embedding tokens, and estimated USD.

- Example one-shot with a message cap:
  ```bash
  ./scripts/indexer-once.sh --chats '<Saved Messages>' --days 30 --limit-messages 50
  ```

Common daemon tuning flags:

- `--daemon-lookback-minutes` (default 5) — replay window on startup/reconnect.
- `--lookback-message-limit` (default 250) — cap per-chat catch-up volume.
- `--backfill-checkpoint-interval` (default 50) — persist JSON progress every N messages.

## API & UI Usage

- Login at `/login` using the credentials from `.env`; an HTTP-only session cookie is issued.
- Core endpoints: `/models`, `/search`, and `/chat`. See `api/` for request/response schemas.
- Model labels shown in the UI map to OpenAI IDs defined in the environment variables (e.g., `gpt-5`, `gpt-5-mini`).

## Testing & Quality

- Format and lint before committing: `make precommit` or `pre-commit run --all-files`
- Python tests (api + indexer): `make test-python`
- UI unit tests: `make test-ui`
- UI end-to-end tests: `make test-ui-e2e`
- Optional smoke checks against a running stack: `./scripts/smoke_tests.sh`

## Directory Layout

```
api/                FastAPI service (auth, models, search, chat)
indexer/            Telethon ingestion, chunking, embeddings, Vespa upserts
ui/                 Astro + React front-end
vespa/application/  Vespa schemas and services (auto-deployed)
scripts/            Helpers: deploy-vespa.sh, wait_for_health.sh, smoke_tests.sh
```

## Troubleshooting

- **Cannot log in**: confirm `APP_USER` and `APP_USER_HASH_BCRYPT`; check system clock for cookie expiry.
- **Indexer stalled**: ensure the Telethon `.session` file exists on the Docker volume and inspect `docker compose logs indexer` for rate limiting.
- **`sqlite3.OperationalError: database is locked` on Telethon connect** (common on Docker Desktop for Mac): use the `telethon_session` Docker volume in `docker-compose.yml`, not a bind mount of `indexer/sessions`. One-time migration: `./scripts/import-telethon-session-to-volume.sh`. Do not run the indexer daemon and `./scripts/indexer-once.sh` at the same time.
- **Empty search results**: verify Vespa deployment (`docker compose logs vespa-deploy`) and that embeddings populated successfully.
- **Rerank skipped**: set `VOYAGE_API_KEY` and `RERANK_ENABLED=true`.

## Security & Privacy

- Single-user authentication backed by bcrypt; cookies are HTTP-only.
- Secrets stay in `.env` and are never committed. Copy `.env.example` as a starting point.
- Telethon sessions and Postgres data live on Docker volumes you control.
- If exposing the stack, front it with TLS termination and consider IP allow-listing.

## Supporting Scripts

- `./scripts/wait_for_health.sh` - wait until API and Vespa report healthy
- `./scripts/deploy-vespa.sh` - redeploy the Vespa package manually
- `./scripts/smoke_tests.sh` - basic functional checks against a running stack

For additional implementation details, browse the relevant module directories noted above.
