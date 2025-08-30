# API Agent Guide

Project: telegram-rag API (FastAPI)

## Purpose
- Auth, models listing, and Vespa-backed search for the UI.
- Issues JWT-based session cookie and enforces auth on protected routes.

## Architecture
- FastAPI app with middleware:
  - `AuthMiddleware` (innermost): protects all endpoints except `/healthz` and `/auth/login` using `rag_session` cookie (HS256 JWT).
  - `CORSMiddleware` (outermost): configured via `settings.ui_origin` or `cors_allow_all`.
- Search client: `VespaSearchClient` performs hybrid (vector+BM25) search against Vespa; embeddings via OpenAI.

## Key Endpoints
- `GET /healthz`: Health check (must return `{status: "ok", service: "api"}`).
- `POST /auth/login`: Validates credentials, returns `{ok: true}` and sets `rag_session` cookie.
- `POST /auth/logout`: Clears cookie and returns `{ok: true}`.
- `GET /models`: Returns available model options for UI picker.
- `POST /search`: Accepts `SearchRequest` and returns ranked results.

## Important Files
- `api/app/main.py`: App wiring, middleware, and endpoints.
- `api/app/auth.py`: Password verification (bcrypt), JWT create/decode, rate limiting, and middleware.
- `api/app/search.py`: Vespa client, embedding provider, request/response models, YQL builder.
- `api/app/settings.py`: Typed settings (Pydantic v2) with defaults.
- Tests: `api/tests/*.py` (auth, cors, search).

## Settings (env)
- `APP_USER` / `APP_USER_HASH_BCRYPT` / `SESSION_SECRET` (required for auth).
- `SESSION_TTL_HOURS` (default 24).
- `LOGIN_RATE_MAX_ATTEMPTS` (default 5), `LOGIN_RATE_WINDOW_SECONDS` (default 900).
- `UI_ORIGIN` (e.g. `http://localhost:4321`), `CORS_ALLOW_ALL` (bool).
- `VESPA_ENDPOINT` (default `http://vespa:8080`).
- `OPENAI_API_KEY` (required for hybrid search), `EMBED_MODEL` (`text-embedding-3-large|small`).

## Search Behavior
- Hybrid search tries embedding and falls back to BM25 on failure.
- Model determines vector field and ranking profile:
  - `text-embedding-3-small` → `vector_small` + `hybrid-small` (dims 1536)
  - otherwise → `vector_large` + `hybrid-large` (dims 3072)

## Testing (VS Code UI only)
- Use VS Code Python Test integration to run `api/tests` (pytest).
- Do not run `pytest` from terminal.

## Coding Standards
- Type hints everywhere; async I/O where applicable.
- Return structured JSON with `{ok: boolean}` for data endpoints when suitable.
- Timeouts and error logging around external calls (OpenAI, Vespa).
- Keep auth and CORS middleware ordering intact: Auth first, CORS last.

## Adding Endpoints
- Define Pydantic request/response models.
- Validate inputs and handle auth via middleware.
- Add tests under `api/tests/` and update docs.

