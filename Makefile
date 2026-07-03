.PHONY: install lint test download-models serve smoke compare-runs

install:
	python -m pip install --upgrade pip setuptools wheel
	pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	pytest -q

download-models:
	./scripts/download_models.sh

serve:
	EOVRT_MODEL_REF=$${EOVRT_MODEL_REF:-mock} \
	uvicorn --factory eovrt_media.service.app:create_app --host 0.0.0.0 --port 8080

smoke:
	curl -sf http://localhost:8080/healthz && curl -sf http://localhost:8080/readyz && echo OK

compare-runs:
	python -m eovrt_media.tools.inspect_runs compare runs
