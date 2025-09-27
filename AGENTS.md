# Repository Guidelines

## Project Structure & Modules

- `api/`: FastAPI service (`/auth`, `/models`, `/search`, `/chat`).
- `indexer/`: Telethon ingestion, chunking, embeddings, Vespa upserts.
- `ui/`: Astro + React front-end (login, filters, search, chat).
- `vespa/application/`: Vespa schemas and services; auto-deployed on startup.
- `scripts/`: Helpers (`deploy-vespa.sh`, `wait_for_health.sh`, `smoke_tests.sh`).

## Build, Test, and Dev Commands

- `make install`: Create venv and install Python deps for `api` and `indexer`.
- `make ui-install`: Install UI dependencies.
- `make precommit`: Run all pre-commit hooks (format/lint).
- `make test-python`: Run Python tests (`api/tests`, `indexer/tests`).
- `make test-ui`: Run UI unit tests (vitest). `make test-ui-e2e`: Playwright E2E.
- Run stack: `docker compose up -d --build` (Vespa app auto-deploys).

## Coding Style & Naming

- Python: type hints, async I/O where applicable; format with Black.
- JS/TS/Markdown: Prettier; Shell: shfmt. See `.pre-commit-config.yaml`.
- Naming: modules/files `snake_case` (Python), scripts `kebab-case`, React components `PascalCase`.
- Models: keep UI labels stable → "gpt 5"→`gpt-5`, "gpt5 mini"→`gpt-5-mini`, "gpt5 nano"→`gpt-5-nano`.

## Testing Guidelines

- Frameworks: `pytest` (Python), `vitest` (UI), `playwright` (E2E).
- Use VS Code Test Explorer; mock with `patch()` in tests (avoid global module mocking).
- Discovery: tests under `api/tests` and `indexer/tests` named `test_*.py`.
- Before PR: run `make test-python`, `make test-ui`, and optional `scripts/smoke_tests.sh`.

## Commit & PR Guidelines

- Commits: imperative, present tense with scope when helpful (e.g., "api: fix auth cookie").
- Run `pre-commit run --all-files` before pushing; no hook failures.
- PRs: clear description, linked issue, reproduction steps, and screenshots for UI changes.
- Include local test results and any performance/latency notes for search/chat.

## Security & Configuration

- Never commit secrets. Use `.env` (copy `.env.example`).
- Bcrypt password hash controls login; cookies are HTTP-only.
- Telethon sessions and Postgres data are volume-backed; prefer read-only mounts where possible.
