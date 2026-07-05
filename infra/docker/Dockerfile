# Dockerfile — imagen única DBE (Fase 1, Spec A §3.3)
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
# El python3.11 del universe de jammy queda pineado en un build 3.11.0rc1 (le falta
# sys.get_int_max_str_digits, agregado en el 3.11 final), lo que rompe torch._dynamo
# al cargar cualquier modelo real (transformers). deadsnakes trae el release final.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common gnupg curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python3.11 -m ensurepip --upgrade \
    && python3.11 -m pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY pyproject.toml constraints.txt ./
COPY src ./src
COPY configs ./configs
RUN python3.11 -m pip install --no-cache-dir -c constraints.txt ".[gpu]"

ENV EOVRT_MODEL_REF=mock \
    EOVRT_MEDIA_CATALOG_ROOT=/app/configs \
    EOVRT_RUNS_DIR=/data/runs \
    EOVRT_DATASETS_ROOT=/data/datasets \
    HF_HOME=/data/weights
VOLUME ["/data/runs", "/data/datasets", "/data/weights"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
    CMD curl -sf http://localhost:8080/readyz || exit 1
CMD ["python3.11", "-m", "uvicorn", "--factory", "eovrt_media.service.app:create_app", \
     "--host", "0.0.0.0", "--port", "8080"]
