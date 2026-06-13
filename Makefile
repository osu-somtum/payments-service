.PHONY: run dev install type-check

install:
	poetry install

run:
	poetry run uvicorn app.main:app --host $${APP_HOST:-0.0.0.0} --port $${APP_PORT:-8001}

dev:
	poetry run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

type-check:
	poetry run mypy app --ignore-missing-imports
