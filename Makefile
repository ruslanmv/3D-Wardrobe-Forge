.PHONY: help install dev api worker test test-unit test-e2e test-blender lint fmt fixtures templates library studio assets assets-demo validate-assets docker space clean

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
	@echo "library       fetch and verify the Studio's avatar library (FROM=dir to copy locally)"
	@echo "studio        fetch the library, then run the API with the Studio at /studio/"
	@echo "assets        build a yourfriend.online bundle (AVATAR=... PROMPT=...)"
	@echo "assets-demo   build a demo yourfriend.online bundle from a generated fixture"
	@echo "validate-assets validate the default static bundle manifests"
	@echo "space         deploy committed HEAD to the Hugging Face Space (HF_TOKEN=..., HF_SPACE_REPO=...)"

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

library:
	$(PYTHON) tools/fetch_library.py $(if $(FROM),--from "$(FROM)")

studio: library
	@echo "Wardrobe Studio: http://127.0.0.1:$(PORT)/studio/"
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port $(PORT)

assets:
	@test -n "$(AVATAR)" || (echo "AVATAR is required" && exit 2)
	@test -n "$(PROMPT)" || (echo "PROMPT is required" && exit 2)
	$(PYTHON) -m apps.cli create --avatar "$(AVATAR)" --prompt "$(PROMPT)" --target yourfriend

assets-demo:
	rm -rf /tmp/wardrobe-demo dist/yourfriend-online
	$(PYTHON) -m apps.cli fixtures --out /tmp/wardrobe-demo
	$(PYTHON) -m apps.cli create --avatar /tmp/wardrobe-demo/calibration-b-medium-vrm1.vrm --prompt "elegant dark red evening dress" --target yourfriend

validate-assets:
	@test -f dist/yourfriend-online/wardrobe.json
	@test -f dist/yourfriend-online/avatars.json
	@test -f dist/yourfriend-online/catalog.json
	@test -f dist/yourfriend-online/provenance.json
	@find dist/yourfriend-online/looks -name look.vrm -print -quit | grep -q .

docker:
	docker compose build

space:
	sh deploy/huggingface/deploy.sh

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info output
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
