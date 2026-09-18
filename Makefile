.PHONY: install dev test lint api

install:
	python -m pip install -e ".[dev]"

dev:
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8080

test:
	pytest

lint:
	ruff check .

api:
	uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
