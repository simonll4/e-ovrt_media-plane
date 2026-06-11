.PHONY: install lint test download-models run-mock run-gdino run-yoloe compare-runs

install:
	python -m pip install --upgrade pip setuptools wheel
	pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	pytest -q

download-models:
	./scripts/download_models.sh

run-mock:
	eovrt-media run --config configs/runs/mock.yaml

run-gdino:
	./scripts/run_grounding_dino_sample.sh

run-yoloe:
	./scripts/run_yoloe_sample.sh

compare-runs:
	eovrt-media compare-runs runs
