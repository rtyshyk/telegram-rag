# UI Agent Guide

Project: telegram-rag UI (Astro + React)

## Purpose
- Frontend for RAG chat and search UI.
- Authenticates against API via cookie session.
- Queries API for models and search results.

## Stack
- Astro 4 + React 18 + TailwindCSS.
- Unit tests: Vitest + Testing Library.
- E2E tests: Playwright.
- Dockerized for deployment.

## Key Files
- `ui/src/lib/api.ts`: API client. Uses `PUBLIC_API_URL` and includes fetch timeouts and 401 redirect to `/login`.
- `ui/src/components/ProtectedApp.tsx`: Main chat UI with search context panel and message composer.
- `ui/src/components/ModelPicker.tsx`: Fetches `/models` from API.
- `ui/src/pages/login.astro`: Login page using `login()` API.
- `ui/src/pages/app.astro`: Protected app shell that renders React app.
- `ui/Dockerfile`: Container image for production.
- Tests: `ui/tests/e2e/*.spec.ts`, `ui/src/components/*.spec.tsx`.

## Environment
- `PUBLIC_API_URL`: Required for API base URL (e.g. `http://localhost:8000`). The value is injected at build/runtime by Astro env and must not end with a trailing slash.

## Development
- Dev server: `astro dev` (port 4321). Preview: `astro preview`.
- API calls use `credentials: 'include'` expecting cookie `rag_session` from API.
- Search panel calls `POST /search` with optional `chat_id`, `thread_id`, `hybrid`.

## Testing (VS Code UI only)
- Unit tests: run via VS Code Vitest extension/integration (do not use `npm test` in terminal).
- E2E tests: run via VS Code Playwright Test integration.
- Keep tests deterministic; avoid network calls in unit tests.

## Coding Standards
- Follow repository-wide AGENTS.md. Run `pre-commit run --all-files` after changes.
- Prefer small, focused components. Keep state local in `ProtectedApp` unless shared.
- Surface user-friendly messages, never swallow 401—redirect to `/login`.
- Accessibility: basic aria roles and keyboard handling for inputs and buttons.

## Adding Features
- New API calls: add to `src/lib/api.ts` with timeout and credentials, and export typed helpers.
- New pages/components: colocate tests (`.spec.tsx`) next to components when practical.
- Model/config pickers: read-only from `/models`; avoid mutating server state from UI unless specified.

## Docker
- `ui/Dockerfile` builds a static site served by Astro preview or a chosen server. Ensure proper base path if behind proxy.

## Common Pitfalls
- Missing `PUBLIC_API_URL` leads to network calls against empty base; guard with runtime checks when wiring new features.
- CORS: API must include the UI origin; use `UI_ORIGIN` in API settings or `cors_allow_all=true` for local dev.

