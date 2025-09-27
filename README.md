# Telegram RAG Chat

Personal, Dockerized RAG system for searching and chatting with your Telegram message history.

## Features

- **Phase 1**: Web app with hybrid search (BM25 + vector similarity)
- **Phase 2**: Telegram indexing with chunking and embeddings
- **Phase 3**: Production-ready hybrid search pipeline
- **Phase 4**: RAG Chat with Citations ✨ **NEW**

### Phase 4 - RAG Chat

The latest addition provides AI-powered question answering using your indexed Telegram data:

- **Grounded responses**: AI answers strictly from your Telegram messages
- **Citation tracking**: Each statement links back to specific messages
- **Smart context assembly**: Automatically selects and compresses relevant chunks
- **Model selection**: Choose between GPT models via UI
- **Rate limiting**: Built-in protection against excessive usage
- **Real-time search**: Live search results as you type

**Auto-deploy Vespa `application.zip` on container start; fail fast on schema mismatch**

## Commands

### Indexing

Index chat messages:

```
# Index all available chats (full history)
docker compose run --build --rm indexer python main.py --once

# Index specific chats only (limit to last 30 days)
docker compose run --build --rm indexer python main.py --once --chats '<Saved Messages>' --days 30 --limit-messages 50
```

### Chat API

The chat endpoint provides RAG-powered question answering:

```bash
# Basic chat request
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  -d '{"q":"What database connection string did we agree on?","k":12}'

# With filters and model selection
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  -d '{
    "q": "How do we handle authentication?",
    "k": 15,
    "model_label": "gpt 5",
    "filters": {
      "chat_ids": ["-123456789"],
      "date_from": "2025-08-01"
    },
    "debug": true
  }'
```

**Response format:**

```json
{
  "answer": "Use postgres://user:pass@db:5432/app [1]\n\nSources:\n[1] Work Chat — 2025-08-12 09:41 — message 7741",
  "citations": [
    {
      "id": "msg:7741:0",
      "chat_id": "-123456789",
      "message_id": 7741,
      "chunk_idx": 0,
      "source_title": "Work Chat",
      "message_date": 1723452060
    }
  ],
  "usage": {
    "prompt_tokens": 1812,
    "completion_tokens": 112,
    "total_tokens": 1924
  },
  "timing_ms": 2105
}
```

---

## Architecture

````
[indexer]  ── Telethon daemon/--once → chunk → cache → OpenAI embed → Vespa upsert
     │
     ├── Postgres (sync_state, embedding_cache, chunks)
     └── Tele---

## Troubleshooting

### Vespa Deployment

The Vespa application is **automatically deployed** when you run `docker compose up`. If you need to manually redeploy:

```bash
# Manual deployment using the deployment script
./scripts/deploy-vespa.sh

# Or deploy from a running container
docker run --rm --network telegram-rag_default \
  -v $(pwd)/vespa/application:/app/application:ro \
  alpine/curl:latest sh -c "
    apk add --no-cache zip jq bash &&
    cd /app &&
    zip -r application.zip application/ &&
    curl -sf --data-binary @application.zip \
      http://vespa:19071/application/v2/tenant/default/prepareandactivate
  "

# Check deployment status
curl -s http://localhost:19071/ApplicationStatus | jq -r '.application.meta.generation'
````

### Common Issues

- **Can't login** → verify `APP_USER` and `APP_USER_HASH_BCRYPT`; check time drift for cookie expiry.
- **Indexer stalls** → confirm Telethon session exists on volume; check rate-limit backoff logs.
- **No search results** → ensure Vespa app deployed (container logs) and embeddings present.
- **Rerank skipped** → set `COHERE_API_KEY` and `RERANK_ENABLED=true`.
- **Vespa deployment fails** → check `docker compose logs vespa-deploy` for errors; verify application package structure.

---ion (on a Docker volume)

[api] FastAPI ── /search → Vespa hybrid
/chat → retrieve → (optional rerank) → compress → LLM answer + citations
/auth, /models, /chats

[ui] Astro+React ─ login, filters, search, ask AI (stores model label in localStorage)

[vespa-deploy] ── Auto-deploy Vespa application package on startup

```

---ed Generation) over **your Telegram**: index private DMs, groups, channels, and Saved Messages, then search or chat over them via a lightweight web UI.

- **Ingestion & API:** Python (Telethon + FastAPI)
- **UI:** Astro + React
- **Retrieval:** Vespa (hybrid vector + BM25 + recency)
- **State & cache:** Postgres
- **LLM & embeddings:** OpenAI (optional rerank via Cohere)
- **Everything in Docker Compose**

> **Privacy note:** This indexes only your account’s content. v1 ignores media (no OCR/ASR) and does not crawl external links. You own the data volumes.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Directory layout](#directory-layout)
- [Design specifics](#design-specifics)
- [API quick reference](#api-quick-reference)
- [Testing & quality](#testing--quality)
- [Roadmap & acceptance (MVP stages)](#roadmap--acceptance-mvp-stages)
- [Agent prompt (Codex)](#agent-prompt-codex)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- Index all Telegram messages (DMs, groups, channels, Saved Messages)
- Web UI with secure login (bcrypt hash in env)
- Hybrid search (vector + BM25) with recency sort
- Chat/RAG answers with in-line citations (chat, date, deep link)
- Smart chunking with reply/forward/thread context
- Embedding cache & idempotent upserts (no re-embedding unchanged text)
- Filters: chat(s) multi-select, sender, type, date range, `has_link`, sort by recency
- Optional **rerank** with Cohere Rerank v3 (auto-skip if no key)
- Dry-run cost estimate, backoff/retries, consistency sweep
- Auto-deploy Vespa `application.zip` on container start; fail fast on schema mismatch

---

## Architecture

```

[indexer] ── Telethon daemon/--once → chunk → cache → OpenAI embed → Vespa upsert
│
├── Postgres (sync_state, embedding_cache, chunks)
└── Telethon .session (on a Docker volume)

[api] FastAPI ── /search → Vespa hybrid
/chat → retrieve → (optional rerank) → compress → LLM answer + citations
/auth, /models, /chats

[ui] Astro+React ─ login, filters, search, ask AI (stores model label in localStorage)

````

---

## Quick start

### 1) Prerequisites

- Docker & Docker Compose
- Your Telegram **API ID/HASH** and phone (for user login)
- OpenAI API key
- (Optional) Cohere API key for rerank

### 2) Clone & configure

```bash
git clone <your-repo-url> telegram-rag
cd telegram-rag
cp .env.example .env

# Set up development tools (recommended)
brew install pre-commit  # or pip install pre-commit
pre-commit install       # Install git hooks for code formatting
```

Edit `.env` (see [Environment variables](#environment-variables)).

### 3) Run the stack

**For Development (Recommended):**
```bash
# Start backend services
docker compose up -d api vespa postgres indexer vespa-deploy

# Start UI in development mode (separate terminal)
cd ui && npm install && npm run dev

# Verify everything works
./scripts/wait_for_health.sh     # optional helper
./scripts/smoke_tests.sh         # optional simple checks
```

**For Production/Testing:**
```bash
docker compose up -d --build
./scripts/wait_for_health.sh     # optional helper
./scripts/smoke_tests.sh         # optional simple checks
```

The Vespa application will be **automatically deployed** when the stack starts. The `vespa-deploy` service waits for Vespa to be healthy and then deploys the application package.

- UI: http://localhost:4321 (development) or http://localhost:3000 (production)
  - Login at `/login` (username/password from `.env`)
- API health: http://localhost:8000/healthz
- Vespa: http://localhost:19071/ApplicationStatus (example)

### 4) First backfill

```bash
docker compose exec indexer python main.py --once
```

This runs a one-shot sync. The **daemon** runs continuously to pick up edits/deletes.

---

**Generate bcrypt hash** (example):

```bash
python - <<'PY'
import bcrypt; print(bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode())
PY
```

---

## Directory layout

```
/api               # FastAPI app (auth, search, chat, models)
/indexer           # Telethon daemon + --once backfill
/ui                # Astro + React UI
/vespa/application # Vespa application package (schemas, services, etc.)
/scripts           # Deployment and utility scripts
  ├─ deploy-vespa.sh      # Automated Vespa deployment script
  ├─ wait_for_health.sh   # Health check helper
  ├─ smoke_tests.sh       # Basic functionality tests
  └─ setup-github-mcp.sh  # GitHub MCP integration setup
/.github
  └─ copilot-instructions.md  # GitHub Copilot development guidelines
/tests
  ├─ api/          # pytest
  ├─ indexer/      # pytest
  ├─ vespa/        # retrieval golden tests
  └─ ui-e2e/       # Playwright
.pre-commit-config.yaml   # Code formatting & linting hooks
docker-compose.yml
Dockerfile.vespa-deploy  # Vespa deployment container
mcp-config.json          # GitHub MCP server configuration
.env.example
```

> **Note:** The Telethon `.session` file is persisted on a Docker volume (not baked into images).

---

## Design specifics

### Chunking

- ~800–1200 tokens, ~15% overlap, message-aware (don’t split inside code/links)
- Prepend: `[YYYY-MM-DD HH:mm • @sender]`
- **Composed chunk:** `trim(reply_context to N tokens) + "——" + main_message`
- Metadata: `reply_to_message_id`, `forward_from`, `thread_id`, `has_link`

### What is **ignored** in v1

- Media content: **voice messages, images, documents**
- Web page fetching/crawling, OCR, ASR

### Retrieval & ranking

- Vespa first-phase rank (example):
  `1.6 * closeness(vector) + 0.9 * bm25(text) + 0.3 * bm25(exact_terms) + recency_decay(message_date) + thread_boost`
- Sort toggle: **relevance** vs **recency**
- Optional rerank: **Cohere Rerank v3** (if key present)

---

## API quick reference

Auth cookie is HTTP-only (login first).

```bash
# Login
curl -i -X POST http://localhost:8080/auth/login   -H 'Content-Type: application/json'   -d '{"username":"admin","password":"<your-password>"}'

# List models (UI labels → OpenAI IDs from env)
curl -b cookies.txt -c cookies.txt http://localhost:8080/models

# Search
curl -b cookies.txt -X POST http://localhost:8080/search   -H 'Content-Type: application/json'   -d '{
    "q": "ssh key from last week",
    "k": 12,
    "filters": {
      "chat_ids": ["123456789"],
      "date_from": "2025-08-01",
      "date_to": "2025-08-18"
    },
    "sort": "recency"
  }'

# Chat (RAG)
curl -b cookies.txt -X POST http://localhost:8080/chat   -H 'Content-Type: application/json'   -d '{
    "q": "Send me the Postgres connection string we discussed",
    "k": 12,
    "model_label": "gpt 5",           // or "gpt5 mini", "gpt5 nano"
    "filters": { "chat_ids": ["..."] },
    "rerank": true
  }'
```

---

## Development Workflow

### Quick Start (Recommended)

For fast development with live reloading:

1. **Start backend services (API, Vespa, Postgres, Indexer):**
   ```bash
   # Start all services except UI
   docker compose up -d api vespa postgres indexer vespa-deploy
   ```

2. **Start UI in development mode:**
   ```bash
   cd ui && npm install && npm run dev
   ```

   The UI will be available at http://localhost:4321 with live reloading.

3. **Verify everything is working:**
   ```bash
   ./scripts/wait_for_health.sh     # Wait for all services
   ./scripts/smoke_tests.sh         # Test functionality
   ```

### Full Stack (Production-like)

To run everything in containers:

```bash
docker compose up -d --build
./scripts/wait_for_health.sh     # optional helper
./scripts/smoke_tests.sh         # optional simple checks
```

**Services:**
- **UI**: http://localhost:3000 (containerized) or http://localhost:4321 (development)
- **API**: http://localhost:8000
- **Vespa**: http://localhost:19071
- **Login**: username `admin`, password `password`

### Code Quality (MANDATORY)

**After implementing ANY feature, bug fix, or code change, you MUST run formatting and linting tools:**

```bash
# Always run before committing
pre-commit run --all-files
```

---

## Testing & quality

**Pre-commit hooks & Code formatting**

All code is automatically formatted and linted using pre-commit hooks:

```bash
# Install pre-commit (one-time setup)
brew install pre-commit  # or pip install pre-commit

# Install hooks for this repository
pre-commit install

# Run hooks manually on all files
pre-commit run --all-files

# Run specific hooks
pre-commit run black        # Python formatting
pre-commit run prettier     # Markdown/JSON formatting
pre-commit run shfmt        # Shell script formatting
```

**VS Code Integration:**

Pre-commit hooks can be run directly from VS Code using tasks:

- **Command Palette**: `Ctrl+Shift+P` → "Tasks: Run Task" → "Pre-commit: Run all hooks"
- **Keyboard Shortcut**: `Cmd+Shift+P` (macOS) to run all hooks
- **Available Tasks**:
  - `Pre-commit: Run all hooks` - Run all hooks on all files
  - `Pre-commit: Run on staged files` - Run hooks only on staged files
  - `Pre-commit: Run specific hook (black)` - Run only Python formatting
  - `Pre-commit: Run specific hook (prettier)` - Run only JS/TS/Markdown formatting
  - `Pre-commit: Install hooks` - Install pre-commit hooks

**Hooks configured:**
- `black` - Python code formatting
- `prettier` - Markdown, JSON, YAML formatting
- `shfmt` - Shell script formatting

**Python (Indexer + FastAPI)**

- `pytest`, `pytest-asyncio`, `httpx.AsyncClient` for API tests
- Type & security: `mypy`, `ruff` (lint/format), `bandit`, `pip-audit`
- Env-driven stubs for deterministic CI:
  - `OPENAI_STUB=1` → deterministic 3072-dim vector from SHA256(text)
  - `COHERE_STUB=1` → simple overlap score
  - `TELETHON_STUB=1` → synthetic stream of chats/messages/edits/deletes

**Vespa (Hybrid retrieval)**

- Build `application.zip` in CI; boot test container; `prepare/activate`
- Golden queries (10–20) over seeded fixtures; assert **hit@5 / MRR** minimums; verify filters and recency sort

**UI (Astro + React)**

- Unit: `vitest` + Testing Library; mock API with `msw`
- E2E: `playwright` against docker-compose (login → filter → search → chat answer with citations)

**Infra & linters**

- `eslint`, `prettier`, `hadolint`, `yamllint`, `gitleaks`
- **Coverage gates:** Python ≥ **85%**, UI ≥ **80%**

---

## Roadmap & acceptance (MVP stages)

1. **Stage 0 — Repo & Compose**
   Stack boots; Vespa auto-deploys `application.zip`; API `/healthz` 200; UI shell loads.

2. **Stage 1 — Auth & Models**
   Login w/ bcrypt from env; cookie session; rate-limited; UI model picker (saved to localStorage).

3. **Stage 2 — Ingestion**
   Telethon daemon + `--once`; Postgres migrations; chunker; embedding cache; edits/deletes handled; dry-run cost.

4. **Stage 3 — Search**
   Vespa hybrid query + filters; recency sort; UI search with filters; performance stable.

5. **Stage 4 — Chat/RAG**
   Retrieve → compress → LLM answer with citations; token/latency logs; no history.

6. **Stage 5 — Rerank (optional)**
   Cohere v3 rerank when key present; guardrails to skip if strong signals; measured improvement on golden set.

7. **Stage 6 — Consistency & Ops**
   7-day consistency sweep; weekly purge; backoff with jitter; optional daily budget guard.

## Security

- Single-user auth with **bcrypt** hash in env, session as **HTTP-only** cookie
- Login rate-limit; avoid logging message bodies by default (redacted debug mode)
- Telethon session stored on volume; **never** commit secrets; use `.env` & `.env.example`
- If exposing publicly: terminate TLS at reverse proxy and consider IP allow-list

---

## Troubleshooting

- **Can’t login** → verify `APP_USER` and `APP_USER_HASH_BCRYPT`; check time drift for cookie expiry.
- **Indexer stalls** → confirm Telethon session exists on volume; check rate-limit backoff logs.
- **No search results** → ensure Vespa app deployed (container logs) and embeddings present.
- **Rerank skipped** → set `COHERE_API_KEY` and `RERANK_ENABLED=true`.2

---

### Why these choices?

- **Python + Telethon**: reliable Telegram ingestion & async batching
- **Vespa**: first-class hybrid ranking and recency boosting
- **Postgres**: safe concurrency & migrations
- **Astro + React**: simple, fast UI with minimal state
- **OpenAI**: excellent multi-lingual embeddings & models; optional Cohere rerank
````
