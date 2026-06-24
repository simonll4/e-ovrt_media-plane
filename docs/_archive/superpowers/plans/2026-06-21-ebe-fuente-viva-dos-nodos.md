# EBE completo (fuente viva RTSP + dos nodos ZeroMQ) — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completar el Escenario B (EBE) del plano de medios: fuente viva RTSP en un solo host (Fase 1), transporte de red ZeroMQ para dos nodos (Fase 2), y empaquetado Docker (Fase 2c).

**Architecture:** Reusar el andamiaje existente sin tocar contratos ni lógica. Fase 1 agrega `RtspSource` (fuente viva con timestamps de captura y reconexión) consumida por el pipeline actual con política `bounded_freshness`. Fase 2 reemplaza la cola en memoria por un `NetworkTransportAdapter` ZeroMQ REQ/REP entre dos procesos, con los comandos CLI `run-producer`/`run-consumer`. Fase 2c empaqueta cada nodo en su propia imagen Docker.

**Tech Stack:** Python 3.11+, Pydantic v2, OpenCV (`cv2.VideoCapture`), ZeroMQ (`pyzmq`), msgpack para serialización de metadata, pytest, Docker.

**Spec:** `docs/superpowers/specs/2026-06-21-ebe-fuente-viva-dos-nodos-design.md`

## Global Constraints

- Python ≥ 3.11; Pydantic v2; OpenCV; ZeroMQ vía `pyzmq`.
- TDD estricto: el test rojo primero, luego la implementación mínima.
- **Sin `Co-Authored-By` en los commits.**
- Las features no implementadas (`oak_d`, `two_node`/`network` antes de Fase 2, `fp16`) fallan explícito (`NotImplementedError`/`ValueError`), nunca con fallback silencioso.
- Comandos desde la raíz del repo `e-ovrt_media-plane` con el venv activo: `source .venv/bin/activate`.
- Un solo modelo por corrida; no se tocan catálogos de `configs/`.

## File Structure

**Fase 1 (single-host):**
- Create: `src/eovrt_media/sources/rtsp_source.py` — `RtspSource`
- Create: `src/eovrt_media/sources/oak_d_source.py` — `OakDSource` (declarado)
- Modify: `src/eovrt_media/sources/__init__.py` — exportar nuevas fuentes
- Modify: `src/eovrt_media/config/schemas.py` — campos RTSP en `SourceSection`
- Modify: `src/eovrt_media/config/loader.py` — derivación rtsp, ungate rtsp, gate `oak_d`
- Modify: `src/eovrt_media/runtime/pipeline.py` — `create_source` para rtsp/oak_d, `len()` negativo → `total=None`
- Create: `tests/test_rtsp_source.py`, `tests/test_oak_d_source.py`
- Modify: `tests/test_config_deployment.py`

**Fase 2 (two-node):**
- Modify: `pyproject.toml` — dependencia `pyzmq`
- Create: `src/eovrt_media/transport/serialization.py` — serializar/deserializar `NormalizedUnit` + mensajes de control
- Create: `src/eovrt_media/transport/network.py` — `NetworkTransportAdapter`
- Modify: `src/eovrt_media/transport/declared.py` — quitar `NetworkTransportAdapter` (queda solo `IpcTransportAdapter`)
- Modify: `src/eovrt_media/transport/factory.py` — cablear `network` con `role` + heartbeat
- Modify: `src/eovrt_media/transport/__init__.py` — exportar `NetworkTransportAdapter`
- Modify: `src/eovrt_media/config/schemas.py` — heartbeat en `TransportConfig`
- Modify: `src/eovrt_media/config/loader.py` — ungate `two_node`/`network`
- Modify: `src/eovrt_media/runtime/pipeline.py` — extraer `run_producer_loop` / `run_consumer_loop`
- Modify: `src/eovrt_media/cli.py` — comandos `run-producer` / `run-consumer`
- Create: `tests/test_serialization.py`, `tests/test_network_transport.py`, `tests/test_cli_two_node.py`

**Fase 2c (Docker):**
- Modify: `pyproject.toml` — extras `edge` / `gpu`
- Create: `docker/Dockerfile.node-a`, `docker/Dockerfile.node-b`, `docker/docker-compose.yml`
- Create: `docs/deployment/two-node-docker.md`

---

# FASE 1 — EBE en un solo host

## Task 1: `RtspSource` — fuente viva RTSP con timestamps y reconexión

**Files:**
- Create: `src/eovrt_media/sources/rtsp_source.py`
- Test: `tests/test_rtsp_source.py`

**Interfaces:**
- Consumes: `BaseSource` (`src/eovrt_media/sources/base.py`), `VisualUnit` (`src/eovrt_media/contracts/visual_unit.py`).
- Produces: `RtspSource(url: str, reconnect_retries: int = 5, reconnect_delay_ms: int = 1000, max_units: int | None = None)`. Método sobreescribible `_open_capture(self, url: str) -> cv2.VideoCapture`. `__iter__` produce `VisualUnit(source_type="video_frame", timestamp_ms=<reloj de pared al capturar>)`. `__len__() == -1`.

- [ ] **Step 1: Escribir los tests rojos**

Crear `tests/test_rtsp_source.py`:

```python
"""Tests de RtspSource usando un archivo de video como cámara simulada."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.sources.rtsp_source import RtspSource


@pytest.fixture
def fake_stream(tmp_path: Path) -> Path:
    """Genera un .mp4 de 5 frames que sustituye a la cámara RTSP."""
    video_path = tmp_path / "fake_stream.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48)
    )
    for i in range(5):
        frame = np.full((48, 64, 3), i * 10, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    assert video_path.exists()
    return video_path


def _patch_capture(monkeypatch, video_path: Path) -> None:
    monkeypatch.setattr(
        RtspSource,
        "_open_capture",
        lambda self, url: cv2.VideoCapture(str(video_path)),
    )


class TestRtspSource:
    def test_yields_units_with_capture_timestamps(self, fake_stream, monkeypatch):
        _patch_capture(monkeypatch, fake_stream)
        source = RtspSource(url="rtsp://fake/stream", max_units=5)
        units = list(source)
        assert len(units) == 5
        assert all(u.source_type == "video_frame" for u in units)
        assert all(u.timestamp_ms is not None and u.timestamp_ms > 0 for u in units)
        # Los timestamps son de reloj de pared, no decrecientes.
        ts = [u.timestamp_ms for u in units]
        assert ts == sorted(ts)

    def test_len_is_indefinite(self, fake_stream, monkeypatch):
        _patch_capture(monkeypatch, fake_stream)
        source = RtspSource(url="rtsp://fake/stream")
        assert len(source) == -1

    def test_max_units_limits_iteration(self, fake_stream, monkeypatch):
        _patch_capture(monkeypatch, fake_stream)
        source = RtspSource(url="rtsp://fake/stream", max_units=3)
        assert len(list(source)) == 3

    def test_reconnects_before_giving_up(self, fake_stream, monkeypatch):
        attempts = {"count": 0}

        def flaky_open(self, url):
            attempts["count"] += 1
            if attempts["count"] < 3:
                cap = cv2.VideoCapture(str(tmp_nonexistent))  # no abre
                return cap
            return cv2.VideoCapture(str(fake_stream))

        tmp_nonexistent = fake_stream.parent / "missing.mp4"
        monkeypatch.setattr(RtspSource, "_open_capture", flaky_open)
        source = RtspSource(
            url="rtsp://fake/stream", reconnect_retries=5, reconnect_delay_ms=0, max_units=2
        )
        units = list(source)
        assert len(units) == 2
        assert attempts["count"] >= 3  # reintentó hasta conectar

    def test_raises_after_exhausting_retries(self, tmp_path, monkeypatch):
        missing = tmp_path / "missing.mp4"
        monkeypatch.setattr(
            RtspSource, "_open_capture", lambda self, url: cv2.VideoCapture(str(missing))
        )
        source = RtspSource(
            url="rtsp://fake/stream", reconnect_retries=2, reconnect_delay_ms=0
        )
        with pytest.raises(ConnectionError, match="RTSP"):
            list(source)
```

- [ ] **Step 2: Verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_rtsp_source.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'eovrt_media.sources.rtsp_source'`.

- [ ] **Step 3: Implementar `RtspSource`**

Crear `src/eovrt_media/sources/rtsp_source.py`:

```python
"""Fuente viva RTSP — cámara IP estándar (EZVIZ, Hikvision, etc.)."""
from __future__ import annotations

import logging
import time
from typing import Iterator

import cv2

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource

logger = logging.getLogger(__name__)


class RtspSource(BaseSource):
    """Lee un stream RTSP y produce VisualUnits con timestamp de captura.

    A diferencia de VideoFileSource: nunca hace looping, marca el timestamp con
    el reloj de pared al capturar (hace significativo max_staleness_ms), y
    reintenta la conexión ante cortes de red.
    """

    def __init__(
        self,
        url: str,
        reconnect_retries: int = 5,
        reconnect_delay_ms: int = 1000,
        max_units: int | None = None,
    ) -> None:
        self.url = url
        self.reconnect_retries = reconnect_retries
        self.reconnect_delay_ms = reconnect_delay_ms
        self.max_units = max_units

    def _open_capture(self, url: str) -> cv2.VideoCapture:
        """Abre la captura RTSP. Sobreescribible en tests para usar un archivo."""
        return cv2.VideoCapture(url)

    def _connect(self) -> cv2.VideoCapture:
        """Intenta abrir la captura con reintentos; lanza ConnectionError al agotar."""
        for attempt in range(1, self.reconnect_retries + 1):
            cap = self._open_capture(self.url)
            if cap.isOpened():
                return cap
            cap.release()
            logger.warning(
                "RTSP no disponible (intento %d/%d): %s",
                attempt, self.reconnect_retries, self.url,
            )
            if self.reconnect_delay_ms > 0:
                time.sleep(self.reconnect_delay_ms / 1000.0)
        raise ConnectionError(
            f"RTSP: no se pudo conectar tras {self.reconnect_retries} intentos: {self.url}"
        )

    def __iter__(self) -> Iterator[VisualUnit]:
        cap = self._connect()
        emitted = 0
        try:
            while True:
                if self.max_units is not None and emitted >= self.max_units:
                    return
                ok, frame = cap.read()
                if not ok:
                    cap.release()
                    cap = self._connect()  # reintenta; lanza si agota
                    ok, frame = cap.read()
                    if not ok:
                        return  # fin de stream tras reconexión
                height, width = frame.shape[:2]
                timestamp_ms = time.time() * 1000.0
                yield VisualUnit(
                    unit_id=f"frame_{emitted:06d}",
                    source_path=self.url,
                    source_type="video_frame",
                    frame_index=emitted,
                    width=width,
                    height=height,
                    timestamp_ms=round(timestamp_ms, 2),
                )
                emitted += 1
        finally:
            cap.release()

    def __len__(self) -> int:
        return -1  # fuente viva: longitud indefinida
```

- [ ] **Step 4: Verificar que pasan**

Run: `source .venv/bin/activate && pytest tests/test_rtsp_source.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/sources/rtsp_source.py tests/test_rtsp_source.py
git commit -m "feat: agregar RtspSource (fuente viva RTSP con timestamps y reconexión)"
```

---

## Task 2: `OakDSource` declarado (no implementado)

**Files:**
- Create: `src/eovrt_media/sources/oak_d_source.py`
- Test: `tests/test_oak_d_source.py`

**Interfaces:**
- Produces: `OakDSource(url: str | None = None, max_units: int | None = None)`. `__iter__` lanza `NotImplementedError`. `__len__() == -1`.

- [ ] **Step 1: Escribir el test rojo**

Crear `tests/test_oak_d_source.py`:

```python
"""OakDSource está declarada pero no implementada."""
from __future__ import annotations

import pytest

from eovrt_media.sources.oak_d_source import OakDSource


def test_oak_d_iter_raises_not_implemented():
    source = OakDSource(url=None)
    with pytest.raises(NotImplementedError, match="OAK-D"):
        list(source)


def test_oak_d_len_is_indefinite():
    assert len(OakDSource(url=None)) == -1
```

- [ ] **Step 2: Verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_oak_d_source.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar el stub**

Crear `src/eovrt_media/sources/oak_d_source.py`:

```python
"""OakDSource — cámara OAK-D Pro PoE vía DepthAI. Declarada, no implementada."""
from __future__ import annotations

from typing import Iterator

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource


class OakDSource(BaseSource):
    """Fuente OAK-D Pro PoE vía DepthAI SDK — declarada, no implementada.

    Requires: pip install depthai
    Produces: frames RGB vía dai.Pipeline XLinkOut.
    Ver docs/contexto/oak-d-integration.md cuando se implemente.
    """

    def __init__(self, url: str | None = None, max_units: int | None = None) -> None:
        self.url = url
        self.max_units = max_units

    def __iter__(self) -> Iterator[VisualUnit]:
        raise NotImplementedError(
            "OakDSource (source.type=oak_d) requiere DepthAI instalado y configurado. "
            "Declarada para la cámara OAK-D Pro PoE; pendiente de implementación."
        )

    def __len__(self) -> int:
        return -1
```

- [ ] **Step 4: Verificar que pasa**

Run: `source .venv/bin/activate && pytest tests/test_oak_d_source.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Actualizar exports y commit**

Modificar `src/eovrt_media/sources/__init__.py` para que quede:

```python
"""Módulo de fuentes de datos visuales del plano de medios E-OVRT."""

from eovrt_media.sources.base import BaseSource
from eovrt_media.sources.image_folder_source import ImageFolderSource
from eovrt_media.sources.oak_d_source import OakDSource
from eovrt_media.sources.rtsp_source import RtspSource
from eovrt_media.sources.video_file_source import VideoFileSource

__all__ = [
    "BaseSource",
    "ImageFolderSource",
    "OakDSource",
    "RtspSource",
    "VideoFileSource",
]
```

```bash
git add src/eovrt_media/sources/oak_d_source.py src/eovrt_media/sources/__init__.py tests/test_oak_d_source.py
git commit -m "feat: declarar OakDSource (OAK-D Pro PoE) sin implementar"
```

---

## Task 3: Config — campos RTSP, derivación y gating

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (`SourceSection`, ~líneas 100-117)
- Modify: `src/eovrt_media/config/loader.py` (`_validate_deployment`, ~líneas 125-128)
- Test: `tests/test_config_deployment.py`

**Interfaces:**
- Consumes: `load_run_config` (`src/eovrt_media/config/loader.py`), `SourceSection` (`schemas.py`).
- Produces: `source.type=rtsp` válido (no gateado), deriva `kind=live` + `policy=bounded_freshness`. `SourceSection` con `url`, `reconnect_retries: int = 5`, `reconnect_delay_ms: int = 1000`. `source.type=oak_d` gateado con `NotImplementedError`.

- [ ] **Step 1: Escribir los tests rojos**

Agregar a `tests/test_config_deployment.py` al final del archivo:

```python
class TestRtspSourceConfig:
    def test_rtsp_derives_live_and_bounded_freshness(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            source={"type": "rtsp", "path": "rtsp://cam/stream", "url": "rtsp://cam/stream"},
        )
        assert cfg.source.kind == "live"
        assert cfg.rate_control.policy == "bounded_freshness"

    def test_rtsp_fields_have_defaults(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            source={"type": "rtsp", "path": "rtsp://cam/stream", "url": "rtsp://cam/stream"},
        )
        assert cfg.source.reconnect_retries == 5
        assert cfg.source.reconnect_delay_ms == 1000

    def test_oak_d_source_type_is_gated(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="oak_d.*implementad"):
            _minimal_config(
                tmp_path,
                source={"type": "oak_d", "path": "oak://device"},
            )
```

Nota: el `_minimal_config` existente exige `path`; RTSP usa `url` pero mantenemos `path` por compatibilidad del schema (`SourceSection.path` es obligatorio). El pipeline usará `url` cuando exista.

- [ ] **Step 2: Verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_config_deployment.py::TestRtspSourceConfig -v`
Expected: FAIL — `rtsp` hoy está gateado por `_LIVE_TYPES` (lanza `NotImplementedError` para todo live), y `oak_d` no existe como tipo.

- [ ] **Step 3: Agregar campos RTSP a `SourceSection`**

En `src/eovrt_media/config/schemas.py`, dentro de `class SourceSection`, agregar tras `vocabulary` (línea ~117):

```python
    # Fuente viva (RTSP / cámaras IP)
    url: str | None = None
    reconnect_retries: int = 5
    reconnect_delay_ms: int = 1000
```

- [ ] **Step 4: Ajustar el gating en el loader**

En `src/eovrt_media/config/loader.py`, reemplazar el bloque final de `_validate_deployment` (líneas ~125-128):

```python
    if config.source.type.lower() in _LIVE_TYPES:
        raise NotImplementedError(
            f"source.type={config.source.type!r} está declarado pero no implementado."
        )
```

por:

```python
    if config.source.type.lower() == "oak_d":
        raise NotImplementedError(
            "source.type=oak_d (OAK-D Pro PoE) está declarado pero no implementado."
        )
```

Y actualizar el conjunto de tipos vivos en la línea ~26 para incluir `oak_d` (así `oak_d` también deriva `kind=live`):

```python
_LIVE_TYPES = {"camera", "rtsp", "oak_d"}
```

(`rtsp` queda como tipo vivo válido y deja de estar gateado; `oak_d` deriva `kind=live` pero su gate específico lo bloquea más abajo.)

- [ ] **Step 5: Verificar la suite de config**

Run: `source .venv/bin/activate && pytest tests/test_config_deployment.py -v`
Expected: PASS (todos, incluidos los 3 nuevos).

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/config/schemas.py src/eovrt_media/config/loader.py tests/test_config_deployment.py
git commit -m "feat: habilitar source.type=rtsp en config y gatear oak_d"
```

---

## Task 4: Cablear fuentes vivas en el pipeline y tolerar longitud indefinida

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py` (`create_source`, ~líneas 34-54; `run_pipeline`, ~líneas 134, 183)
- Test: `tests/test_pipeline_mock.py`

**Interfaces:**
- Consumes: `RtspSource`, `OakDSource`, `create_source(config)`.
- Produces: `create_source` devuelve `RtspSource` para `type in {rtsp}` y `OakDSource` para `type==oak_d`; la barra de progreso usa `total=None` cuando `len(source) < 0`.

- [ ] **Step 1: Escribir el test rojo (longitud indefinida no rompe el pipeline)**

Agregar a `tests/test_pipeline_mock.py` dentro de `class TestPipelineMock`:

```python
    def test_live_source_with_negative_len_runs(self, tmp_path, monkeypatch):
        """Una fuente viva (len=-1) corre limitada por max_units sin romper el progreso."""
        import cv2
        import numpy as np
        from eovrt_media.runtime import pipeline as pipeline_module
        from eovrt_media.sources.rtsp_source import RtspSource

        video_path = tmp_path / "stream.mp4"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48)
        )
        for i in range(6):
            writer.write(np.full((48, 64, 3), i * 10, dtype=np.uint8))
        writer.release()

        monkeypatch.setattr(
            RtspSource, "_open_capture", lambda self, url: cv2.VideoCapture(str(video_path))
        )

        config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
        config.model.adapter = "mock"
        config.source.type = "rtsp"
        config.source.url = "rtsp://fake/stream"
        config.source.kind = "live"
        config.rate_control.policy = "bounded_freshness"
        config.run.max_units = 4
        config.outputs.base_dir = str(tmp_path / "runs")
        config.outputs.run_dir = str(tmp_path / "runs")
        config.outputs.save_previews = False

        run_id = run_pipeline(config)
        summary = json.loads(
            (Path(config.outputs.base_dir) / run_id / "summary.json").read_text()
        )
        total = summary["units_processed"] + summary["units_failed"] + summary["units_dropped"]
        assert total <= 4
        assert summary["units_processed"] >= 1
```

- [ ] **Step 2: Verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_pipeline_mock.py::TestPipelineMock::test_live_source_with_negative_len_runs -v`
Expected: FAIL — `create_source` no conoce `rtsp` (lanza `ValueError`), y/o la barra recibe `total=-1`.

- [ ] **Step 3: Extender `create_source` y la barra de progreso**

En `src/eovrt_media/runtime/pipeline.py`, dentro de `create_source`, agregar antes del `raise ValueError` final:

```python
    if source_type == "rtsp":
        from eovrt_media.sources import RtspSource

        return RtspSource(
            url=config.source.url or config.source.path,
            reconnect_retries=config.source.reconnect_retries,
            reconnect_delay_ms=config.source.reconnect_delay_ms,
            max_units=config.run.max_units,
        )
    if source_type == "oak_d":
        from eovrt_media.sources import OakDSource

        return OakDSource(url=config.source.url or config.source.path,
                          max_units=config.run.max_units)
```

Modificar el cálculo de `source_count` (línea ~134) y el `add_task` (línea ~183). Cambiar:

```python
        source_count = len(source)
```

por:

```python
        source_count = len(source)
        progress_total = source_count if source_count >= 0 else None
```

y cambiar:

```python
            task = progress.add_task("Procesando unidades visuales...", total=source_count)
```

por:

```python
            task = progress.add_task("Procesando unidades visuales...", total=progress_total)
```

- [ ] **Step 4: Verificar el test y la suite completa**

Run: `source .venv/bin/activate && pytest tests/test_pipeline_mock.py -v && pytest -q && ruff check src tests`
Expected: PASS, sin errores de Ruff.

- [ ] **Step 5: Commit (cierra Fase 1)**

```bash
git add src/eovrt_media/runtime/pipeline.py tests/test_pipeline_mock.py
git commit -m "feat: cablear RtspSource/OakDSource y tolerar fuentes de longitud indefinida"
```

**✅ Checkpoint Fase 1:** EBE single-host funcional. `eovrt-media run --config <rtsp.yaml>` consume una cámara RTSP con `bounded_freshness`. Antes de seguir a Fase 2, validar manualmente con una cámara real si está disponible (opcional).

---

# FASE 2 — EBE en dos nodos (ZeroMQ)

## Task 5: Agregar dependencia `pyzmq`

**Files:**
- Modify: `pyproject.toml` (lista `dependencies`)

- [ ] **Step 1: Agregar `pyzmq` y `msgpack` a dependencias**

En `pyproject.toml`, en la lista `dependencies`, agregar tras `"ultralytics",`:

```toml
    "pyzmq",
    "msgpack",
```

- [ ] **Step 2: Instalar en el venv**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: instala `pyzmq` y `msgpack` sin errores.

- [ ] **Step 3: Verificar import**

Run: `source .venv/bin/activate && python -c "import zmq, msgpack; print(zmq.zmq_version(), msgpack.version)"`
Expected: imprime versiones sin error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: agregar pyzmq y msgpack para transporte de red"
```

---

## Task 6: Serialización de `NormalizedUnit` y mensajes de control

**Files:**
- Create: `src/eovrt_media/transport/serialization.py`
- Test: `tests/test_serialization.py`

**Interfaces:**
- Consumes: `NormalizedUnit`, `PayloadFormat`, `ResizeTransform`, `END` (`src/eovrt_media/contracts/normalized_unit.py`).
- Produces:
  - `REQUEST: bytes`, `END_MSG: bytes`, `HEARTBEAT: bytes` (constantes de control).
  - `serialize_unit(unit: NormalizedUnit) -> bytes`
  - `deserialize_unit(data: bytes) -> NormalizedUnit`
  - `is_control(data: bytes) -> bool`

- [ ] **Step 1: Escribir los tests rojos**

Crear `tests/test_serialization.py`:

```python
"""Round-trip de NormalizedUnit por el wire y mensajes de control."""
from __future__ import annotations

import numpy as np

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform,
)
from eovrt_media.transport.serialization import (
    REQUEST, END_MSG, HEARTBEAT,
    serialize_unit, deserialize_unit, is_control,
)


def _make_unit(fmt: PayloadFormat) -> NormalizedUnit:
    if fmt == PayloadFormat.FP32:
        payload = np.random.rand(640, 640, 3).astype(np.float32)
    else:
        payload = (np.random.rand(640, 640, 3) * 255).astype(np.uint8)
    return NormalizedUnit(
        run_id="run_x",
        unit_id="frame_000001",
        source_id="cam0",
        source_path="rtsp://cam/stream",
        frame_index=1,
        timestamp_ms=12345.6,
        orig_width=1920,
        orig_height=1080,
        payload=payload,
        payload_format=fmt,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=0.33, scale_y=0.33, pad_x=0.0, pad_y=140.0),
    )


def test_roundtrip_uint8_rgb():
    unit = _make_unit(PayloadFormat.UINT8_RGB)
    restored = deserialize_unit(serialize_unit(unit))
    assert restored.unit_id == unit.unit_id
    assert restored.run_id == unit.run_id
    assert restored.timestamp_ms == unit.timestamp_ms
    assert restored.orig_width == unit.orig_width
    assert restored.target_size == unit.target_size
    assert restored.payload_format == PayloadFormat.UINT8_RGB
    assert restored.payload.dtype == np.uint8
    assert restored.payload.shape == (640, 640, 3)
    assert np.array_equal(restored.payload, unit.payload)
    assert restored.transform.pad_y == unit.transform.pad_y


def test_roundtrip_fp32():
    unit = _make_unit(PayloadFormat.FP32)
    restored = deserialize_unit(serialize_unit(unit))
    assert restored.payload.dtype == np.float32
    assert np.allclose(restored.payload, unit.payload)


def test_control_messages_recognized():
    assert is_control(REQUEST)
    assert is_control(END_MSG)
    assert is_control(HEARTBEAT)


def test_serialized_unit_is_not_control():
    unit = _make_unit(PayloadFormat.UINT8_RGB)
    assert not is_control(serialize_unit(unit))
```

- [ ] **Step 2: Verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_serialization.py -v`
Expected: FAIL con `ModuleNotFoundError: ...transport.serialization`.

- [ ] **Step 3: Implementar la serialización**

Crear `src/eovrt_media/transport/serialization.py`:

```python
"""Serialización de NormalizedUnit y mensajes de control para el wire ZeroMQ.

Formato de un frame de datos:
  [4 bytes big-endian: header_len][header_len bytes: msgpack(meta)][payload crudo]
El payload se reconstruye con dtype derivado de payload_format y shape de target_size.
"""
from __future__ import annotations

import struct

import msgpack
import numpy as np

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform,
)

# Mensajes de control (prefijo reservado que nunca aparece en un header válido)
REQUEST = b"\x00CTRL:REQUEST"
END_MSG = b"\x00CTRL:END"
HEARTBEAT = b"\x00CTRL:HEARTBEAT"

_CONTROL_PREFIX = b"\x00CTRL:"

_DTYPE_BY_FORMAT = {
    PayloadFormat.UINT8_RGB: np.uint8,
    PayloadFormat.FP32: np.float32,
}


def is_control(data: bytes) -> bool:
    """True si el mensaje es de control (REQUEST/END/HEARTBEAT)."""
    return data.startswith(_CONTROL_PREFIX)


def serialize_unit(unit: NormalizedUnit) -> bytes:
    """Empaqueta una NormalizedUnit como header msgpack + payload crudo."""
    meta = {
        "run_id": unit.run_id,
        "unit_id": unit.unit_id,
        "source_id": unit.source_id,
        "source_path": unit.source_path,
        "frame_index": unit.frame_index,
        "timestamp_ms": unit.timestamp_ms,
        "orig_width": unit.orig_width,
        "orig_height": unit.orig_height,
        "payload_format": unit.payload_format.value,
        "target_size": list(unit.target_size),
        "transform": {
            "scale_x": unit.transform.scale_x,
            "scale_y": unit.transform.scale_y,
            "pad_x": unit.transform.pad_x,
            "pad_y": unit.transform.pad_y,
        },
    }
    header = msgpack.packb(meta, use_bin_type=True)
    payload_bytes = np.ascontiguousarray(unit.payload).tobytes()
    return struct.pack(">I", len(header)) + header + payload_bytes


def deserialize_unit(data: bytes) -> NormalizedUnit:
    """Reconstruye una NormalizedUnit desde el formato de wire."""
    (header_len,) = struct.unpack(">I", data[:4])
    header = data[4 : 4 + header_len]
    payload_bytes = data[4 + header_len :]
    meta = msgpack.unpackb(header, raw=False)

    fmt = PayloadFormat(meta["payload_format"])
    dtype = _DTYPE_BY_FORMAT[fmt]
    target_h, target_w = meta["target_size"]
    payload = np.frombuffer(payload_bytes, dtype=dtype).reshape((target_h, target_w, 3))

    t = meta["transform"]
    return NormalizedUnit(
        run_id=meta["run_id"],
        unit_id=meta["unit_id"],
        source_id=meta["source_id"],
        source_path=meta["source_path"],
        frame_index=meta["frame_index"],
        timestamp_ms=meta["timestamp_ms"],
        orig_width=meta["orig_width"],
        orig_height=meta["orig_height"],
        payload=payload,
        payload_format=fmt,
        target_size=(target_h, target_w),
        transform=ResizeTransform(
            scale_x=t["scale_x"], scale_y=t["scale_y"], pad_x=t["pad_x"], pad_y=t["pad_y"]
        ),
    )
```

Nota: `np.frombuffer` devuelve un array de solo-lectura; si algún consumidor necesita escribir el payload, hará `.copy()`. Los adapters actuales no mutan el payload, así que es seguro.

- [ ] **Step 4: Verificar que pasan**

Run: `source .venv/bin/activate && pytest tests/test_serialization.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/transport/serialization.py tests/test_serialization.py
git commit -m "feat: serialización de NormalizedUnit y mensajes de control para ZeroMQ"
```

---

## Task 7: `NetworkTransportAdapter` — REQ/REP en loopback

**Files:**
- Create: `src/eovrt_media/transport/network.py`
- Modify: `src/eovrt_media/transport/declared.py` (quitar `NetworkTransportAdapter`)
- Modify: `src/eovrt_media/transport/__init__.py`
- Test: `tests/test_network_transport.py`

**Interfaces:**
- Consumes: `serialize_unit`, `deserialize_unit`, `REQUEST`, `END_MSG`, `is_control` (Task 6); `MemoryTransportAdapter` (`transport/memory.py`); `END`, `NormalizedUnit` (contratos).
- Produces: `NetworkTransportAdapter(role: str, endpoint: str, policy: str = "bounded_freshness", buffer_size: int = 2, max_staleness_ms: float | None = None)`.
  - role `producer`: `offer(unit)` llena un buffer interno con head-drop; un hilo servidor REP atiende `REQUEST` devolviendo el frame más antiguo; `close()` emite END a quien pida.
  - role `consumer`: `request()` hace el round-trip REQ y devuelve `NormalizedUnit` o `END`; `offer`/`close` no aplican.

- [ ] **Step 1: Escribir los tests rojos (loopback en el mismo proceso)**

Crear `tests/test_network_transport.py`:

```python
"""NetworkTransportAdapter sobre ZeroMQ en loopback (mismo proceso, dos hilos)."""
from __future__ import annotations

import threading

import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import (
    END, NormalizedUnit, PayloadFormat, ResizeTransform,
)
from eovrt_media.transport.network import NetworkTransportAdapter


def _unit(i: int) -> NormalizedUnit:
    return NormalizedUnit(
        run_id="run_x",
        unit_id=f"frame_{i:06d}",
        source_id="cam0",
        orig_width=64,
        orig_height=48,
        payload=(np.ones((640, 640, 3)) * i).astype(np.uint8),
        payload_format=PayloadFormat.UINT8_RGB,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
    )


@pytest.fixture
def endpoint() -> str:
    # Puerto efímero fijo del rango alto para loopback de test.
    return "tcp://127.0.0.1:5599"


def test_producer_consumer_roundtrip(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness", buffer_size=8
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)

    for i in range(3):
        producer.offer(_unit(i))
    producer.close()

    received = []
    while True:
        item = consumer.request()
        if item is END:
            break
        received.append(item)

    consumer.shutdown()
    producer.shutdown()

    assert [u.unit_id for u in received][:3] == [
        "frame_000000", "frame_000001", "frame_000002",
    ]
    assert received[0].payload.shape == (640, 640, 3)


def test_consumer_receives_end_when_buffer_empty_and_closed(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness", buffer_size=2
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)
    producer.close()
    assert consumer.request() is END
    consumer.shutdown()
    producer.shutdown()
```

- [ ] **Step 2: Verificar que fallan**

Run: `source .venv/bin/activate && pytest tests/test_network_transport.py -v`
Expected: FAIL con `ModuleNotFoundError: ...transport.network`.

- [ ] **Step 3: Implementar `NetworkTransportAdapter`**

Crear `src/eovrt_media/transport/network.py`:

```python
"""Backend de transporte ZeroMQ REQ/REP entre Nodo A (productor) y Nodo B (consumidor).

La política de rate control NO cambia: el lado productor reutiliza el buffer
bounded_freshness (head-drop). ZeroMQ es solo el canal entre los dos lados.
"""
from __future__ import annotations

import threading

import zmq

from eovrt_media.contracts.normalized_unit import END, NormalizedUnit
from eovrt_media.transport.base import TransportAdapter
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.serialization import (
    END_MSG, REQUEST, deserialize_unit, is_control, serialize_unit,
)


class NetworkTransportAdapter(TransportAdapter):
    """Adaptador de red con dos roles que comparten interfaz.

    role="producer": bind REP; sirve frames del buffer bounded_freshness.
    role="consumer": connect REQ; pide frames hasta recibir END.
    """

    def __init__(
        self,
        role: str,
        endpoint: str,
        policy: str = "bounded_freshness",
        buffer_size: int = 2,
        max_staleness_ms: float | None = None,
    ) -> None:
        if role not in {"producer", "consumer"}:
            raise ValueError(f"role debe ser 'producer' o 'consumer', no {role!r}.")
        self.role = role
        self.endpoint = endpoint
        self._ctx = zmq.Context.instance()

        if role == "producer":
            self._buffer = MemoryTransportAdapter(
                policy=policy, buffer_size=buffer_size, max_staleness_ms=max_staleness_ms
            )
            self.units_dropped = 0
            self._sock = self._ctx.socket(zmq.REP)
            self._sock.bind(endpoint)
            self._server = threading.Thread(target=self._serve, name="net-rep-server", daemon=True)
            self._server.start()
        else:
            self._sock = self._ctx.socket(zmq.REQ)
            self._sock.connect(endpoint)

    # --- productor ---

    def offer(self, unit: NormalizedUnit) -> None:
        self._buffer.offer(unit)

    def close(self) -> None:
        """Señala fin de stream al buffer; el server enviará END a los REQUEST."""
        self._buffer.close()

    def _serve(self) -> None:
        """Hilo REP: por cada REQUEST entrega el frame más antiguo o END."""
        while True:
            msg = self._sock.recv()
            if not is_control(msg):
                continue  # solo REQUEST/HEARTBEAT esperados del consumidor
            item = self._buffer.request()  # bloquea hasta frame o END
            if item is END:
                self._sock.send(END_MSG)
                return
            self._sock.send(serialize_unit(item))

    # --- consumidor ---

    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        self._sock.send(REQUEST)
        data = self._sock.recv()
        if data == END_MSG:
            return END
        return deserialize_unit(data)

    def shutdown(self) -> None:
        """Cierra socket y, en producer, espera el hilo servidor."""
        if self.role == "producer" and self._server.is_alive():
            self._server.join(timeout=5.0)
        self._sock.close(linger=0)
```

`MemoryTransportAdapter` ya expone `units_dropped`; para reflejar el conteo del buffer interno en el productor, exponer una propiedad. Agregar al final de `NetworkTransportAdapter` (dentro de la clase):

```python
    @property
    def buffer_units_dropped(self) -> int:
        return getattr(self._buffer, "units_dropped", 0) if self.role == "producer" else 0
```

- [ ] **Step 4: Quitar el stub de red de `declared.py`**

En `src/eovrt_media/transport/declared.py`, eliminar la clase `NetworkTransportAdapter` completa (queda solo `IpcTransportAdapter`). Eliminar también su import no usado de `END` si queda huérfano (mantener `NormalizedUnit, END` solo si `IpcTransportAdapter` los usa — sí los usa en las firmas).

- [ ] **Step 5: Actualizar imports y factory**

En `src/eovrt_media/transport/__init__.py`, agregar la exportación de `NetworkTransportAdapter` desde el nuevo módulo (mantener el resto de exports). Añadir:

```python
from eovrt_media.transport.network import NetworkTransportAdapter
```

y agregar `"NetworkTransportAdapter"` a `__all__`.

En `src/eovrt_media/transport/factory.py`, cambiar el import:

```python
from eovrt_media.transport.declared import IpcTransportAdapter, NetworkTransportAdapter
```

por:

```python
from eovrt_media.transport.declared import IpcTransportAdapter
from eovrt_media.transport.network import NetworkTransportAdapter
```

(El cableado de `role`/heartbeat en el factory se completa en la Task 9; por ahora el constructor de `NetworkTransportAdapter` ya acepta los parámetros existentes y `create_transport` sigue pasándole `endpoint`. Para que `create_transport` no rompa, ajustar la rama `network` para pasar `role="consumer"` por defecto — se parametriza en Task 9.)

Reemplazar la rama `network` de `create_transport`:

```python
    if backend == "network":
        if not endpoint:
            raise ValueError("backend=network requiere transport.endpoint configurado.")
        return NetworkTransportAdapter(endpoint=endpoint)
```

por:

```python
    if backend == "network":
        if not endpoint:
            raise ValueError("backend=network requiere transport.endpoint configurado.")
        return NetworkTransportAdapter(
            role=kwargs.get("role", "consumer"),
            endpoint=endpoint,
            policy=policy,
            buffer_size=buffer_size,
            max_staleness_ms=max_staleness_ms,
        )
```

y agregar `**kwargs` a la firma de `create_transport` (tras `endpoint`):

```python
def create_transport(
    *,
    backend: str = "memory",
    policy: str = "deterministic",
    max_queue_size: int = 8,
    buffer_size: int = 2,
    max_staleness_ms: float | None = None,
    endpoint: str | None = None,
    **kwargs,
) -> TransportAdapter:
```

- [ ] **Step 6: Verificar tests de red + suite de transporte existente**

Run: `source .venv/bin/activate && pytest tests/test_network_transport.py tests/test_transport.py -v`
Expected: PASS. Los tests de `declared.py` (`TestDeclaredStubs::test_network_request_raises`) ya no aplican al stub de red eliminado — eliminar ese test específico de `tests/test_transport.py` (mantener `test_ipc_offer_raises`).

- [ ] **Step 7: Commit**

```bash
git add src/eovrt_media/transport/network.py src/eovrt_media/transport/declared.py src/eovrt_media/transport/__init__.py src/eovrt_media/transport/factory.py tests/test_network_transport.py tests/test_transport.py
git commit -m "feat: NetworkTransportAdapter ZeroMQ REQ/REP (producer/consumer)"
```

---

## Task 8: Heartbeat y detección de caída

**Files:**
- Modify: `src/eovrt_media/transport/network.py`
- Test: `tests/test_network_transport.py`

**Interfaces:**
- Produces: `NetworkTransportAdapter` acepta `heartbeat_interval_ms: int = 1000`, `heartbeat_timeout_ms: int = 5000`. Método `is_peer_alive() -> bool` en el lado productor (True si recibió actividad del consumidor dentro del timeout).

- [ ] **Step 1: Escribir el test rojo**

Agregar a `tests/test_network_transport.py`:

```python
def test_producer_tracks_peer_activity(endpoint):
    producer = NetworkTransportAdapter(
        role="producer", endpoint=endpoint, policy="bounded_freshness",
        buffer_size=4, heartbeat_timeout_ms=10_000,
    )
    consumer = NetworkTransportAdapter(role="consumer", endpoint=endpoint)

    producer.offer(_unit(0))
    producer.close()
    _ = consumer.request()       # consume el frame → actividad registrada
    assert producer.is_peer_alive() is True

    consumer.shutdown()
    producer.shutdown()
```

- [ ] **Step 2: Verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_network_transport.py::test_producer_tracks_peer_activity -v`
Expected: FAIL — `is_peer_alive` y los parámetros de heartbeat no existen.

- [ ] **Step 3: Implementar tracking de actividad**

En `src/eovrt_media/transport/network.py`:

Agregar al `__init__` los parámetros (tras `max_staleness_ms`):

```python
        heartbeat_interval_ms: int = 1000,
        heartbeat_timeout_ms: int = 5000,
```

Guardar estado en el `__init__` para el rol productor (junto a la creación del buffer). Como `Date.now`/`time` real: usar `time.monotonic()`:

```python
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.heartbeat_timeout_ms = heartbeat_timeout_ms
        self._last_peer_activity = None  # se setea al recibir el primer REQUEST
```

Agregar `import time` al tope del módulo.

En `_serve`, tras `msg = self._sock.recv()`, registrar actividad:

```python
            self._last_peer_activity = time.monotonic()
```

Agregar el método:

```python
    def is_peer_alive(self) -> bool:
        """True si el consumidor mostró actividad dentro del timeout (lado productor)."""
        if self.role != "producer" or self._last_peer_activity is None:
            return False
        elapsed_ms = (time.monotonic() - self._last_peer_activity) * 1000.0
        return elapsed_ms <= self.heartbeat_timeout_ms
```

Nota de alcance: en este build el heartbeat se modela como "actividad reciente del peer en el canal REQ/REP" (cada REQUEST cuenta como latido). Un socket PUSH/PULL dedicado para keep-alive sin tráfico de frames queda declarado en el spec y diferido; el modelo actual basta para detectar un Nodo B que dejó de pedir.

- [ ] **Step 4: Verificar el test y la suite de red**

Run: `source .venv/bin/activate && pytest tests/test_network_transport.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/transport/network.py tests/test_network_transport.py
git commit -m "feat: tracking de actividad del peer (heartbeat) en NetworkTransportAdapter"
```

---

## Task 9: Config — heartbeat y ungate de two_node/network

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (`TransportConfig`, ~líneas 140-145)
- Modify: `src/eovrt_media/config/loader.py` (`_validate_deployment`, ~líneas 113-116)
- Test: `tests/test_config_deployment.py`

**Interfaces:**
- Produces: `TransportConfig` con `heartbeat_interval_ms: int = 1000`, `heartbeat_timeout_ms: int = 5000`. `topology.mode=two_node` + `transport.backend=network` + `endpoint` válido ya NO lanza `NotImplementedError`.

- [ ] **Step 1: Actualizar los tests de gating**

En `tests/test_config_deployment.py`, el test `TestConfigGating::test_two_node_topology_is_gated` ahora debe verificar que two_node + network **es válido**. Reemplazarlo por:

```python
    def test_two_node_with_network_is_valid(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            topology={"mode": "two_node"},
            transport={"backend": "network", "endpoint": "tcp://127.0.0.1:5555"},
        )
        assert cfg.topology.mode == "two_node"
        assert cfg.transport.backend == "network"
        assert cfg.transport.heartbeat_timeout_ms == 5000
```

Mantener `test_ipc_backend_is_gated` y `test_fp16_payload_format_is_gated` (siguen gateados).

- [ ] **Step 2: Verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_config_deployment.py::TestConfigGating::test_two_node_with_network_is_valid -v`
Expected: FAIL — hoy `two_node` lanza `NotImplementedError`.

- [ ] **Step 3: Agregar campos de heartbeat al schema**

En `src/eovrt_media/config/schemas.py`, dentro de `class TransportConfig`, agregar tras `endpoint`:

```python
    heartbeat_interval_ms: int = 1000
    heartbeat_timeout_ms: int = 5000
```

- [ ] **Step 4: Quitar el gate de two_node**

En `src/eovrt_media/config/loader.py`, eliminar el bloque (líneas ~113-116):

```python
    if config.topology.mode == "two_node":
        raise NotImplementedError(
            "topology.mode=two_node está declarado pero no implementado en este build."
        )
```

Mantener intactos los gates de `ipc` y `fp16`, y todas las validaciones de coherencia (two_node requiere network, etc.).

- [ ] **Step 5: Verificar la suite de config**

Run: `source .venv/bin/activate && pytest tests/test_config_deployment.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/config/schemas.py src/eovrt_media/config/loader.py tests/test_config_deployment.py
git commit -m "feat: habilitar topology=two_node/network y campos de heartbeat"
```

---

## Task 10: Refactor del pipeline en mitades reutilizables

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Test: `tests/test_pipeline_two_threads.py` (debe seguir pasando sin cambios)

**Interfaces:**
- Produces:
  - `run_producer_loop(source, rate_gate, spec, payload_format, transport, run_id, errors_queue, timings) -> None` (lo que hoy es `_producer_thread`, renombrado y público).
  - `run_consumer_loop(transport, adapter, normalizer, artifact_writer, run_context, tracker, config, prompt_texts, prompt_items, prompt_version, timings, progress=None, task=None, drain_errors=True) -> None` (extrae el cuerpo del `while True` consumidor del `run_pipeline` actual).
  - `run_pipeline` se reescribe para componer ambas mitades vía `MemoryTransportAdapter` (comportamiento idéntico).

- [ ] **Step 1: Verificar baseline verde**

Run: `source .venv/bin/activate && pytest tests/test_pipeline_two_threads.py -v`
Expected: PASS (es la red de seguridad del refactor; no se cambian estos tests).

- [ ] **Step 2: Extraer `run_consumer_loop` y `run_producer_loop`**

En `src/eovrt_media/runtime/pipeline.py`:

1. Renombrar `_producer_thread` a `run_producer_loop` (misma firma y cuerpo). Actualizar la referencia en `threading.Thread(target=...)`.

2. Extraer el cuerpo del bucle consumidor (`while True:` dentro de `run_pipeline`, líneas ~184-323) a una función `run_consumer_loop` con esta firma:

```python
def run_consumer_loop(
    transport,
    adapter,
    normalizer,
    artifact_writer,
    run_context,
    tracker,
    config,
    prompt_texts,
    prompt_items,
    prompt_version,
    timings,
    progress=None,
    task=None,
    drain_errors=True,
) -> None:
    """Consume del transporte hasta END: inferencia → postproceso → escritura."""
    while True:
        item = transport.request()
        if drain_errors:
            producer_errors = _drain_producer_errors(
                run_context._errors_queue, artifact_writer, run_context
            )
            if producer_errors and progress is not None and task is not None:
                progress.update(task, advance=producer_errors)
        if item is END:
            break
        # ... (todo el cuerpo actual del bucle: timer, forward, normalize,
        #      write_detection, previews, write_metric, manejo de errores) ...
        if progress is not None and task is not None:
            progress.update(task, advance=1)
```

El cuerpo interno (desde `timer = tracker.start_unit(...)` hasta el `progress.update(task, advance=1)` final) se mueve tal cual, reemplazando las referencias directas a `progress`/`task` por las guardas `if progress is not None and task is not None`.

3. Reescribir `run_pipeline` para que, tras crear `transport` y lanzar el hilo productor con `run_producer_loop`, invoque `run_consumer_loop(...)` dentro del bloque `with Progress(...)`, pasando `progress=progress, task=task`.

- [ ] **Step 3: Verificar que la suite completa sigue verde**

Run: `source .venv/bin/activate && pytest -q && ruff check src tests`
Expected: PASS sin regresiones, sin errores de Ruff.

- [ ] **Step 4: Commit**

```bash
git add src/eovrt_media/runtime/pipeline.py
git commit -m "refactor: extraer run_producer_loop/run_consumer_loop reutilizables"
```

---

## Task 11: Comandos CLI `run-producer` / `run-consumer`

**Files:**
- Modify: `src/eovrt_media/cli.py`
- Test: `tests/test_cli_two_node.py`

**Interfaces:**
- Consumes: `run_producer_loop`, `run_consumer_loop` (Task 10); `create_transport` con `role`; `load_run_config`.
- Produces: comandos `run-producer` (Nodo A) y `run-consumer` (Nodo B). Un consumidor en loopback contra un productor produce artefactos equivalentes a un `run` single-host con la misma fuente determinista.

- [ ] **Step 1: Escribir el test de integración rojo**

Crear `tests/test_cli_two_node.py`:

```python
"""Integración loopback de run-producer / run-consumer en el mismo proceso."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np

from eovrt_media.config import load_run_config
from eovrt_media.runtime.two_node import run_node_a, run_node_b


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _images(folder: Path, count: int = 4) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        cv2.imwrite(str(folder / f"img_{i:03d}.jpg"),
                    np.full((48, 64, 3), i * 20, dtype=np.uint8))


def test_two_node_loopback_produces_detections(tmp_path):
    images = tmp_path / "imgs"
    _images(images, 4)

    cfg = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    cfg.model.adapter = "mock"
    cfg.source.path = str(images)
    cfg.topology.mode = "two_node"
    cfg.transport.backend = "network"
    cfg.transport.endpoint = "tcp://127.0.0.1:5601"
    cfg.outputs.base_dir = str(tmp_path / "runs")
    cfg.outputs.run_dir = str(tmp_path / "runs")
    cfg.outputs.save_previews = False

    node_a = threading.Thread(target=run_node_a, args=(cfg,), daemon=True)
    node_a.start()

    run_id = run_node_b(cfg)
    node_a.join(timeout=10.0)

    detections = (Path(cfg.outputs.base_dir) / run_id / "detections.jsonl").read_text()
    events = [json.loads(line) for line in detections.splitlines()]
    assert len(events) == 4
```

Nota: el test ejercita las funciones `run_node_a`/`run_node_b` (la lógica de los comandos), no el subprocess de Typer, para mantener el test rápido y determinista. Los comandos CLI son envoltorios finos sobre estas funciones.

- [ ] **Step 2: Verificar que falla**

Run: `source .venv/bin/activate && pytest tests/test_cli_two_node.py -v`
Expected: FAIL con `ModuleNotFoundError: ...runtime.two_node`.

- [ ] **Step 3: Implementar `runtime/two_node.py`**

Crear `src/eovrt_media/runtime/two_node.py`:

```python
"""Orquestación de los dos nodos para topología distribuida."""
from __future__ import annotations

from rich.console import Console

from eovrt_media.config import RunConfig
from eovrt_media.contracts.normalized_unit import PayloadFormat
from eovrt_media.metrics import LatencyTracker, reset_gpu_peak_memory, get_gpu_memory_peak_mb
from eovrt_media.models import create_adapter
from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.runtime.pipeline import create_source, run_producer_loop, run_consumer_loop
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter
from eovrt_media.transport import RateGate, create_transport


def run_node_a(config: RunConfig, console: Console | None = None) -> None:
    """Nodo A: ingesta + rate control + normalización + servidor de red."""
    console = console or Console()
    source = create_source(config)
    adapter = create_adapter(config.model)  # solo para input_spec; no infiere
    rate_control = config.rate_control
    transport = create_transport(
        backend="network",
        role="producer",
        policy=rate_control.policy,
        buffer_size=rate_control.buffer_size,
        max_staleness_ms=rate_control.max_staleness_ms,
        endpoint=config.transport.endpoint,
    )
    import queue
    errors_queue: queue.SimpleQueue = queue.SimpleQueue()
    timings: dict[str, float] = {"backpressure_wait_ms": 0.0}
    run_producer_loop(
        source,
        RateGate(stride=rate_control.stride),
        adapter.input_spec,
        PayloadFormat(config.transport.payload_format),
        transport,
        run_id="",  # el run_id canónico vive en Nodo B
        errors_queue=errors_queue,
        timings=timings,
    )
    transport.shutdown()


def run_node_b(config: RunConfig, console: Console | None = None) -> str:
    """Nodo B: cliente de red + inferencia + postproceso + artefactos."""
    console = console or Console()
    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)
    tracker = LatencyTracker()
    artifact_writer.write_effective_config()

    prompt_texts = config.get_prompt_texts()
    prompt_items = config.get_prompt_items()
    prompt_version = config.prompts_file.resolved_version if config.prompts_file else "unknown"

    normalizer = DetectionNormalizer(
        min_confidence=config.postprocess.min_confidence,
        min_box_area_px=config.postprocess.min_box_area_px,
        normalize_boxes=config.postprocess.normalize_boxes,
    )
    adapter = create_adapter(config.model)
    reset_gpu_peak_memory()
    adapter.load()

    transport = create_transport(
        backend="network",
        role="consumer",
        endpoint=config.transport.endpoint,
    )
    try:
        run_consumer_loop(
            transport, adapter, normalizer, artifact_writer, run_context, tracker,
            config, prompt_texts, prompt_items, prompt_version,
            timings={}, progress=None, task=None, drain_errors=False,
        )
    finally:
        transport.shutdown()
        adapter.close()
        artifact_writer.close()

    run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
    run_context.finish()
    artifact_writer.write_summary(tracker)
    artifact_writer.write_provenance()
    artifact_writer.write_manifest()
    return run_context.run_id
```

> **Limitación conocida (edge container):** `run_node_a` instancia el adapter completo solo
> para leer `adapter.input_spec` (target_size + resize_mode de la normalización espacial). Con
> el detector mock y en el entorno de desarrollo (con torch) funciona. Pero el contenedor edge
> de la Fase 2c usa el extra `edge` (sin torch), donde `create_adapter` para gdino/yoloe
> fallaría al importar torch. El Nodo A solo necesita los parámetros de resize espacial, no el
> modelo. Refinamiento diferido: derivar el `input_spec` de Nodo A desde la config/catálogo sin
> instanciar un adapter de torch. No bloquea la validación loopback de la Fase 2.

- [ ] **Step 4: Verificar el test de integración**

Run: `source .venv/bin/activate && pytest tests/test_cli_two_node.py -v`
Expected: PASS.

- [ ] **Step 5: Agregar los comandos CLI**

En `src/eovrt_media/cli.py`, agregar tras el comando `run`:

```python
@app.command(name="run-producer")
def run_producer(
    config: Path = typer.Option(
        ..., "--config", "-c", help="Config YAML (topology=two_node).",
        exists=True, readable=True,
    ),
) -> None:
    """Nodo A: ingesta + normalización + servidor de red ZeroMQ."""
    from eovrt_media.config import load_run_config
    from eovrt_media.runtime.two_node import run_node_a

    console.print("\n[bold cyan]E-OVRT Media Plane — Nodo A (producer)[/bold cyan]")
    run_node_a(load_run_config(config), console=console)


@app.command(name="run-consumer")
def run_consumer(
    config: Path = typer.Option(
        ..., "--config", "-c", help="Config YAML (topology=two_node).",
        exists=True, readable=True,
    ),
) -> None:
    """Nodo B: cliente de red ZeroMQ + inferencia + artefactos."""
    from eovrt_media.config import load_run_config
    from eovrt_media.runtime.two_node import run_node_b

    console.print("\n[bold cyan]E-OVRT Media Plane — Nodo B (consumer)[/bold cyan]")
    run_id = run_node_b(load_run_config(config), console=console)
    console.print(f"[green]✓ Corrida completada:[/green] {run_id}")
```

- [ ] **Step 6: Verificar la suite completa**

Run: `source .venv/bin/activate && pytest -q && ruff check src tests`
Expected: PASS sin errores.

- [ ] **Step 7: Commit (cierra Fase 2)**

```bash
git add src/eovrt_media/cli.py src/eovrt_media/runtime/two_node.py tests/test_cli_two_node.py
git commit -m "feat: comandos run-producer/run-consumer para topología de dos nodos"
```

**✅ Checkpoint Fase 2:** EBE two-node funcional en loopback. Validar manualmente entre dos máquinas reales cuando la infra esté lista.

---

# FASE 2c — Containerización

> Ejecutar solo después de que la Fase 2 funcione en loopback. Ver la sección "Decisión: containerización con Docker" del spec.

## Task 12: Extras `edge` / `gpu` en pyproject

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `pip install -e ".[edge]"` instala solo lo que necesita el Nodo A (sin torch); `pip install -e ".[gpu]"` instala el stack de inferencia. La sección `dependencies` base queda con lo mínimo común.

- [ ] **Step 1: Reestructurar dependencias**

En `pyproject.toml`, dejar en `dependencies` solo lo común a ambos nodos:

```toml
dependencies = [
    "pillow",
    "opencv-python",
    "pydantic",
    "pyyaml",
    "typer",
    "rich",
    "pyzmq",
    "msgpack",
]
```

y mover el stack de GPU a un extra, agregando a `[project.optional-dependencies]`:

```toml
edge = []
gpu = [
    "torch",
    "torchvision",
    "transformers",
    "accelerate",
    "huggingface_hub",
    "ultralytics",
]
```

(El extra `edge` queda vacío: el Nodo A solo necesita la base. `dev` se mantiene como está.)

- [ ] **Step 2: Verificar que el entorno de desarrollo sigue completo**

Run: `source .venv/bin/activate && pip install -e ".[dev,gpu]" && pytest -q`
Expected: instala todo y la suite pasa (desarrollo usa ambos extras).

- [ ] **Step 3: Verificar que el extra edge no arrastra torch**

Run: `python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['dependencies'])"`
Expected: la lista base NO contiene `torch` ni `ultralytics`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: separar dependencias en extras edge (Nodo A) y gpu (Nodo B)"
```

---

## Task 13: Dockerfiles, compose y documentación de despliegue

**Files:**
- Create: `docker/Dockerfile.node-a`
- Create: `docker/Dockerfile.node-b`
- Create: `docker/docker-compose.yml`
- Create: `docs/deployment/two-node-docker.md`

**Interfaces:**
- Produces: imagen `node-a` (base + extra `edge`, sin GPU); imagen `node-b` (CUDA + extra `gpu`); `docker-compose.yml` con red puente para el endpoint ZeroMQ.

- [ ] **Step 1: Dockerfile del Nodo A (edge, sin GPU)**

Crear `docker/Dockerfile.node-a`:

```dockerfile
# Nodo A — ingesta + normalización + servidor ZeroMQ. Sin GPU.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[edge]"

ENTRYPOINT ["eovrt-media", "run-producer"]
CMD ["--config", "/configs/two_node.yaml"]
```

- [ ] **Step 2: Dockerfile del Nodo B (GPU)**

Crear `docker/Dockerfile.node-b`:

```dockerfile
# Nodo B — inferencia + postproceso + artefactos. Requiere GPU NVIDIA.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3-pip libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[gpu]"

ENTRYPOINT ["eovrt-media", "run-consumer"]
CMD ["--config", "/configs/two_node.yaml"]
```

- [ ] **Step 3: docker-compose con red puente**

Crear `docker/docker-compose.yml`:

```yaml
# Despliegue de dos nodos del plano de medios.
# Nodo A (edge) y Nodo B (GPU) comparten una red puente para el canal ZeroMQ.
services:
  node-a:
    build:
      context: ..
      dockerfile: docker/Dockerfile.node-a
    networks: [media-plane]
    volumes:
      - ../configs:/configs:ro
    # Nodo A expone el REP server; el endpoint del YAML debe bindear 0.0.0.0:5555
    expose: ["5555"]

  node-b:
    build:
      context: ..
      dockerfile: docker/Dockerfile.node-b
    networks: [media-plane]
    volumes:
      - ../configs:/configs:ro
      - ../models:/app/models:ro
      - ../runs:/app/runs
    depends_on: [node-a]
    # El endpoint del YAML debe apuntar a tcp://node-a:5555
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

networks:
  media-plane:
    driver: bridge
```

- [ ] **Step 4: Documentación de despliegue**

Crear `docs/deployment/two-node-docker.md`:

```markdown
# Despliegue de dos nodos con Docker

Empaqueta el plano de medios EBE distribuido en dos imágenes:

- **node-a** (edge, sin GPU): ingesta RTSP + rate control + normalización + servidor ZeroMQ.
- **node-b** (GPU): cliente ZeroMQ + inferencia OVD + postproceso + artefactos.

## Requisitos

- Docker y docker-compose.
- En el host del Nodo B: GPU NVIDIA + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **WSL2**: el soporte CUDA-en-Docker depende del driver NVIDIA del host Windows; verificar con `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.

## Configuración del endpoint

En el YAML de la corrida (`topology.mode: two_node`):

- Nodo A debe bindear todas las interfaces: `transport.endpoint: "tcp://0.0.0.0:5555"`.
- Nodo B debe conectar al servicio por nombre: `transport.endpoint: "tcp://node-a:5555"`.

Como ambos nodos comparten un mismo YAML montado en `/configs`, mantener dos archivos
(`two_node_a.yaml` / `two_node_b.yaml`) que solo difieran en el `endpoint`, o resolver el
nombre `node-a` en ambos (el bind a `0.0.0.0` acepta conexiones a `node-a`).

## Uso

```bash
cd docker
docker compose build
docker compose up
```

Los artefactos quedan en `runs/` del host (montado en Nodo B).

## Fricciones conocidas

- Imágenes con CUDA+PyTorch son grandes (varios GB); el primer build es lento.
- La cámara OAK-D Pro PoE (vía DepthAI) requerirá acceso a dispositivos/red adicional en el
  contenedor del Nodo A; pendiente junto con `OakDSource`.
```

- [ ] **Step 5: Verificar que el build del Nodo A funciona**

Run: `cd docker && docker build -f Dockerfile.node-a -t eovrt-node-a ..`
Expected: build exitoso (imagen edge sin torch). El build del Nodo B requiere base CUDA y es pesado; correrlo solo si hay GPU y tiempo.

- [ ] **Step 6: Commit (cierra Fase 2c)**

```bash
git add docker/ docs/deployment/two-node-docker.md
git commit -m "feat: dockerizar Nodo A/B y documentar despliegue de dos nodos"
```

**✅ Checkpoint Fase 2c:** servicio empaquetado. EBE completo y funcional en single-host y dos nodos, con despliegue reproducible.

---

## Notas de cierre

- Tras completar las tres fases, actualizar `docs/contexto/topologias-despliegue-dbe-ebe.md`
  (sección "Estado de implementación") y `e-ovrt_media-plane/CLAUDE.md` para reflejar que
  EBE single-host y two-node están implementados.
- El adaptador `OakDSource` y el heartbeat sobre socket PUSH/PULL dedicado quedan declarados
  y diferidos según el spec.
- Refinamiento diferido (ver Task 11): el Nodo A debe obtener su `input_spec` (resize espacial)
  sin instanciar un adapter de torch, para que el contenedor edge funcione con modelos reales.
