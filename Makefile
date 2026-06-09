.PHONY: install lint test download-models run-gdino run-yoloe

install:
	python -m pip install --upgrade pip setuptools wheel
	pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	pytest -q

download-models:
	./scripts/download_models.sh

run-gdino:
	./scripts/run_grounding_dino_sample.sh

run-yoloe:
	./scripts/run_yoloe_sample.sh
