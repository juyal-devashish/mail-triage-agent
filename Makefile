# Common tasks. Backend commands run in backend/ with the project's virtualenv.

PY := .venv/bin/python

.PHONY: install demo dev-backend dev-frontend test lint eval

install:            ## backend venv (editable, with dev tools and Claude support) and frontend deps
	cd backend && python3.12 -m venv .venv && $(PY) -m pip install -q -e ".[dev,llm,gmail]"
	if [ -f frontend/package.json ]; then cd frontend && npm install; fi

demo:               ## build the synthetic inbox and apply stored verdicts (no API calls)
	cd backend && $(PY) -m app.cli demo

dev-backend:        ## API on :8000 with auto-reload
	cd backend && $(PY) -m uvicorn app.main:default_app --factory --reload --port 8000

dev-frontend:       ## React dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

test:               ## backend tests + frontend typecheck
	cd backend && $(PY) -m pytest
	if [ -f frontend/package.json ]; then cd frontend && npm run typecheck; fi

lint:
	cd backend && $(PY) -m ruff check app tests && $(PY) -m ruff format --check app tests

eval:               ## score stored verdicts against the synthetic answer key and rewrite docs/results.md
	cd backend && $(PY) -m app.cli eval --write
