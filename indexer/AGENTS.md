# Indexer Agent Guide

Project: telegram-rag Indexer (Python)

## Purpose

- Ingest Telegram messages, normalize/chunk, embed text, and feed documents to Vespa.
- Maintains local DB for state, caching, and metrics.

## Architecture

- Modules:
  - `settings.py`: Pydantic settings for OpenAI, Telegram, DB, Vespa, chunking.
  - `telethon_client.py`: Telegram client abstraction and fetch utilities.
  - `normalize.py`: Text cleanup and normalization.
  - `chunker.py`: Token-aware chunking with overlap and reply-context support.
  - `embedder.py`: OpenAI embedding with caching, batching, concurrency, budget checks, and retries.
  - `db.py`: Database access layer (caching embeddings and state).
  - `vespa_client.py`: Feed/delete documents, health checks, concurrency, retries with backoff.
  - `models.py`: Typed data models (e.g., `VespaDocument`, caches, metrics).
  - `main.py`: CLI entry and pipeline orchestration.

## Document Identity

- Vespa document id format: `{chat_id}:{message_id}:{chunk_idx}:v{chunking_version}`.
- Fields include metadata such as `sender`, `sender_username`, `message_date`, `source_title`, `chat_type`, `has_link`.
- Vector fields: `vector_small` (1536 dims) and/or `vector_large` (3072 dims) depending on model.

## Settings (env)

- OpenAI: `OPENAI_API_KEY`, `EMBED_MODEL` (default `text-embedding-3-large`), `EMBED_DIMENSIONS`, `EMBED_BATCH_SIZE`, `EMBED_CONCURRENCY`.
- Telegram: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `TELETHON_SESSION_PATH` (default `/sessions/telethon.session`).
- Storage: `DATABASE_URL`.
- Vespa: `VESPA_ENDPOINT` (default `http://vespa:8080`).
- Chunking: `CHUNKING_VERSION`, `PREPROCESS_VERSION`, `REPLY_CONTEXT_TOKENS`, `TARGET_CHUNK_TOKENS`, `CHUNK_OVERLAP_TOKENS`.
- Budget/Backoff: `DAILY_EMBED_BUDGET_USD`, `BACKOFF_BASE_MS`, `BACKOFF_MAX_MS`.

## Error Handling & Reliability

- Embedding and feeding use retries with exponential backoff; metrics recorded in `IndexerMetrics`.
- Cost guard: raises on budget exceedance when estimate >= budget.
- HTTP clients use reasonable timeouts and connection limits.

## Testing (VS Code UI only)

- Run `indexer/tests` with VS Code Python Test integration (pytest).
- Unit tests cover chunking, normalization, DB, embedder, vespa client, Telethon client.
- No terminal test commands.

## Coding Standards

- Follow repository-wide AGENTS.md. Run `pre-commit run --all-files` after changes.
- Keep IO async; pass DB and clients explicitly for testability.
- Avoid leaking mocks into settings; coerce values where necessary (see `Embedder`).

## Adding Pipelines/Fields

- Extend `models.VespaDocument` and update `vespa_client.feed_document` mapping.
- Keep compatibility with UI search display fields used in API responses.
- Update tests for new fields and behaviors.

## Docker

- `indexer/Dockerfile` for containerized execution. Ensure sessions volume is mounted read-write for Telethon.
