SHELL := /bin/bash
PORT ?= 8740
COMPOSE := docker compose
export UID := $(shell id -u)
export GID := $(shell id -g)
# A13: stamped into the image so experiments record the code they ran
export GIT_COMMIT := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

.PHONY: up up-langfuse down logs env test test-docker dev-backend dev-frontend health fixtures

## One setup command: write .env from key files, build, start, wait for health.
up: env
	@mkdir -p data
	$(COMPOSE) up -d --build
	@for i in $$(seq 1 30); do curl -fsS http://127.0.0.1:$(PORT)/healthz >/dev/null 2>&1 && break; sleep 1; done
	@curl -fsS http://127.0.0.1:$(PORT)/healthz && echo
	@echo "App: http://localhost:$(PORT)  (from the Mac: ssh -N -L $(PORT):127.0.0.1:$(PORT) hdx-lab)"

# A20: same app with Langfuse tracing on (keys as file secrets; see docs/observability.md)
up-langfuse: env
	@mkdir -p data
	$(COMPOSE) -f docker-compose.yml -f docker-compose.langfuse.yml up -d --build
	@for i in $$(seq 1 30); do curl -fsS http://127.0.0.1:$(PORT)/healthz >/dev/null 2>&1 && break; sleep 1; done
	@curl -fsS http://127.0.0.1:$(PORT)/healthz && echo

env:
	@python3 scripts/setup_env.py

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

health:
	@curl -fsS http://127.0.0.1:$(PORT)/healthz && echo

## Tests without keys or network (providers are mocked; ElevenLabs is never called).
test:
	cd backend && (test -d .venv || uv venv -q .venv) && VIRTUAL_ENV=.venv uv pip install -q -e '.[dev]' && .venv/bin/pytest -q
	cd frontend && npm ci --silent && npx tsc -b && npx vitest run

test-docker:
	docker build --target test -t interpreter-workbench:test . && docker run --rm --network none interpreter-workbench:test

dev-backend:
	cd backend && set -a && source ../.env && set +a && CONFIG_DIR=../config DATA_DIR=../data .venv/bin/uvicorn app.main:app --reload --port $(PORT)

dev-frontend:
	cd frontend && npm run dev

## Benchmark fixtures (OpenAI TTS, non-pipeline voices) -> data/fixtures/*.wav (gitignored; skips existing files).
fixtures:
	set -a && source .env && set +a && backend/.venv/bin/python scripts/make_fixtures.py
