.PHONY: setup migrate seed fixtures pipeline demo backend frontend dev test lint typecheck build validate workflows up
PY = .venv/bin/python

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements.lock
	.venv/bin/pip install --no-deps -e './backend[dev]'
	cd frontend && npm ci
migrate:
	.venv/bin/alembic upgrade head
seed:
	$(PY) -m leados.cli seed
fixtures: pipeline
pipeline:
	$(PY) -m leados.cli run
demo:
	$(PY) -m leados.cli demo
backend:
	.venv/bin/uvicorn leados.api:app --host 0.0.0.0 --port 8000 --reload
frontend:
	cd frontend && npm run dev
dev:
	$(PY) scripts/dev.py
test:
	.venv/bin/pytest backend/tests -q
test-live-providers:
	RUN_LIVE_PROVIDER_TESTS=true .venv/bin/pytest backend/tests/test_live_providers_integration.py -q -s
lint:
	.venv/bin/ruff check backend scripts
	.venv/bin/ruff format --check backend scripts
	cd frontend && npm run lint
typecheck:
	.venv/bin/mypy --config-file backend/pyproject.toml backend/leados
	cd frontend && npm run typecheck
build:
	cd frontend && npm run build
workflows:
	$(PY) -m leados.cli validate-workflows
validate: test lint typecheck build workflows
up:
	docker compose up --build -d


setup-sheets:
	$(PY) scripts/setup_google_sheets.py
validate-sheets:
	$(PY) scripts/validate_google_sheets.py
export:
	$(PY) scripts/export_leados_data.py
