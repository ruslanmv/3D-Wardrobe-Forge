.PHONY: help install dev api worker test test-unit test-e2e test-blender lint fmt fixtures templates docker clean

PYTHON ?= python
PORT ?= 8080

help:
	@echo "install       install the package with dev extras"
	@echo "dev           run the API with reload"
	@echo "api           run the API"
	@echo "worker        run a standalone job worker"
	@echo "test          run the whole suite"
	@echo "test-unit     run unit tests only"
	@echo "test-e2e      run the acceptance matrix"
	@echo "test-blender  run the Blender integration tests"
	@echo "lint          ruff check"
	@echo "fmt           ruff format + autofix"
	@echo "fixtures      regenerate the calibration avatars"
	@echo "templates     list and validate the garment library"

install:
	$(PYTHON) -m pip install -e ".[dev,preview]"

dev:
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port $(PORT)

api:
	uvicorn apps.api.main:app --host 0.0.0.0 --port $(PORT)

worker:
	$(PYTHON) -m worker.runner

test:
	pytest

test-unit:
	pytest tests/unit

test-e2e:
	pytest tests/e2e

test-blender:
	pytest tests/blender -v

lint:
	ruff check .

fmt:
	ruff check --fix .
	ruff format .

fixtures:
	$(PYTHON) -m apps.cli fixtures --out assets/fixtures

templates:
	$(PYTHON) -m apps.cli templates

docker:
	docker compose build

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info output
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
