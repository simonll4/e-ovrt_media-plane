.PHONY: install lint test download-models download-prefilter-blob serve smoke compare-runs docker-build docker-run-mock

install:
	python -m pip install --upgrade pip setuptools wheel
	pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	pytest -q

download-models:
	./scripts/download_models.sh

download-prefilter-blob:
	python scripts/download_prefilter_blob.py

serve:
	EOVRT_MODEL_REF=$${EOVRT_MODEL_REF:-mock} \
	uvicorn --factory eovrt_media.service.app:create_app --host 0.0.0.0 --port 8080

smoke:
	curl -sf http://localhost:8080/healthz && curl -sf http://localhost:8080/readyz && echo OK

compare-runs:
	python -m eovrt_media.tools.inspect_runs compare runs

docker-build:
	docker build -t eovrt/media-plane:latest -f infra/docker/Dockerfile .

docker-run-mock:
	docker run --rm -p 8080:8080 -e EOVRT_MODEL_REF=mock \
	  -v $$(pwd)/runs:/data/runs eovrt/media-plane:latest
