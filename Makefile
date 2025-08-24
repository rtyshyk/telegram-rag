# Unified Makefile for repository CI tasks
# Usage examples:
#   make install          # install Python deps (api + indexer) and pre-commit
#   make ui-install       # install UI deps
#   make test-python      # run all python tests (api + indexer)
#   make test-ui          # run UI unit tests (vitest)
#   make precommit        # run pre-commit hooks on all files
#   make ci               # precommit + all tests

PYTHON ?= python3
VENV_DIR ?= .venv
PY ?= $(VENV_DIR)/bin/python
PIP ?= $(VENV_DIR)/bin/pip
PRECOMMIT ?= $(VENV_DIR)/bin/pre-commit

UI_DIR := ui
API_DIR := api
INDEXER_DIR := indexer

.PHONY: install ui-install test-python test-ui test-ui-e2e precommit ci ensure-venv

ensure-venv:
	@[ -d $(VENV_DIR) ] || ($(PYTHON) -m venv $(VENV_DIR) && echo "Created venv")
	@$(PIP) install -q --upgrade pip

install: ensure-venv
	@echo "Installing Python dependencies (api + indexer)"
	@$(PIP) install -q -r $(API_DIR)/requirements.txt
	@$(PIP) install -q -r $(INDEXER_DIR)/requirements.txt
	@$(PIP) install -q pre-commit
	@echo "Python deps installed"

ui-install:
	@echo "Installing UI dependencies"
	@cd $(UI_DIR) && npm install --no-audit --no-fund

precommit: install
	@echo "Running pre-commit hooks"
	@$(PRECOMMIT) run --all-files

# Run python tests (api + indexer)
# Uses pytest.ini at root (if any) else default discovery
test-python: install
	@echo "Running API tests"
	@$(PY) -m pytest -q $(API_DIR)/tests
	@echo "Running indexer tests"
	@$(PY) -m pytest -q $(INDEXER_DIR)/tests

# Run UI unit tests (vitest). Assumes deps already installed.
test-ui:
	@echo "Running UI unit tests (vitest)"
	@cd $(UI_DIR) && npx vitest run --passWithNoTests

# Run UI e2e tests (Playwright)
test-ui-e2e: ui-install
	@echo "Running UI e2e tests (Playwright)"
	@cd $(UI_DIR) && npx playwright install --with-deps chromium >/dev/null 2>&1 || true
	@cd $(UI_DIR) && npx playwright test --reporter=line

ci: precommit test-python test-ui test-ui-e2e
	@echo "CI pipeline succeeded"
