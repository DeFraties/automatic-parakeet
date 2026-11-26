# Ballpark — run everything from the repo root.
PYTHON ?= python3
VENV    := backend/.venv
PY      := $(VENV)/bin/python
ALEMBIC := $(VENV)/bin/alembic -c backend/alembic.ini
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env

.PHONY: help install dev api web test test-backend test-frontend e2e lint format build \
        migrate seed ingest up down logs clean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

$(VENV)/.installed: backend/pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e 'backend[dev]'
	@touch $@

frontend/node_modules/.installed: frontend/package.json
	cd frontend && npm install
	@touch $@

.env:
	cp .env.example .env

install: $(VENV)/.installed frontend/node_modules/.installed .env ## Install backend + frontend deps

dev: install migrate ## API on :8000 (reload) + Vite on :5173
	@trap 'kill 0' INT TERM EXIT; \
	$(VENV)/bin/uvicorn app.main:app --reload --reload-dir backend/app --port 8000 & \
	(cd frontend && npx vite --port 5173) & \
	wait

api: install migrate ## API only
	$(VENV)/bin/uvicorn app.main:app --reload --reload-dir backend/app --port 8000

web: install ## Vite dev server only
	cd frontend && npx vite --port 5173

test: test-backend test-frontend ## Run all unit/API tests

test-backend: $(VENV)/.installed
	cd backend && .venv/bin/pytest

test-frontend: frontend/node_modules/.installed
	cd frontend && npx tsc -b && npx vitest run

e2e: install ## Playwright end-to-end smoke test (starts its own servers)
	cd frontend && npx playwright test --trace off

lint: install ## Ruff + TypeScript checks
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npx tsc -b

format: $(VENV)/.installed
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

build: frontend/node_modules/.installed ## Production frontend build
	cd frontend && npm run build

migrate: $(VENV)/.installed .env ## Apply DB migrations
	$(ALEMBIC) upgrade head

seed: migrate ## Load 51 DEMO properties
	$(PY) -m app.seed

ingest: migrate ## Run the ingest CLI: make ingest ARGS="run --source uk_price_paid"
	$(PY) -m ingest $(ARGS)

up: .env ## Start the docker compose stack
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

clean:
	rm -rf frontend/dist frontend/test-results backend/.pytest_cache backend/.ruff_cache
