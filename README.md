# Telegram RAG Chat

Self-hosted retrieval-augmented generation stack for searching and chatting over your personal Telegram history. The project ships with ingestion, hybrid retrieval, and an authenticated UI; everything runs locally via Docker Compose.

## Highlights

- Index DMs, groups, channels, and Saved Messages with Telethon and store content in Postgres
- Hybrid Vespa retrieval (vector + BM25 + recency) with optional Cohere rerank
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
- OpenAI API key (for embeddings/LLM)
- Optional: Cohere API key for reranking

## Setup

1. Clone and configure the repository:
   ```bash
   git clone <repo> telegram-rag
   cd telegram-rag
   cp .env.example .env
   ```
2. Edit `.env` with your credentials. Required values include `APP_USER`, `APP_USER_HASH_BCRYPT`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `OPENAI_API_KEY`. Optional keys such as `COHERE_API_KEY` enable reranking.
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

### Development

```bash
docker compose up -d api vespa postgres indexer vespa-deploy
(cd ui && npm run dev)
```

- UI: http://localhost:4321 (development server)
- API: http://localhost:8000 (health probe at `/healthz`)
- Vespa status: http://localhost:19071/ApplicationStatus

### Production-like

```bash
docker compose up -d --build
```

The `vespa-deploy` service waits for Vespa to become healthy and then pushes `vespa/application` automatically.

## Indexing Telegram Data

- First full sync: `docker compose run --rm indexer python main.py --once`
- Target specific chats/dates (example):
  ```bash
  docker compose run --rm indexer python main.py --once \
    --chats '<Saved Messages>' --days 30 --limit-messages 50
  ```
  The daemon keeps running inside the `indexer` service to capture edits and deletions.

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
- **Empty search results**: verify Vespa deployment (`docker compose logs vespa-deploy`) and that embeddings populated successfully.
- **Rerank skipped**: set `COHERE_API_KEY` and `RERANK_ENABLED=true`.

## Security & Privacy

- Single-user authentication backed by bcrypt; cookies are HTTP-only.
- Secrets stay in `.env` and are never committed. Copy `.env.example` as a starting point.
- Telethon sessions and Postgres data live on Docker volumes you control.
- If exposing the stack, front it with TLS termination and consider IP allow-listing.

## TODO

- Implement Cohere rerank integration across the API and UI. Environment placeholders (`COHERE_API_KEY`, `RERANK_ENABLED`) and documentation references exist, but no reranking client or request path is wired up yet.

## Supporting Scripts

- `./scripts/wait_for_health.sh` - wait until API and Vespa report healthy
- `./scripts/deploy-vespa.sh` - redeploy the Vespa package manually
- `./scripts/smoke_tests.sh` - basic functional checks against a running stack

For additional implementation details, browse the relevant module directories noted above.
