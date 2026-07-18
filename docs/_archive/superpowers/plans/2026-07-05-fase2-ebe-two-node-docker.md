# Fase 2 — EBE two-node containerizada — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruir el despliegue Docker del split two-node (Nodo A edge sin GPU + Nodo B GPU sobre ZeroMQ) que quedó roto al eliminar el CLI, con timeout anti-cuelgue en el transporte.

**Architecture:** Se reutilizan `run_node_a`/`run_node_b` (ya validados en-proceso) sin cambios funcionales. Se agrega un entrypoint delgado `eovrt_media.tools.run_node` (argparse, reemplaza al CLI eliminado), un `request_timeout_ms` en el REQ/REP del consumidor, y un layout `infra/twonode/` (Dockerfile edge + composes + configs) que reemplaza a `deploy/`. El Nodo B reusa la imagen `eovrt/media-plane:latest` existente con entrypoint override.

**Tech Stack:** Python 3.11+, pyzmq, pydantic v2, argparse, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-07-05-fase2-ebe-two-node-docker-design.md`

## Global Constraints

- **NO COMMITS**: regla del workspace (CLAUDE.md raíz) — nunca commitear salvo pedido explícito del usuario en ese turno. Los pasos de commit habituales se reemplazan por verificación; los diffs quedan en el working tree. Para review de archivos nuevos: `git add -N <paths>` + `git diff HEAD -- <paths>`.
- Repo: `e-ovrt_media-plane` @ `feature/inference-service`. No tocar `e-ovrt_experimental-setup` ni la plataforma DBE.
- Suite completa (421 tests) + `ruff check src tests` deben quedar verdes al final de cada task. Comando: `.venv/bin/python -m pytest -q` desde la raíz del repo (venv es python3.12; el código debe seguir soportando 3.11 que usan las imágenes).
- Sin dependencias nuevas. Sin auth/TLS entre nodos (decisión spec §0.4). Sin reconexión automática ZeroMQ (spec §0.3).
- `run_node_a`/`run_node_b` no cambian de firma.
- OAK-D: solo documentación de contrato (spec §4); `OakDSource` conserva su `NotImplementedError`.

---

### Task 1: `transport.request_timeout_ms` + timeout en `request()` del consumidor

El bug: `NetworkTransportAdapter.request()` (`src/eovrt_media/transport/network.py:186-191`) hace `send`+`recv` bloqueante sin límite; si el Nodo A muere a mitad de corrida, el Nodo B cuelga para siempre.

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (clase `TransportConfig`, ~línea 184)
- Modify: `src/eovrt_media/transport/network.py` (`__init__` ~línea 31 y `request()` ~línea 186)
- Modify: `src/eovrt_media/transport/factory.py` (rama `backend == "network"`)
- Modify: `src/eovrt_media/runtime/two_node.py` (`run_node_b`, llamada a `create_transport`)
- Test: `tests/test_network_transport.py`

**Interfaces:**
- Produces: `TransportConfig.request_timeout_ms: int` (default 10000, gt=0); kwarg `request_timeout_ms` en `NetworkTransportAdapter.__init__` y en `create_transport(backend="network", ...)`. `request()` lanza `RuntimeError` si no hay respuesta dentro del timeout.

- [ ] **Step 1: Test que falla — consumidor sin productor no cuelga**

Agregar al final de `tests/test_network_transport.py` (usa los helpers ya definidos en ese archivo: `_unused_tcp_endpoint`):

```python
def test_consumer_request_times_out_instead_of_hanging_when_producer_is_gone():
    # Sin productor del otro lado: el REQ encola el send y el recv jamás llega.
    consumer = NetworkTransportAdapter(
        role="consumer",
        endpoint=_unused_tcp_endpoint(),
        heartbeat_endpoint=_unused_tcp_endpoint(),
        request_timeout_ms=300,
    )
    try:
        start = time.monotonic()
        with pytest.raises(RuntimeError, match="no respondió en 300 ms"):
            consumer.request()
        assert time.monotonic() - start < 5.0  # cortó por timeout, no colgó
    finally:
        consumer.shutdown()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_network_transport.py::test_consumer_request_times_out_instead_of_hanging_when_producer_is_gone -v`
Expected: FAIL con `TypeError: ... unexpected keyword argument 'request_timeout_ms'`

- [ ] **Step 3: Implementar**

En `src/eovrt_media/config/schemas.py`, dentro de `TransportConfig` (después de `heartbeat_timeout_ms`):

```python
    request_timeout_ms: int = Field(default=10000, gt=0)
```

En `src/eovrt_media/transport/network.py`, `__init__`: agregar el parámetro `request_timeout_ms: int = 10000` (después de `heartbeat_timeout_ms`) y guardarlo:

```python
        self.request_timeout_ms = request_timeout_ms
```

Reemplazar `request()` (el método actual de las líneas ~186-191) por:

```python
    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        self._sock.send(REQUEST)
        poller = zmq.Poller()
        poller.register(self._sock, zmq.POLLIN)
        try:
            if not dict(poller.poll(timeout=self.request_timeout_ms)):
                raise RuntimeError(
                    f"Nodo A no respondió en {self.request_timeout_ms} ms — ¿murió el "
                    "nodo edge? La corrida se aborta (sin reintento automático)."
                )
            data = self._sock.recv()
        finally:
            poller.unregister(self._sock)
        if data == END_MSG:
            return END
        return deserialize_unit(data)
```

En `src/eovrt_media/transport/factory.py`, rama `backend == "network"`, agregar junto a los otros kwargs:

```python
            request_timeout_ms=kwargs.get("request_timeout_ms", 10000),
```

En `src/eovrt_media/runtime/two_node.py`, `run_node_b`, agregar a la llamada `create_transport(...)` (junto a `heartbeat_timeout_ms`):

```python
        request_timeout_ms=config.transport.request_timeout_ms,
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `.venv/bin/python -m pytest tests/test_network_transport.py tests/test_two_node.py tests/test_transport.py -q`
Expected: todos PASS (el roundtrip existente no se ve afectado: 10s de default sobran en loopback).

- [ ] **Step 5: Suite completa + lint (sin commit — regla del workspace)**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests`
Expected: `422 passed` (421 + el nuevo) y `All checks passed!`

---

### Task 2: Entrypoint `eovrt_media.tools.run_node`

Reemplazo delgado del CLI eliminado. Mismo patrón que `tools/evaluate.py` / `tools/debug_run.py` (función `main()` con argparse + `if __name__ == "__main__":`).

**Files:**
- Create: `src/eovrt_media/tools/run_node.py`
- Test: `tests/test_run_node_tool.py`

**Interfaces:**
- Consumes: `load_run_config(config_path)` de `eovrt_media.config.loader`; `run_node_a(config)` / `run_node_b(config)` de `eovrt_media.runtime.two_node`.
- Produces: `python -m eovrt_media.tools.run_node --role {a|b} --config <yaml>` — exit 0 si el run termina, exit 1 con error en stderr ante cualquier falla, exit 2 ante args inválidos (argparse). Los Dockerfiles/composes de Tasks 3-4 dependen de esta invocación exacta.

- [ ] **Step 1: Tests que fallan**

Crear `tests/test_run_node_tool.py`:

```python
"""Entrypoint two-node: despacho por rol, carga de config y exit codes."""
from __future__ import annotations

from pathlib import Path

import pytest

from eovrt_media.tools import run_node


def _write_minimal_config(tmp_path: Path) -> Path:
    # Config mínima válida: mock + image_folder sobre un dir con una imagen falsa.
    images = tmp_path / "imgs"
    images.mkdir()
    (images / "f.jpg").write_bytes(b"\xff\xd8\xff\xd9")  # JPEG vacío: alcanza para el load
    config = tmp_path / "run.yaml"
    config.write_text(
        f"""
run:
  scenario: EBE
  name: run_node_test
source:
  type: image_folder
  path: {images}
model:
  ref: mock
prompts:
  set_inline:
    id: t
    classes:
      - id: person
        prompt: person
topology:
  mode: two_node
transport:
  backend: network
  endpoint: "tcp://127.0.0.1:5599"
  heartbeat_endpoint: "tcp://127.0.0.1:5600"
""",
        encoding="utf-8",
    )
    return config


def test_role_a_dispatches_to_run_node_a(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(run_node, "_RUNNERS", {"a": lambda c: called.setdefault("a", c),
                                               "b": lambda c: called.setdefault("b", c)})
    config = _write_minimal_config(tmp_path)

    run_node.main(["--role", "a", "--config", str(config)])

    assert "a" in called and "b" not in called
    assert called["a"].run.name == "run_node_test"


def test_role_b_dispatches_to_run_node_b(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(run_node, "_RUNNERS", {"a": lambda c: called.setdefault("a", c),
                                               "b": lambda c: called.setdefault("b", c)})
    config = _write_minimal_config(tmp_path)

    run_node.main(["--role", "b", "--config", str(config)])

    assert "b" in called and "a" not in called


def test_missing_config_exits_1(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_node.main(["--role", "a", "--config", str(tmp_path / "nope.yaml")])
    assert excinfo.value.code == 1
    assert "nope.yaml" in capsys.readouterr().err


def test_runtime_error_exits_1(tmp_path, monkeypatch, capsys):
    def boom(config):
        raise RuntimeError("zmq explotó")

    monkeypatch.setattr(run_node, "_RUNNERS", {"a": boom, "b": boom})
    config = _write_minimal_config(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        run_node.main(["--role", "b", "--config", str(config)])
    assert excinfo.value.code == 1
    assert "zmq explotó" in capsys.readouterr().err


def test_invalid_role_exits_2(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        run_node.main(["--role", "c", "--config", "x.yaml"])
    assert excinfo.value.code == 2  # argparse
```

Nota para el implementador: si `load_run_config` rechaza la config mínima por algún campo (p. ej. el formato de `set_inline`), ajustar la config del helper hasta que cargue — mirar `tests/test_config_*.py` para ejemplos de configs mínimas válidas ya usadas en la suite. El contrato a preservar es el de los asserts, no el YAML literal.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_run_node_tool.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'eovrt_media.tools.run_node'`

- [ ] **Step 3: Implementar**

Crear `src/eovrt_media/tools/run_node.py`:

```python
"""Entrypoint two-node: arranca Nodo A (edge) o Nodo B (GPU) desde una run config.

Uso: `python -m eovrt_media.tools.run_node --role {a|b} --config <run.yaml>`

Reemplazo delgado del CLI eliminado en Fase 1 (Task 17): carga la RunConfig y
despacha a run_node_a/run_node_b. Pensado como ENTRYPOINT de los contenedores de
infra/twonode/ — reporta por exit code (0 ok, 1 falla) + stderr.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _run_a(config) -> None:
    from eovrt_media.runtime.two_node import run_node_a

    run_node_a(config)


def _run_b(config) -> None:
    from eovrt_media.runtime.two_node import run_node_b

    run_node_b(config)


_RUNNERS = {"a": _run_a, "b": _run_b}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="eovrt-run-node",
        description="Arranca un nodo del split two-node (a=edge, b=GPU).",
    )
    parser.add_argument("--role", choices=["a", "b"], required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)

    from eovrt_media.config.loader import load_run_config

    try:
        config = load_run_config(args.config)
        _RUNNERS[args.role](config)
    except Exception as error:  # exit code + stderr para el contenedor
        print(f"eovrt-run-node[{args.role}]: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `.venv/bin/python -m pytest tests/test_run_node_tool.py -v`
Expected: 5 PASS

- [ ] **Step 5: Suite completa + lint (sin commit)**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests`
Expected: `427 passed`, lint limpio.

---

### Task 3: Limpieza de `two_node_local.py` (código muerto post-CLI)

**NO borrar `run_two_node_local`**: la importan `src/eovrt_media/debugging/session.py:16` y la monkeypatchean 3 tests de `tests/test_debug_session.py`. Solo se elimina el cuerpo inalcanzable después del `raise RuntimeError` y los helpers que únicamente ese cuerpo usaba.

**Files:**
- Modify: `src/eovrt_media/runtime/two_node_local.py`
- Test (existentes, deben seguir verdes): `tests/test_two_node_local.py`, `tests/test_debug_session.py`, `tests/test_debug_run.py`

**Interfaces:**
- Produces: `run_two_node_local(options)` sigue existiendo y sigue lanzando `RuntimeError` con match `"no está soportado"` (hay un test que lo exige: `test_run_two_node_local_raises_since_cli_removed`). Se conservan intactos: `LocalTwoNodeOptions`, `LocalTwoNodeResult`, `resolve_source`, `resolve_prompts_ref`, `build_run_config`, `write_generated_config`, `unused_tcp_endpoint`, `wait_for_tcp_endpoint`, `scan_log_warnings`, `collect_run_summary`, `resolve_run_dir_from_node_log`, `latest_run_dir`, `probe_rtsp_config`, `_endpoint_host_port`.

- [ ] **Step 1: Verificar consumidores antes de borrar**

Run: `grep -rn "_command_for_node\|_subprocess_env\|_open_log\|_terminate_process\|_endpoints_for_options" src/ tests/ --include="*.py" | grep -v two_node_local.py`
Expected: sin resultados (solo el propio módulo los usa). Si aparece algún consumidor, NO borrar ese símbolo y anotar el hallazgo.

- [ ] **Step 2: Borrar el código muerto**

En `src/eovrt_media/runtime/two_node_local.py`:

1. Eliminar las funciones `_command_for_node`, `_subprocess_env`, `_open_log`, `_terminate_process`, `_endpoints_for_options` completas.
2. En `run_two_node_local`, eliminar todo el cuerpo **después** del `raise RuntimeError(...)` (es inalcanzable desde Task 17). Actualizar el mensaje y el docstring para apuntar al reemplazo real:

```python
def run_two_node_local(options: LocalTwoNodeOptions) -> LocalTwoNodeResult:
    """NO SOPORTADO desde Task 17 (Fase 1): el CLI que esta orquestación spawneaba
    fue eliminado. El despliegue two-node vive ahora en ``infra/twonode/``
    (docker compose; ver su README). Se conserva la firma porque
    ``debugging/session.py`` la importa y los tests la monkeypatchean.
    """
    raise RuntimeError(
        "run_two_node_local ya no está soportado: el CLI `eovrt_media.cli` fue "
        "eliminado (Task 17). Usar el despliegue Docker two-node de infra/twonode/."
    )
```

3. Eliminar los imports que queden sin uso (previsiblemente `subprocess`, `sys`, `os`, `time`; `ruff` los señala — correr `ruff check src/eovrt_media/runtime/two_node_local.py` y borrar exactamente los que marque F401).

- [ ] **Step 3: Verificar que nada se rompió**

Run: `.venv/bin/python -m pytest tests/test_two_node_local.py tests/test_debug_session.py tests/test_debug_run.py -q && .venv/bin/python -m ruff check src tests`
Expected: todos PASS (el test del guard sigue matcheando "no está soportado"), lint limpio.

- [ ] **Step 4: Suite completa (sin commit)**

Run: `.venv/bin/python -m pytest -q`
Expected: `427 passed`.

---

### Task 4: `infra/twonode/` — Dockerfile edge, composes y configs

**Files:**
- Create: `infra/twonode/Dockerfile.node-a`
- Create: `infra/twonode/docker-compose.yml`
- Create: `infra/twonode/docker-compose.node-a.yml`
- Create: `infra/twonode/docker-compose.node-b.yml`
- Create: `infra/twonode/configs/two_node_a.yaml` (migrado desde `deploy/configs/two_node_a.example.yaml`, ajustado)
- Create: `infra/twonode/configs/two_node_b.yaml` (ídem desde `two_node_b.example.yaml`)
- (Los `deploy/configs/e2e_fp16_node_{a,b}.yaml` se migran tal cual a `infra/twonode/configs/` en Task 6 al borrar `deploy/`.)

**Interfaces:**
- Consumes: `python -m eovrt_media.tools.run_node --role {a|b} --config ...` (Task 2); imagen `eovrt/media-plane:latest` de `infra/docker/Dockerfile` (ya existe).
- Produces: los manifiestos que Task 5 cubre con tests de contrato y Task 7 usa en el smoke.

- [ ] **Step 1: Dockerfile del Nodo A (edge, sin GPU)**

Crear `infra/twonode/Dockerfile.node-a`:

```dockerfile
# Nodo A — ingesta + rate control + normalización + servidor ZeroMQ. Sin GPU.
# El extra [edge] es vacío a propósito: solo deps base, sin torch (el Nodo A
# construye el adaptador únicamente para leer input_spec, nunca llama load()).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY configs ./configs
RUN pip install --no-cache-dir -e ".[edge]"

ENV EOVRT_MEDIA_CATALOG_ROOT=/app/configs PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "eovrt_media.tools.run_node", "--role", "a"]
CMD ["--config", "/app/twonode-configs/two_node_a.yaml"]
```

- [ ] **Step 2: Compose single-host (smoke y demo)**

Crear `infra/twonode/docker-compose.yml`:

```yaml
# Split two-node EBE en UN host (red bridge interna) — smoke de aceptación y demo.
# Un run por `up`: ambos contenedores terminan al agotar el stream (batch, no servicio).
# SEGURIDAD: sin auth ni cifrado entre nodos (LAN de laboratorio, riesgo aceptado
# — ver README.md). No publicar 5555/5556 fuera de la LAN.
name: eovrt-twonode
services:
  node-a:
    build:
      context: ../..
      dockerfile: infra/twonode/Dockerfile.node-a
    image: eovrt/media-plane-edge:latest
    command: ["--config", "/app/twonode-configs/two_node_a.yaml"]
    networks: [twonode]
    expose: ["5555", "5556"]
    volumes:
      - ./configs:/app/twonode-configs:ro
      - ../../../e-ovrt_datasets/datasets/raw:/datasets:ro
      - ../../../e-ovrt_experimental-setup/prompts:/app/configs/prompts:ro

  node-b:
    build:
      context: ../..
      dockerfile: infra/docker/Dockerfile
    image: eovrt/media-plane:latest
    # Misma imagen del servicio DBE, proceso distinto: run batch del Nodo B.
    entrypoint: ["python3.11", "-m", "eovrt_media.tools.run_node", "--role", "b"]
    command: ["--config", "/app/twonode-configs/two_node_b.yaml"]
    networks: [twonode]
    depends_on: [node-a]
    environment:
      # La imagen DBE define EOVRT_DATASETS_ROOT=/data/datasets; acá el Nodo B no
      # lee datasets (los frames llegan por ZeroMQ) — se anula para que el loader
      # no rebasee el path de source del config.
      EOVRT_DATASETS_ROOT: ""
    volumes:
      - ./configs:/app/twonode-configs:ro
      - ../../models:/app/models:ro
      - ../../mobileclip2_b.ts:/app/mobileclip2_b.ts:ro
      - ../../runs:/app/runs
      - ../../../e-ovrt_experimental-setup/prompts:/app/configs/prompts:ro
      - weights-cache:/data/weights
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    # Para el smoke con model.ref=mock en un host sin GPU: comentar el bloque
    # deploy.resources de arriba.

networks:
  twonode:
    driver: bridge

volumes:
  weights-cache: {}
```

- [ ] **Step 3: Composes por host (despliegue real en dos máquinas)**

Crear `infra/twonode/docker-compose.node-a.yml`:

```yaml
# Solo Nodo A — host edge real. Publica ZeroMQ hacia la LAN para el Nodo B remoto.
# SEGURIDAD: 5555/5556 sin auth ni cifrado — solo LAN de laboratorio (ver README.md).
name: eovrt-twonode-a
services:
  node-a:
    build:
      context: ../..
      dockerfile: infra/twonode/Dockerfile.node-a
    image: eovrt/media-plane-edge:latest
    command: ["--config", "${NODE_A_CONFIG:-/app/twonode-configs/two_node_a.yaml}"]
    ports: ["5555:5555", "5556:5556"]
    volumes:
      - ./configs:/app/twonode-configs:ro
      - ../../../e-ovrt_datasets/datasets/raw:/datasets:ro
      - ../../../e-ovrt_experimental-setup/prompts:/app/configs/prompts:ro
```

Crear `infra/twonode/docker-compose.node-b.yml`:

```yaml
# Solo Nodo B — host GPU real. El endpoint del Nodo A remoto va en el YAML de config
# (transport.endpoint: tcp://<ip-edge>:5555).
name: eovrt-twonode-b
services:
  node-b:
    build:
      context: ../..
      dockerfile: infra/docker/Dockerfile
    image: eovrt/media-plane:latest
    entrypoint: ["python3.11", "-m", "eovrt_media.tools.run_node", "--role", "b"]
    command: ["--config", "${NODE_B_CONFIG:-/app/twonode-configs/two_node_b.yaml}"]
    environment:
      EOVRT_DATASETS_ROOT: ""
    volumes:
      - ./configs:/app/twonode-configs:ro
      - ../../models:/app/models:ro
      - ../../mobileclip2_b.ts:/app/mobileclip2_b.ts:ro
      - ../../runs:/app/runs
      - ../../../e-ovrt_experimental-setup/prompts:/app/configs/prompts:ro
      - weights-cache:/data/weights
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  weights-cache: {}
```

- [ ] **Step 4: Configs de los nodos**

Crear `infra/twonode/configs/two_node_a.yaml` (base: `deploy/configs/two_node_a.example.yaml`; cambios: `model.ref: mock` como default de smoke, `run.max_units`, timeout explícito):

```yaml
### Nodo A (edge) — single-host compose. Bindea a 0.0.0.0; node-b llega por la bridge.
### Para el despliegue en dos hosts es idéntico (el bind ya escucha en todas las ifaces).
run:
  scenario: EBE
  name: ebe_node_a
  description: "Nodo A: ingesta + normalización + servidor ZeroMQ."
  max_units: 20            # smoke corto; quitar para el stream completo

source:
  type: image_folder
  path: /datasets/construction_site_safety/valid/images

model:
  ref: mock                # smoke sin GPU; para real: yoloe/yoloe-26s (mismo ref que Nodo B)

prompts:
  ref: cr01_cr02_bench_v2
  active_ids: [person, helmet, vest, bare_head]

topology:
  mode: two_node

transport:
  backend: network
  endpoint: "tcp://0.0.0.0:5555"
  heartbeat_endpoint: "tcp://0.0.0.0:5556"
  payload_format: uint8_rgb
  request_timeout_ms: 10000
  compression:
    codec: jpeg
    quality: 90
```

Crear `infra/twonode/configs/two_node_b.yaml` (base: `deploy/configs/two_node_b.example.yaml`; el endpoint apunta al service name de la bridge — para dos hosts reemplazar por la IP del edge):

```yaml
### Nodo B (GPU) — single-host compose: conecta al Nodo A por el nombre de servicio.
### Para dos hosts: endpoint tcp://<ip-del-edge>:5555 (y heartbeat :5556).
run:
  scenario: EBE
  name: ebe_node_b
  description: "Nodo B: inferencia + postproceso + artefactos."
  max_units: 20

source:
  type: image_folder
  path: /datasets/construction_site_safety/valid/images   # no se lee: frames por ZeroMQ

model:
  ref: mock                # smoke; para real: yoloe/yoloe-26s (mismo ref que Nodo A)

prompts:
  ref: cr01_cr02_bench_v2
  active_ids: [person, helmet, vest, bare_head]

topology:
  mode: two_node

transport:
  backend: network
  endpoint: "tcp://node-a:5555"
  heartbeat_endpoint: "tcp://node-a:5556"
  payload_format: uint8_rgb
  request_timeout_ms: 10000
  compression:
    codec: jpeg
    quality: 90
```

Nota para el implementador: si `load_run_config` exige campos adicionales que el ejemplo viejo de `deploy/configs/` sí traía (p. ej. `postprocess`, `outputs`), copiarlos del ejemplo viejo — el criterio es que la config cargue con `load_run_config` sin errores (el test de Task 5 lo verifica).

- [ ] **Step 5: Verificación estática (sin commit)**

Run: `docker compose -f infra/twonode/docker-compose.yml config -q && docker compose -f infra/twonode/docker-compose.node-a.yml config -q && docker compose -f infra/twonode/docker-compose.node-b.yml config -q`
Expected: exit 0 los tres, sin warnings de sintaxis. (Si el daemon Docker no está corriendo, `config` funciona igual — no requiere daemon.)

---

### Task 5: Tests de contrato de `infra/twonode/` (reemplazan a `test_deploy_contract.py`)

`tests/test_deploy_contract.py` valida la forma de los manifiestos **viejos** de `deploy/` (y se mantuvo en verde a propósito como referencia). Ahora que el wiring nuevo existe, se reescriben esos contratos contra `infra/twonode/` y además se valida que las configs cargan.

**Files:**
- Create: `tests/test_twonode_contract.py`
- (El viejo `tests/test_deploy_contract.py` se borra en Task 6 junto con `deploy/`.)

**Interfaces:**
- Consumes: los manifiestos y configs de Task 4; `load_run_config` para validar las configs.

- [ ] **Step 1: Escribir los tests**

Crear `tests/test_twonode_contract.py`:

```python
"""Contratos estáticos del despliegue two-node de infra/twonode/ (Fase 2)."""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
TWONODE_DIR = REPO_ROOT / "infra" / "twonode"


def _load_compose(name: str) -> dict:
    return yaml.safe_load((TWONODE_DIR / name).read_text())


def test_single_host_compose_runs_the_complete_two_node_stack() -> None:
    compose = _load_compose("docker-compose.yml")

    assert set(compose["services"]) == {"node-a", "node-b"}
    assert compose["services"]["node-b"]["depends_on"] == ["node-a"]
    assert compose["services"]["node-a"]["expose"] == ["5555", "5556"]


def test_two_host_manifests_do_not_start_a_remote_peer_locally() -> None:
    edge = _load_compose("docker-compose.node-a.yml")
    gpu = _load_compose("docker-compose.node-b.yml")

    assert set(edge["services"]) == {"node-a"}
    assert edge["services"]["node-a"]["ports"] == ["5555:5555", "5556:5556"]
    assert set(gpu["services"]) == {"node-b"}


def test_node_entrypoints_use_the_run_node_tool() -> None:
    compose = _load_compose("docker-compose.yml")

    dockerfile = (TWONODE_DIR / "Dockerfile.node-a").read_text()
    assert '"-m", "eovrt_media.tools.run_node", "--role", "a"' in dockerfile
    assert '".[edge]"' in dockerfile  # edge sin torch

    node_b = compose["services"]["node-b"]
    assert node_b["image"] == "eovrt/media-plane:latest"  # reusa la imagen DBE
    assert node_b["entrypoint"][-3:] == ["run_node", "--role", "b"] or (
        "eovrt_media.tools.run_node" in " ".join(node_b["entrypoint"])
        and node_b["entrypoint"][-1] == "b"
    )


def test_twonode_configs_load_and_declare_network_transport() -> None:
    from eovrt_media.config.loader import load_run_config

    for name, endpoint_prefix in [
        ("two_node_a.yaml", "tcp://0.0.0.0:"),
        ("two_node_b.yaml", "tcp://node-a:"),
    ]:
        config = load_run_config(TWONODE_DIR / "configs" / name)
        assert config.topology.mode == "two_node"
        assert config.transport.backend == "network"
        assert config.transport.endpoint.startswith(endpoint_prefix)
        assert config.transport.request_timeout_ms == 10000
```

Nota: `load_run_config` resuelve `source.path: /datasets/...` como string (no exige que el path exista al cargar) y `prompts.ref` cae al catálogo del plano; si `configs/prompts/cr01_cr02_bench_v2.yaml` no existe en el repo, el loader deja `prompts_file` sin resolver hasta que el archivo exista — si eso hace fallar la carga, cambiar las configs de ejemplo a `prompts.file: /app/configs/prompts/cr01_cr02_bench_v2.yaml` y en el test montar/parchear un prompts file mínimo vía `tmp_path` + copia de la config con `prompts.set_inline`. El contrato central es: topología, transporte y timeout correctos.

- [ ] **Step 2: Correr y ajustar hasta verde**

Run: `.venv/bin/python -m pytest tests/test_twonode_contract.py -v`
Expected: 4 PASS (ajustar configs/manifiestos de Task 4 si algún contrato falla — el test es la fuente de verdad del wiring).

- [ ] **Step 3: Suite completa + lint (sin commit)**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests`
Expected: `431 passed` (427 + 4), lint limpio. (`test_deploy_contract.py` sigue verde porque `deploy/` todavía existe.)

---

### Task 6: Eliminar `deploy/`, README de twonode y actualización de docs

**Files:**
- Delete: `deploy/` completo (los 4 configs ya migrados/reemplazados) y `tests/test_deploy_contract.py`
- Create: `infra/twonode/README.md`
- Modify: `CLAUDE.md` (sección de comandos/arquitectura donde menciona `deploy/`)
- Modify: `docs/implementation-status.md` (fila del split two-node)
- Modify: `src/eovrt_media/tools/debug_run.py:12` (referencia a `deploy/README.md`)

**Interfaces:**
- Consumes: manifiestos de Task 4 verificados por Task 5.

- [ ] **Step 1: Migrar los configs e2e restantes y borrar deploy/**

```bash
cp deploy/configs/e2e_fp16_node_a.yaml deploy/configs/e2e_fp16_node_b.yaml infra/twonode/configs/
git rm -r deploy/
git rm tests/test_deploy_contract.py
```

(En los dos `e2e_fp16_*.yaml` copiados, actualizar el comentario de cabecera si referencia `deploy/` y agregar `request_timeout_ms: 10000` bajo `transport:` para consistencia.)

- [ ] **Step 2: README de operación**

Crear `infra/twonode/README.md`:

```markdown
# Split two-node EBE (Nodo A edge + Nodo B GPU)

Despliegue Docker de la topología EBE: **Nodo A** (edge, sin GPU: ingesta + rate
control + normalización + servidor ZeroMQ) y **Nodo B** (GPU: inferencia +
postproceso + artefactos). Un run por `up`: ambos contenedores son procesos batch
que terminan al agotar el stream — no son servicios de larga vida (eso es el DBE
de `infra/docker-compose.yml`). Nodo B es el dueño del `run_id` y de `runs/`.

Equivalencia validada (gate 2026-06-24): mAP idéntico DBE vs EBE; JPEG q90 con
pérdida marginal (solo vests limítrofes).

## Single-host (smoke / demo)

```bash
cd infra/twonode
docker compose build            # eovrt/media-plane-edge + eovrt/media-plane
docker compose up               # corre el run de configs/two_node_{a,b}.yaml
# Nodo B escribe runs/<run_id>/ en el runs/ del repo (montado).
docker compose down
```

Default: `model.ref: mock` + `max_units: 20` (sin GPU; comentar el bloque
`deploy.resources` de node-b si el host no tiene nvidia-container-toolkit).
Para un run real: cambiar `model.ref` a `yoloe/yoloe-26s` en AMBAS configs
(el ref debe coincidir — Nodo A lo usa para el input_spec de normalización).

## Dos hosts (edge + GPU por LAN)

1. Host edge: `docker compose -f docker-compose.node-a.yml up`
2. Host GPU: editar `configs/two_node_b.yaml` → `endpoint: tcp://<ip-edge>:5555`
   y `heartbeat_endpoint: tcp://<ip-edge>:5556`, después
   `docker compose -f docker-compose.node-b.yml up`

## Fallas (comportamiento esperado)

- **Muere el Nodo A a mitad de corrida** → el Nodo B corta con error explícito
  dentro de `transport.request_timeout_ms` (default 10s) y exit != 0. Sin
  reconexión automática: relanzar el run.
- **Muere el Nodo B** → el Nodo A corta por heartbeat timeout
  (`transport.heartbeat_timeout_ms`, default 5s).

## Fuentes

`image_folder` (dataset montado en `/datasets`), `video_file`, `rtsp`. La cámara
**OAK-D Pro PoE** (`source.type: oak_d`) está declarada con contrato de config
(`url` = IP del dispositivo PoE o null para autodescubrimiento; fuente live sin
`len()`, como rtsp) pero NO implementada — requiere DepthAI y el hardware.

## Seguridad (riesgo aceptado)

Los puertos ZeroMQ (5555 datos, 5556 heartbeat) **no tienen autenticación ni
cifrado**: cualquiera con acceso de red puede inyectar frames o consumir el
stream. Aceptado para la LAN de laboratorio del proyecto académico. No publicar
esos puertos fuera de la LAN; revisar esta decisión si el despliegue cambia.
```

- [ ] **Step 3: Actualizar referencias en docs**

1. `CLAUDE.md`: reemplazar la mención a `deploy/` (artefactos two-node deprecados) por una línea que apunte a `infra/twonode/` (split two-node Fase 2, ver su README). Buscar con `grep -n "deploy" CLAUDE.md`.
2. `docs/implementation-status.md`: la fila "Imagen GPU única (Fase 1) + healthchecks" menciona que el split two-node se difiere a Fase 2 — actualizarla: split two-node disponible en `infra/twonode/` (Fase 2).
3. `src/eovrt_media/tools/debug_run.py` línea 12: cambiar `ver README.md y deploy/README.md` por `ver infra/twonode/README.md`.
4. `grep -rn "deploy/" --include="*.py" --include="*.md" src tests docs CLAUDE.md Makefile` — limpiar cualquier referencia restante a `deploy/` (excepto menciones históricas en specs/planes fechados, que se dejan).

- [ ] **Step 4: Suite completa + lint (sin commit)**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests`
Expected: `430 passed` (431 − los 3 de `test_deploy_contract.py` borrado + 2... verificar el número exacto: la suite debe quedar verde sin tests que referencien `deploy/`), lint limpio.

---

### Task 7: Smoke de aceptación (manual, criterio de la fase)

**Files:** ninguno (verificación operativa; requiere Tasks 1-6 y Docker con daemon activo). Al terminar, registrar el resultado en `infra/twonode/README.md` (sección nueva "Ejecutado y verificado") — mismo formato que `e-ovrt_experimental-setup/infra/platform/README.md`.

- [ ] **Step 1: Build de ambas imágenes**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane/infra/twonode
docker compose build
```
Expected: `eovrt/media-plane-edge:latest` (chica, sin torch — verificar con `docker image ls eovrt/media-plane-edge` que pese cientos de MB, no >10GB) y `eovrt/media-plane:latest`.

- [ ] **Step 2: Run mock end-to-end (sin GPU)**

```bash
docker compose up --abort-on-container-exit
```
Expected: Nodo A sirve 20 units y termina exit 0; Nodo B consume, escribe `../../runs/<run_id>/` con `detections.jsonl` + `summary.json` (status succeeded, 20 units) y termina exit 0. Verificar: `ls -t ../../runs | head -1` y `python3 -c "import json;print(json.load(open('../../runs/<run_id>/summary.json'))['status'])"` → `succeeded`.

- [ ] **Step 3: Caso de falla — matar el Nodo A a mitad de corrida**

En `configs/two_node_a.yaml` y `two_node_b.yaml` subir `max_units` a 200 (run más largo). Después:

```bash
docker compose up -d
sleep 3 && docker compose kill node-a
docker compose logs -f node-b   # esperar el corte
docker compose ps -a
```
Expected: node-b sale con exit != 0 en ≤ ~15s (request_timeout_ms=10000 + margen), y sus logs muestran `Nodo A no respondió en 10000 ms`. **Este es el criterio de aceptación del hardening.** Restaurar `max_units: 20` al terminar.

- [ ] **Step 4: (Opcional, si hay GPU + pesos) Run real con YOLOE-26s**

Cambiar `model.ref` a `yoloe/yoloe-26s` en ambas configs, descomentar/verificar el bloque GPU de node-b, `docker compose up --abort-on-container-exit`. Expected: `summary.json` con detecciones reales y `device: cuda`. Restaurar `model.ref: mock`.

- [ ] **Step 5: Documentar el resultado (sin commit)**

Agregar la sección "Ejecutado y verificado (fecha)" a `infra/twonode/README.md` con: imágenes construidas (tamaños), resultado del run mock, resultado del caso de falla (tiempo de corte observado), y del run GPU si se hizo. Dejar todo en el working tree para el commit del usuario.

---

## Self-review (hecho al escribir el plan)

- **Cobertura del spec**: §2.1 entrypoint→Task 2; §3 timeout→Task 1; §2.2 layout infra/twonode + limpieza two_node_local→Tasks 3/4/6; §2.3 configs→Task 4; §4 OAK-D (solo doc)→README Task 6; §5 seguridad (README + comentarios compose)→Tasks 4/6; §6 testing→Tasks 1/2/5 + smoke Task 7; §7 exclusiones respetadas (sin auth, sin reconexión, sin Dockerfile.node-b, sin integración consola). Sin gaps.
- **Consistencia de tipos**: `request_timeout_ms` mismo nombre en schema/adapter/factory/two_node/configs YAML/tests (Tasks 1, 4, 5). `_RUNNERS` definido en Task 2 y monkeypatcheado en sus tests. `eovrt/media-plane-edge:latest` consistente entre Dockerfile/composes/test de contrato.
- **Placeholders**: los dos puntos genuinamente inciertos (forma exacta de la config mínima en el test de Task 2; resolución de `prompts.ref` al cargar configs en Task 5) llevan instrucción explícita de cómo resolverlos y cuál es el contrato invariante — no son "TBD".
- **Conteos de tests**: los números esperados (422/427/431/430) son orientativos; el invariante es "suite completa verde, sin regresiones" — si un conteo difiere por ajustes del implementador, verificar que la diferencia se explica por los tests agregados/borrados en la task correspondiente.
