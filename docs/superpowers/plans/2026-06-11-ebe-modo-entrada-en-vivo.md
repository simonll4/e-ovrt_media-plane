# Plan de implementación — EBE como modo de entrada del plano de medios

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soportar el escenario EBE (cámara / stream / entorno en vivo) como un segundo modo de entrada sobre el mismo pipeline del plano de medios, sin bifurcar la lógica de procesamiento: DBE y EBE convergen en `VisualUnit` y comparten inferencia, postproceso, publicación de evidencia, métricas y trazabilidad.

**Architecture:** Se agrega un adaptador de entrada `LiveStreamSource` (hilo de captura + buffer acotado con descarte de frames viejos = backpressure) que implementa la interfaz `BaseSource` existente. `VisualUnit` gana un payload de frame en memoria (los frames vivos no pueden re-leerse de disco) y un timestamp de captura de reloj de pared. El núcleo (`run_pipeline`) queda intacto salvo: soporte de fuentes no acotadas, condición de corte por duración, y campos nuevos de evidencia/métricas (escenario, `captured_at_ms`, latencia captura→publicación, frames capturados/descartados, profundidad máxima de buffer y razón de cierre de la fuente).

**Tech Stack:** Python 3.11, OpenCV (`cv2.VideoCapture` para webcam/RTSP/archivo), threading stdlib, Pydantic v2, pytest.

---

## Mapeo de la cadena conceptual a módulos

| Etapa de la cadena | Módulo (existente o nuevo) |
| --- | --- |
| Fuente visual | Entrada del catálogo `configs/datasets/<nombre>.yaml` |
| Adaptador de entrada | `sources/` — `ImageFolderSource`, `VideoFileSource` (DBE) / **`LiveStreamSource` (EBE, nuevo)** |
| Decodificación / lectura de frames | `preprocessing/image_loader.py` (DBE) / **hilo de captura de `LiveStreamSource` (EBE)** |
| Normalización de unidad visual | `contracts/visual_unit.py` — `VisualUnit` (**punto de convergencia DBE/EBE**) |
| Control de ritmo y muestreo | `SamplingConfig` + `_get_frame_indices()` (DBE) / **pacing por `target_fps` + buffer con descarte (EBE)** |
| Preprocesamiento | `preprocessing/` |
| Inferencia OVD | `models/` (adaptadores mock / yoloe / grounding_dino) |
| Postproceso perceptivo | `postprocessing/DetectionNormalizer` |
| Tracking opcional | **Costura documentada, no implementada** (fuera de alcance según CLAUDE.md): el punto de inserción es inmediatamente después de `normalizer.normalize(...)` en `runtime/pipeline.py`, donde un futuro `Tracker.update(detections, unit)` enriquecería las detecciones con `track_id` antes de construir el `DetectionEvent`. |
| Publicación de evidencia perceptiva | `sinks/RunArtifactWriter` → `detections.jsonl` (`DetectionEvent`) |
| Inspección, métricas y trazabilidad | `runs/<run_id>/` + CLI `inspect-run` / `compare-runs` |

**Principio rector:** DBE y EBE no son dos pipelines; son dos adaptadores de entrada sobre el mismo plano de medios. A partir de `VisualUnit`, ningún módulo puede depender del origen.

## Alineación con el diseño arquitectónico (Etapa 3, §17.3)

Este plan implementa, dentro del alcance del repo (solo plano de medios), la topología EBE definida en §17.3.14 del diseño arquitectónico de la plataforma (`docs/contexto/E-OVRT-VDP_Etapa_3_Diseno_Arquitectonico_para_agente_codigo.md`). Correspondencias:

| Decisión del plan | Sustento en el diseño arquitectónico |
| --- | --- |
| Convergencia DBE/EBE en `VisualUnit`; mismos contratos, métricas y trazabilidad | §17.3.14.3 (equivalencia entre topologías: "frontera común de entrada visual normalizada") y Tabla 54. |
| `buffer_size: 1` + drop-oldest (procesar el último frame disponible) | §17.3.7.3 — política recomendada para pruebas orientadas a baja latencia. |
| `buffer_size > 1` + `target_fps` (cola acotada / FPS fijo) | §17.3.7.3 — política para pruebas orientadas a continuidad temporal. |
| Simulación sin hardware: archivo de video con `realtime: true` | Tabla 55 — "archivo simulado como stream" es un mecanismo de transporte previsto. |
| Contadores de captura/descarte, profundidad de cola observada y razón de cierre de la fuente | §17.3.7.2 (visibilidad de la variabilidad temporal) y Tablas 53/55 (señales de colas, buffers, backpressure y degradación). |
| Fuente inaccesible registrada como `ErrorEvent` | RNF de robustez experimental (Tabla 42) y Tabla 55 (condición de degradación). |
| `captured_at_ms` = instante de recepción/decodificación en el nodo de procesamiento | Contrato FrameMetadata (Tabla 50): "instante de captura o recepción cuando aplique". No hay reloj de cámara; en webcam local captura ≈ recepción. |
| Webcam o RTSP en red local sin nodo intermedio | Modo EN-0 "captura sin análisis local" (§17.3.15.2, Tabla 56). EN-1/EN-2 (preprocesamiento o preselección en borde) quedan fuera de alcance (DA-11, condicionada). |
| EBE recién ahora, con DBE ya estabilizado | DA-10 ("priorizar DBE antes de EBE"): el núcleo DBE ya tiene corridas reportables. |
| La salida sigue siendo evidencia perceptiva normalizada; sin patrones ni alertas | DA-01/DA-02 y §17.3.7 (límite estricto del plano de medios). El plano de control es otro componente. |

Requisitos del diseño que el repo ya satisface sin cambios: versión de esquema en todos los eventos (`media.detection.v1`, `media.metric.v1`, `media.error.v1`, `media.summary.v1`) y configuración efectiva persistida por corrida (`effective_config.yaml`), que materializa la declaración de política de muestreo/descarte exigida por §17.3.6.2 (Tabla 44).

**Equivalencia de nomenclatura contractual (Tabla 50 del diseño → repo).** El diseño declara sus nombres como "denominaciones contractuales preliminares" que "no imponen una tecnología, un formato de serialización ni una estructura de código específica" (§17.3.11). Cuatro contratos coinciden textualmente; el resto mapea 1:1. Este plan no introduce nombres nuevos por fuera de este mapeo:

| Contrato del diseño (Tabla 50) | Materialización en el repo |
| --- | --- |
| RunConfig | `RunConfig` (`config/schemas.py`) + `effective_config.yaml` persistido por corrida |
| SourceDefinition | `SourceSection` + entrada del catálogo `configs/datasets/<nombre>.yaml` |
| ModelProfile | `ModelSection` + entrada del catálogo `configs/models/<familia>/<variante>.yaml` (checkpoint, adapter, device, umbrales base, source, license) |
| PromptDefinition | `PromptSet` / `PromptItem` + catálogo `configs/prompts/<nombre>.yaml` |
| FrameMetadata | `VisualUnit` (traducción literal de "unidad visual"; transporta los metadatos del contrato y, en EBE, el payload de frame en memoria) |
| DetectionEvent | `DetectionEvent` → `detections.jsonl` (idéntico) |
| MetricSample | `MetricSample` → `metrics.jsonl` (idéntico) |
| ErrorEvent | `ErrorEvent` → `errors.jsonl` (idéntico) |
| PatternStateChanged / AlertEvent | Plano de control — fuera de este repo por diseño (DA-01) |
| Registro de resultados por corrida (§17.3.13.4) | `RunSummary` → `summary.json` |

**Simplificación declarada (descartes EBE):** FrameMetadata prevé "motivo de descarte si corresponde" por unidad. En EBE los descartes se registran como contadores agregados (`frames_dropped`, `buffer_max_depth`) bajo una única causa estructural: backpressure drop-oldest, declarada en `backpressure_policy`. No se emite un evento por frame descartado — a FPS de cámara serían miles de registros sin valor interpretativo adicional. Si una corrida futura introduce descartes con causa múltiple (p. ej. preselección EN-2), ahí se justifica el evento por descarte con motivo.

**Decisiones de diseño bloqueadas:**

1. `VisualUnit.frame` (ndarray BGR opcional, excluido de serialización) es el mecanismo de payload en memoria. `load_image()` lo usa si está presente; si no, re-lee de disco como hoy. Así el loop del pipeline no cambia.
2. La política de backpressure es **drop-oldest** con buffer acotado (`buffer_size`, default 1): el pipeline siempre procesa el frame más reciente disponible y cada descarte se contabiliza.
3. La simulación de EBE sin hardware es `LiveStreamSource` sobre un archivo de video con `realtime: true` (reproduce a FPS nativo). Esto hace el escenario testeable en CI y reproducible.
4. Identidad temporal: `captured_at_ms` = epoch ms de reloj de pared al momento en que el hilo de captura recibe/decodifica el frame en el nodo de procesamiento (semántica de *recepción* según FrameMetadata; en webcam local captura ≈ recepción, en RTSP no existe reloj de cámara). La latencia end-to-end por unidad es `capture_to_done_ms = now_ms - captured_at_ms`.
5. Las fuentes declaran `is_bounded` (atributo de clase). El pipeline usa `total=None` en la barra de progreso para fuentes no acotadas.
6. Señales de operación continua (Tablas 53/55 del diseño): el buffer registra `max_depth` (profundidad de cola observada), la fuente expone `ended_reason` (`max_units` | `max_duration_s` | `end_of_stream` | `source_unreachable`) y el resumen declara `backpressure_policy: drop_oldest`. Una fuente inaccesible se persiste como `ErrorEvent` (stage `source`), no solo como log.

**Archivos a crear/modificar (resumen):**

- Create: `src/eovrt_media/sources/live_capture_buffer.py`, `src/eovrt_media/sources/live_stream_source.py`
- Create: `tests/test_live_capture_buffer.py`, `tests/test_live_stream_source.py`, `tests/test_pipeline_ebe.py`
- Create: `configs/datasets/webcam0.yaml`, `configs/datasets/video_sim_live.yaml`, `configs/runs/ebe_mock_sim.yaml`, `configs/runs/ebe_yoloe_webcam.yaml`
- Create: `docs/decisions/ADR-0005-ebe-modo-entrada.md`
- Modify: `src/eovrt_media/contracts/visual_unit.py`, `contracts/events.py`, `contracts/metrics.py`, `preprocessing/image_loader.py`, `config/schemas.py`, `sources/base.py`, `sources/__init__.py`, `runtime/pipeline.py`, `runtime/run_context.py`, `sinks/run_artifact_writer.py`, `visualize.py`, `docs/architecture.md`, `docs/usage.md`, `configs/README.md`, `CLAUDE.md`
- Test (existentes que se tocan): `tests/test_config.py` (solo si rompe), ninguno más — los contratos nuevos son aditivos.

---

### Task 1: VisualUnit con payload en memoria y timestamp de captura

**Files:**
- Modify: `src/eovrt_media/contracts/visual_unit.py`
- Modify: `src/eovrt_media/preprocessing/image_loader.py:22-26`
- Test: `tests/test_visual_unit_live.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
"""Tests del payload en memoria de VisualUnit y su carga."""

import numpy as np

from eovrt_media.contracts import VisualUnit
from eovrt_media.preprocessing import load_image


def _live_unit(frame=None):
    return VisualUnit(
        unit_id="u1",
        source_type="live_frame",
        source_path="rtsp://camara-inexistente/stream",
        width=4,
        height=4,
        captured_at_ms=1234.5,
        frame=frame,
    )


class TestVisualUnitLive:
    def test_accepts_in_memory_frame(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        unit = _live_unit(frame)
        assert unit.frame is frame
        assert unit.captured_at_ms == 1234.5

    def test_frame_excluded_from_serialization(self):
        unit = _live_unit(np.zeros((4, 4, 3), dtype=np.uint8))
        dumped = unit.model_dump()
        assert "frame" not in dumped
        assert dumped["captured_at_ms"] == 1234.5

    def test_load_image_uses_in_memory_frame_without_touching_disk(self):
        # BGR puro azul -> RGB debe quedar (0, 0, 255) en el canal correcto
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        frame[:, :, 0] = 255  # canal B en BGR
        unit = _live_unit(frame)
        img = load_image(unit)  # el path no existe: si toca disco, falla
        assert img.size == (4, 4)
        assert img.getpixel((0, 0)) == (0, 0, 255)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `pytest tests/test_visual_unit_live.py -v`
Expected: FAIL — `ValidationError` (campos `captured_at_ms` / `frame` no existen en `VisualUnit`).

- [ ] **Step 3: Implementar en VisualUnit**

En `src/eovrt_media/contracts/visual_unit.py`, reemplazar el inicio de la clase:

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator


class VisualUnit(BaseModel):
    """Representa una imagen o frame procesable.

    Para fuentes en vivo (EBE) el frame viaja en memoria en `frame` (ndarray
    BGR) porque no puede re-leerse de disco; `captured_at_ms` registra el
    instante de captura en epoch ms (reloj de pared) para trazabilidad y
    latencia end-to-end.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str | None = None
    unit_id: str
    source_id: str | None = None
    source_type: str  # "image" | "video_frame" | "live_frame"
    frame_index: int | None = None
    timestamp_ms: float | None = None
    captured_at_ms: float | None = None
    width: int
    height: int
    path: str | None = None
    source_path: str | None = None
    frame: Any | None = Field(default=None, exclude=True, repr=False)
```

(el validador `sync_paths_and_ids` existente queda igual)

- [ ] **Step 4: Implementar en load_image**

En `src/eovrt_media/preprocessing/image_loader.py`, insertar al comienzo del cuerpo de `load_image` (antes de `path_str = ...`):

```python
    # Frame en memoria (EBE): no hay re-lectura de disco posible
    if unit.frame is not None:
        frame_rgb = cv2.cvtColor(unit.frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `pytest tests/test_visual_unit_live.py -v && pytest -q`
Expected: PASS los 3 nuevos; la suite completa sigue en verde (cambios aditivos).

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/contracts/visual_unit.py src/eovrt_media/preprocessing/image_loader.py tests/test_visual_unit_live.py
git commit -m "feat: VisualUnit con frame en memoria y captured_at_ms para fuentes en vivo"
```

---

### Task 2: Configuración — escenario EBE, fuente live_stream y corte por duración

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (RunSection, SourceSection, SamplingConfig)
- Test: `tests/test_config_live.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
"""Tests de configuración para el escenario EBE."""

import pytest
from pydantic import ValidationError

from eovrt_media.config.schemas import RunConfig, RunSection, SamplingConfig, SourceSection


def _min_config(scenario: str, source_type: str) -> RunConfig:
    return RunConfig(
        run={"scenario": scenario},
        source={"type": source_type, "path": "x"},
        model={"name": "mock"},
        prompts={"ref": "cr01_cr02_v1"},
    )


class TestEbeConfig:
    def test_scenario_accepts_dbe_and_ebe(self):
        assert RunSection(scenario="DBE").scenario == "DBE"
        assert RunSection(scenario="EBE").scenario == "EBE"
        assert RunSection(scenario="ebe").scenario == "EBE"  # normaliza a mayúsculas

    def test_scenario_rejects_unknown(self):
        with pytest.raises(ValidationError, match="DBE.*EBE"):
            RunSection(scenario="OTRO")

    def test_source_live_stream_fields_with_defaults(self):
        src = SourceSection(type="live_stream", path="rtsp://host/stream")
        assert src.buffer_size == 1
        assert src.realtime is False
        assert src.reconnect_attempts == 3
        assert src.read_timeout_s == 5.0

    def test_sampling_max_duration(self):
        s = SamplingConfig(max_duration_s=30.5)
        assert s.max_duration_s == 30.5
        assert SamplingConfig().max_duration_s is None

    def test_scenario_and_source_type_must_be_consistent(self):
        # §17.3.6.6: la corrida no debe iniciar con escenario y fuente incoherentes
        with pytest.raises(ValidationError, match="EBE"):
            _min_config(scenario="DBE", source_type="live_stream")
        with pytest.raises(ValidationError, match="EBE"):
            _min_config(scenario="EBE", source_type="image_folder")
        assert _min_config(scenario="EBE", source_type="live_stream").run.scenario == "EBE"
        assert _min_config(scenario="DBE", source_type="video_file").run.scenario == "DBE"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_config_live.py -v`
Expected: FAIL — `scenario="ebe"` no normaliza, `buffer_size` no existe, `max_duration_s` no existe, la validación cruzada escenario↔fuente no existe.

- [ ] **Step 3: Implementar en schemas.py**

`RunSection` — reemplazar el campo `scenario` y agregar validador:

```python
class RunSection(BaseModel):
    """Sección 'run' de la configuración."""

    id: str | None = None
    scenario: str = "DBE"  # DBE (dataset offline) | EBE (fuente en vivo)
    name: str | None = None
    description: str | None = None
    seed: int = 42

    @model_validator(mode="after")
    def validate_scenario(self) -> RunSection:
        normalized = self.scenario.upper().strip()
        if normalized not in ("DBE", "EBE"):
            raise ValueError(f"scenario debe ser DBE o EBE, no '{self.scenario}'")
        self.scenario = normalized
        return self
```

`SourceSection` — agregar tras `extensions`:

```python
    # Campos para fuentes en vivo (type: live_stream).
    # path es la URI: índice de webcam ("0"), rtsp://..., http://... o un
    # archivo de video con realtime=true para simular una cámara.
    buffer_size: int = 1
    realtime: bool = False
    reconnect_attempts: int = 3
    read_timeout_s: float = 5.0
```

`SamplingConfig` — agregar tras `max_units`:

```python
    max_duration_s: float | None = None  # corte por tiempo de pared (clave en EBE)
```

`RunConfig` — agregar validador de coherencia escenario↔fuente (§17.3.6.6, validaciones previas al inicio de la corrida; va después de los validadores existentes):

```python
    @model_validator(mode="after")
    def validate_scenario_source_consistency(self) -> RunConfig:
        is_live = self.source.type == "live_stream"
        is_ebe = self.run.scenario == "EBE"
        if is_ebe != is_live:
            raise ValueError(
                "Escenario y fuente incoherentes: EBE requiere source.type "
                f"'live_stream' y DBE una fuente offline "
                f"(scenario={self.run.scenario}, source.type={self.source.type})"
            )
        return self
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_config_live.py tests/test_config.py tests/test_config_refs.py -v`
Expected: PASS todo (las configs existentes usan `scenario: DBE`, válido).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/config/schemas.py tests/test_config_live.py
git commit -m "feat: config de escenario EBE, fuente live_stream y max_duration_s"
```

---

### Task 3: LiveCaptureBuffer — buffer acotado con descarte contabilizado

**Files:**
- Create: `src/eovrt_media/sources/live_capture_buffer.py`
- Test: `tests/test_live_capture_buffer.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
"""Tests del buffer de captura en vivo."""

import threading

import pytest

from eovrt_media.sources.live_capture_buffer import LiveCaptureBuffer


class TestLiveCaptureBuffer:
    def test_push_pop_fifo(self):
        buf = LiveCaptureBuffer(maxsize=3)
        buf.push("a"); buf.push("b")
        assert buf.pop(timeout=0.1) == "a"
        assert buf.pop(timeout=0.1) == "b"

    def test_drop_oldest_when_full_and_counts(self):
        buf = LiveCaptureBuffer(maxsize=2)
        buf.push("a"); buf.push("b"); buf.push("c")  # "a" se descarta
        assert buf.pop(timeout=0.1) == "b"
        assert buf.pop(timeout=0.1) == "c"
        assert buf.stats.frames_captured == 3
        assert buf.stats.frames_dropped == 1
        assert buf.stats.max_depth == 2  # profundidad de cola observada (Tabla 53)

    def test_pop_timeout_returns_none(self):
        buf = LiveCaptureBuffer(maxsize=1)
        assert buf.pop(timeout=0.05) is None

    def test_pop_unblocks_on_push_from_other_thread(self):
        buf = LiveCaptureBuffer(maxsize=1)
        timer = threading.Timer(0.05, lambda: buf.push("x"))
        timer.start()
        assert buf.pop(timeout=1.0) == "x"
        timer.join()

    def test_maxsize_must_be_positive(self):
        with pytest.raises(ValueError, match="maxsize"):
            LiveCaptureBuffer(maxsize=0)
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_live_capture_buffer.py -v`
Expected: FAIL — `ModuleNotFoundError: live_capture_buffer`.

- [ ] **Step 3: Implementar el buffer**

`src/eovrt_media/sources/live_capture_buffer.py` completo:

```python
"""Buffer acotado para captura en vivo con política de descarte de frames viejos."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class CaptureStats:
    """Contadores de captura para backpressure y trazabilidad."""

    frames_captured: int = 0
    frames_dropped: int = 0
    max_depth: int = 0


class LiveCaptureBuffer:
    """Buffer FIFO acotado y thread-safe entre el hilo de captura y el pipeline.

    Si el buffer está lleno al hacer push, se descarta el elemento más viejo
    (el consumidor siempre ve lo más reciente posible) y el descarte queda
    contabilizado en stats. pop() bloquea hasta timeout si está vacío.
    """

    def __init__(self, maxsize: int = 1) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize debe ser >= 1, no {maxsize}")
        self._maxsize = maxsize
        self._items: deque[Any] = deque()
        self._not_empty = threading.Condition(threading.Lock())
        self.stats = CaptureStats()

    def push(self, item: Any) -> None:
        with self._not_empty:
            if len(self._items) >= self._maxsize:
                self._items.popleft()
                self.stats.frames_dropped += 1
            self._items.append(item)
            self.stats.frames_captured += 1
            if len(self._items) > self.stats.max_depth:
                self.stats.max_depth = len(self._items)
            self._not_empty.notify()

    def pop(self, timeout: float | None = None) -> Any | None:
        with self._not_empty:
            if not self._items:
                self._not_empty.wait(timeout)
            if not self._items:
                return None
            return self._items.popleft()
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_live_capture_buffer.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/sources/live_capture_buffer.py tests/test_live_capture_buffer.py
git commit -m "feat: buffer de captura acotado con descarte contabilizado (backpressure EBE)"
```

---

### Task 4: LiveStreamSource — adaptador de entrada EBE

**Files:**
- Create: `src/eovrt_media/sources/live_stream_source.py`
- Modify: `src/eovrt_media/sources/base.py` (atributo `is_bounded`)
- Modify: `src/eovrt_media/sources/__init__.py`
- Test: `tests/test_live_stream_source.py`

- [ ] **Step 1: Escribir los tests que fallan (con captura falsa, sin cámara)**

```python
"""Tests de LiveStreamSource con un capture falso inyectado (sin cámara real)."""

import numpy as np

from eovrt_media.sources import LiveStreamSource


class FakeCapture:
    """Imita cv2.VideoCapture: produce N frames y después devuelve (False, None)."""

    def __init__(self, frames: int, fps: float = 1000.0, fail_open: bool = False):
        self._remaining = frames
        self._fps = fps
        self._fail_open = fail_open

    def isOpened(self):
        return not self._fail_open

    def get(self, prop):
        return self._fps

    def read(self):
        if self._remaining <= 0:
            return False, None
        self._remaining -= 1
        return True, np.zeros((8, 12, 3), dtype=np.uint8)

    def release(self):
        pass


def _source(frames=50, **kwargs):
    defaults = dict(
        uri="fake://stream",
        capture_factory=lambda uri: FakeCapture(frames),
        read_timeout_s=0.5,
    )
    defaults.update(kwargs)
    return LiveStreamSource(**defaults)


class TestLiveStreamSource:
    def test_yields_units_with_frame_payload_and_capture_metadata(self):
        units = list(_source(frames=50, max_units=5))
        assert len(units) == 5
        for unit in units:
            assert unit.source_type == "live_frame"
            assert unit.frame is not None
            assert unit.frame.shape == (8, 12, 3)
            assert unit.width == 12 and unit.height == 8
            assert unit.captured_at_ms is not None
            assert unit.source_path == "fake://stream"

    def test_stops_when_source_ends(self):
        src = _source(frames=3, max_units=100, reconnect_attempts=0)
        units = list(src)
        assert 0 < len(units) <= 3
        assert src.ended_reason == "end_of_stream"

    def test_stops_by_max_duration(self):
        src = _source(frames=10_000_000, max_duration_s=0.3)
        units = list(src)
        assert len(units) >= 1  # cortó por tiempo, no por agotar la fuente
        assert src.ended_reason == "max_duration_s"

    def test_is_unbounded_and_len_reports_max_units(self):
        assert LiveStreamSource.is_bounded is False
        assert len(_source(max_units=7)) == 7
        assert len(_source()) == 0

    def test_capture_stats_exposed(self):
        src = _source(frames=50, max_units=5)
        list(src)
        assert src.stats.frames_captured >= 5

    def test_failed_open_stops_after_reconnect_attempts(self):
        src = LiveStreamSource(
            uri="fake://dead",
            capture_factory=lambda uri: FakeCapture(0, fail_open=True),
            reconnect_attempts=1,
            read_timeout_s=0.2,
        )
        assert list(src) == []
        assert src.ended_reason == "source_unreachable"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_live_stream_source.py -v`
Expected: FAIL — `ImportError: LiveStreamSource`.

- [ ] **Step 3: Marcar acotación en BaseSource**

En `src/eovrt_media/sources/base.py`, dentro de `BaseSource`, antes de `__iter__`:

```python
    # Las fuentes offline conocen su tamaño; las fuentes en vivo no.
    is_bounded: bool = True
```

- [ ] **Step 4: Implementar LiveStreamSource**

`src/eovrt_media/sources/live_stream_source.py` completo:

```python
"""Adaptador de entrada EBE: cámara, stream o archivo simulado en tiempo real."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterator

import cv2

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource
from eovrt_media.sources.live_capture_buffer import CaptureStats, LiveCaptureBuffer

logger = logging.getLogger(__name__)

CaptureFactory = Callable[[str], Any]


def _default_capture_factory(uri: str) -> Any:
    # Un índice numérico es un dispositivo local (webcam); el resto, una URI.
    return cv2.VideoCapture(int(uri)) if uri.isdigit() else cv2.VideoCapture(uri)


class LiveStreamSource(BaseSource):
    """Fuente en vivo para el escenario EBE.

    Un hilo de captura lee frames de la fuente hacia un LiveCaptureBuffer
    acotado (los frames viejos se descartan y contabilizan: backpressure).
    El iterador consume al ritmo de target_fps y corta por max_units,
    max_duration_s o fin/caída de la fuente. Con realtime=True un archivo de
    video se reproduce a su FPS nativo, simulando una cámara sin hardware.
    """

    is_bounded = False

    def __init__(
        self,
        uri: str,
        target_fps: float | None = None,
        max_units: int | None = None,
        max_duration_s: float | None = None,
        buffer_size: int = 1,
        realtime: bool = False,
        reconnect_attempts: int = 3,
        read_timeout_s: float = 5.0,
        capture_factory: CaptureFactory = _default_capture_factory,
    ) -> None:
        self.uri = str(uri)
        self.target_fps = target_fps
        self.max_units = max_units
        self.max_duration_s = max_duration_s
        self.realtime = realtime
        self.reconnect_attempts = reconnect_attempts
        self.read_timeout_s = read_timeout_s
        self.capture_factory = capture_factory
        self.buffer = LiveCaptureBuffer(maxsize=buffer_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Razón de cierre de la iteración (condición de degradación, Tabla 55):
        # "max_units" | "max_duration_s" | "end_of_stream" | "source_unreachable"
        self.ended_reason: str | None = None
        self._capture_reason: str | None = None

    @property
    def stats(self) -> CaptureStats:
        return self.buffer.stats

    def _capture_loop(self) -> None:
        failures = 0
        cap = self.capture_factory(self.uri)
        source_fps = 0.0
        seq = 0
        try:
            while not self._stop.is_set():
                if not cap.isOpened():
                    failures += 1
                    if failures > self.reconnect_attempts:
                        self._capture_reason = "source_unreachable"
                        logger.error(f"Fuente en vivo inaccesible tras {failures} intentos: {self.uri}")
                        return
                    time.sleep(0.2)
                    cap.release()
                    cap = self.capture_factory(self.uri)
                    continue

                if not source_fps:
                    source_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0

                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    if failures > self.reconnect_attempts:
                        self._capture_reason = "end_of_stream"
                        logger.info(f"Fin o caída de la fuente en vivo: {self.uri}")
                        return
                    continue

                failures = 0
                self.buffer.push((seq, time.time() * 1000.0, frame))
                seq += 1

                if self.realtime and source_fps > 0:
                    time.sleep(1.0 / source_fps)
        finally:
            cap.release()

    def __iter__(self) -> Iterator[VisualUnit]:
        self._stop.clear()
        self.ended_reason = None
        self._capture_reason = None
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        started = time.monotonic()
        produced = 0
        interval = (1.0 / self.target_fps) if self.target_fps else 0.0
        next_due = time.monotonic()
        try:
            while True:
                if self.max_units is not None and produced >= self.max_units:
                    self.ended_reason = "max_units"
                    return
                if self.max_duration_s is not None and time.monotonic() - started >= self.max_duration_s:
                    self.ended_reason = "max_duration_s"
                    return

                # Pacing: dormir hasta el próximo slot; el buffer descarta lo viejo.
                now = time.monotonic()
                if interval and now < next_due:
                    time.sleep(next_due - now)
                item = self.buffer.pop(timeout=self.read_timeout_s)
                if item is None:
                    if self._thread.is_alive():
                        continue  # captura viva pero sin frames aún
                    self.ended_reason = self._capture_reason or "end_of_stream"
                    return  # captura terminada y buffer vacío
                next_due = time.monotonic() + interval

                seq, captured_at_ms, frame = item
                height, width = frame.shape[:2]
                produced += 1
                yield VisualUnit(
                    unit_id=f"live_{produced - 1:06d}",
                    source_path=self.uri,
                    source_type="live_frame",
                    frame_index=seq,
                    timestamp_ms=round(captured_at_ms, 2),
                    captured_at_ms=round(captured_at_ms, 2),
                    width=width,
                    height=height,
                    frame=frame,
                )
        finally:
            self.close()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def __len__(self) -> int:
        # Fuente no acotada: solo se conoce el techo si max_units está definido.
        return self.max_units or 0
```

- [ ] **Step 5: Exportar en sources/__init__.py**

```python
"""Módulo de fuentes de datos visuales del plano de medios E-OVRT."""

from eovrt_media.sources.base import BaseSource
from eovrt_media.sources.image_folder_source import ImageFolderSource
from eovrt_media.sources.live_stream_source import LiveStreamSource
from eovrt_media.sources.video_file_source import VideoFileSource

__all__ = [
    "BaseSource",
    "ImageFolderSource",
    "LiveStreamSource",
    "VideoFileSource",
]
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `pytest tests/test_live_stream_source.py -v && pytest -q`
Expected: PASS los 6 nuevos y la suite completa.

- [ ] **Step 7: Commit**

```bash
git add src/eovrt_media/sources/ tests/test_live_stream_source.py
git commit -m "feat: LiveStreamSource — adaptador de entrada EBE con captura en hilo y backpressure"
```

---

### Task 5: Contratos de evidencia y métricas con campos EBE

**Files:**
- Modify: `src/eovrt_media/contracts/events.py` (DetectionEventSource, RunSummary)
- Modify: `src/eovrt_media/contracts/metrics.py` (MetricSample)
- Modify: `src/eovrt_media/runtime/run_context.py`
- Test: `tests/test_contracts_ebe.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
"""Tests de los campos EBE en los contratos de evidencia y métricas."""

from eovrt_media.contracts.events import DetectionEventSource, RunSummary
from eovrt_media.contracts.metrics import MetricSample


class TestEbeContracts:
    def test_detection_event_source_carries_capture_metadata(self):
        src = DetectionEventSource(
            source_id="rtsp://cam/stream",
            source_type="live_frame",
            width=640,
            height=480,
            captured_at_ms=111.0,
            scenario="EBE",
        )
        assert src.captured_at_ms == 111.0
        assert src.scenario == "EBE"

    def test_metric_sample_capture_to_done(self):
        m = MetricSample(run_id="r", unit_id="u", capture_to_done_ms=42.5)
        assert m.capture_to_done_ms == 42.5
        assert MetricSample(run_id="r", unit_id="u").capture_to_done_ms is None

    def test_run_summary_capture_counters(self):
        s = RunSummary(
            run_id="r", scenario="EBE", source_count=0, units_processed=10,
            units_failed=0, started_at="t0", finished_at="t1",
            frames_captured=100, frames_dropped=90, drop_rate=0.9,
            buffer_max_depth=2, backpressure_policy="drop_oldest",
            source_ended_reason="max_duration_s",
        )
        assert s.frames_captured == 100
        assert s.frames_dropped == 90
        assert s.drop_rate == 0.9
        assert s.buffer_max_depth == 2
        assert s.backpressure_policy == "drop_oldest"
        assert s.source_ended_reason == "max_duration_s"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `pytest tests/test_contracts_ebe.py -v`
Expected: FAIL — campos desconocidos (Pydantic los ignora pero el assert de igualdad falla con AttributeError/None).

- [ ] **Step 3: Implementar los campos**

`contracts/events.py` — `DetectionEventSource`, agregar tras `timestamp_ms`:

```python
    captured_at_ms: float | None = None  # epoch ms de captura (EBE)
    scenario: str | None = None          # DBE | EBE
```

`contracts/events.py` — `DetectionEventModel`, agregar tras `device` (la
evidencia debe incluir los umbrales aplicados, no solo referenciarlos vía
`run_id` → `effective_config.yaml`):

```python
    thresholds: dict[str, float] = Field(default_factory=dict)
```

(requiere que `Field` ya esté importado en el módulo — lo está)

Test adicional para `tests/test_contracts_ebe.py` (agregar a la clase):

```python
    def test_detection_event_model_carries_thresholds(self):
        from eovrt_media.contracts.events import DetectionEventModel

        m = DetectionEventModel(
            name="yoloe", device="cuda",
            thresholds={"confidence_threshold": 0.25, "iou_threshold": 0.5},
        )
        assert m.thresholds["confidence_threshold"] == 0.25
        assert DetectionEventModel(name="mock", device="cpu").thresholds == {}
```

`contracts/events.py` — `RunSummary`, agregar tras `gpu_memory_peak_mb`:

```python
    # Operación continua (EBE): contadores de captura, descarte y señales de
    # colas/backpressure/degradación (Tablas 53 y 55 del diseño arquitectónico)
    frames_captured: int | None = None
    frames_dropped: int | None = None
    drop_rate: float | None = None
    buffer_max_depth: int | None = None
    backpressure_policy: str | None = None   # "drop_oldest" en fuentes en vivo
    source_ended_reason: str | None = None   # max_units | max_duration_s | end_of_stream | source_unreachable
```

`contracts/metrics.py` — `MetricSample`, agregar tras `dropped_units`:

```python
    capture_to_done_ms: float | None = None  # latencia captura → publicación (EBE)
```

`runtime/run_context.py` — en `__init__`, tras `self.gpu_memory_peak_mb = 0.0`:

```python
        self.frames_captured = 0
        self.frames_dropped = 0
        self.buffer_max_depth = 0
        self.source_ended_reason: str | None = None
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_contracts_ebe.py tests/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/contracts/ src/eovrt_media/runtime/run_context.py tests/test_contracts_ebe.py
git commit -m "feat: campos EBE en evidencia (captured_at_ms, scenario) y métricas (drops, e2e)"
```

---

### Task 6: Previews desde imagen en memoria

**Files:**
- Modify: `src/eovrt_media/visualize.py:33-37` (firma de `draw_detections`)
- Modify: `src/eovrt_media/runtime/pipeline.py:283` (pasar `pil_image` en lugar del path)
- Test: `tests/test_visualize_in_memory.py`

- [ ] **Step 1: Escribir el test que falla**

```python
"""Test de draw_detections con imagen PIL en memoria (frames EBE sin archivo)."""

from PIL import Image

from eovrt_media.contracts.detection import Detection
from eovrt_media.visualize import draw_detections


def test_draw_detections_accepts_pil_image(tmp_path):
    img = Image.new("RGB", (64, 64), color=(10, 10, 10))
    det = Detection(
        label="person",
        prompt_id="person",
        confidence=0.9,
        bbox_xyxy=[5.0, 5.0, 30.0, 30.0],
        bbox_norm_xyxy=[5 / 64, 5 / 64, 30 / 64, 30 / 64],
    )
    out = tmp_path / "preview.jpg"
    draw_detections(img, [det], out)
    assert out.exists() and out.stat().st_size > 0
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `pytest tests/test_visualize_in_memory.py -v`
Expected: FAIL — `draw_detections` intenta abrir la imagen como path.

- [ ] **Step 3: Implementar**

En `src/eovrt_media/visualize.py`, cambiar la firma y la apertura:

```python
def draw_detections(
    image: Image.Image | str | Path,
    detections: list[Detection],
    output_path: str | Path,
) -> None:
    """Dibuja bounding boxes sobre una imagen (path o PIL en memoria) y la guarda."""
    if isinstance(image, Image.Image):
        img = image.copy()
    else:
        img = Image.open(image).convert("RGB")
```

(el resto de la función usa `img` como hasta ahora; ajustar el nombre de la
variable local si difiere)

En `runtime/pipeline.py`, en el bloque de previews, reemplazar:

```python
                        draw_detections(unit.source_path, detections, preview_path)
```

por:

```python
                        draw_detections(pil_image, detections, preview_path)
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_visualize_in_memory.py -v && pytest -q`
Expected: PASS; la suite completa en verde (los previews DBE ahora usan la imagen ya cargada — mismo resultado, una lectura de disco menos).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/visualize.py src/eovrt_media/runtime/pipeline.py tests/test_visualize_in_memory.py
git commit -m "feat: previews desde imagen en memoria (necesario para frames EBE)"
```

---

### Task 7: Integración en el pipeline — fuente live_stream, progreso no acotado y métricas de operación

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py` (create_source, progreso, evidencia, métricas, resumen)
- Modify: `src/eovrt_media/sinks/run_artifact_writer.py:122-152` (write_summary)
- Test: se valida con el test E2E de la Task 8 (los cambios son de cableado)

- [ ] **Step 1: Registrar la fuente en create_source**

En `runtime/pipeline.py`, agregar import y rama:

```python
from eovrt_media.sources import ImageFolderSource, LiveStreamSource, VideoFileSource, BaseSource
```

En `create_source`, antes del `else`:

```python
    elif source_type == "live_stream":
        return LiveStreamSource(
            uri=config.source.path,
            target_fps=config.sampling.target_fps,
            max_units=config.sampling.max_units,
            max_duration_s=config.sampling.max_duration_s,
            buffer_size=config.source.buffer_size,
            realtime=config.source.realtime,
            reconnect_attempts=config.source.reconnect_attempts,
            read_timeout_s=config.source.read_timeout_s,
        )
```

y actualizar el mensaje del `else` final a `"Opciones: image_folder, video_file, live_stream"`.

- [ ] **Step 2: Progreso para fuentes no acotadas**

Reemplazar (líneas ~79-80):

```python
    source = create_source(config)
    source_count = len(source)
    console.print(f"[dim]  Fuente: {config.source.path} ({source_count} unidades)[/dim]")
```

por:

```python
    source = create_source(config)
    is_bounded = getattr(source, "is_bounded", True)
    source_count = len(source) if is_bounded else (config.sampling.max_units or None)
    count_label = f"{source_count} unidades" if source_count else "fuente en vivo, sin tamaño conocido"
    console.print(f"[dim]  Fuente: {config.source.path} ({count_label})[/dim]")
```

y en `progress.add_task(...)`, `total=source_count` ya acepta `None` (barra indeterminada). En el reporte final, reemplazar `f"  Procesadas: {run_context.units_processed}/{source_count}"` por:

```python
    processed_total = f"/{source_count}" if source_count else ""
    console.print(f"  Procesadas: {run_context.units_processed}{processed_total}")
```

- [ ] **Step 3: Evidencia y métrica por unidad con datos de captura**

Agregar `import time` arriba del archivo. En el bloque de ESCRITURA, antes de construir el `DetectionEvent`:

```python
                    capture_to_done_ms = None
                    if unit.captured_at_ms is not None:
                        capture_to_done_ms = round(time.time() * 1000.0 - unit.captured_at_ms, 2)
```

En el dict `source={...}` del `DetectionEvent`, agregar:

```python
                            "captured_at_ms": unit.captured_at_ms,
                            "scenario": config.run.scenario,
```

En el dict `model={...}` del mismo `DetectionEvent`, agregar los umbrales
aplicados (evidencia auto-contenida):

```python
                            "thresholds": {
                                "box_threshold": config.model.box_threshold,
                                "text_threshold": config.model.text_threshold,
                                "confidence_threshold": config.model.confidence_threshold,
                                "iou_threshold": config.model.iou_threshold,
                                "postprocess_min_confidence": config.postprocess.min_confidence,
                            },
```

En el `MetricSample(...)` del mismo bloque, agregar:

```python
                        capture_to_done_ms=capture_to_done_ms,
```

- [ ] **Step 4: Contadores de captura y degradación de fuente al cierre**

Dentro del `try`, inmediatamente después del loop de unidades (con el writer aún abierto), registrar la degradación de fuente como hecho persistible (Tabla 55; `ErrorEvent` ya está importado en `pipeline.py`):

```python
        # Condición de degradación de la fuente en vivo (errors.jsonl)
        if getattr(source, "ended_reason", None) == "source_unreachable":
            artifact_writer.write_error(ErrorEvent(
                run_id=run_context.run_id,
                stage="source",
                severity="error",
                message=f"Fuente en vivo inaccesible: {config.source.path}",
                recoverable=False,
            ))
```

Tras el `finally` que cierra writer y adapter (después de `adapter.close()`), antes de `run_context.finish()`:

```python
    # Estadísticas de captura (solo fuentes en vivo las exponen)
    capture_stats = getattr(source, "stats", None)
    if capture_stats is not None:
        run_context.frames_captured = capture_stats.frames_captured
        run_context.frames_dropped = capture_stats.frames_dropped
        run_context.buffer_max_depth = capture_stats.max_depth
        run_context.source_ended_reason = getattr(source, "ended_reason", None)
```

y en el reporte final por consola, tras la línea de detecciones totales:

```python
    if run_context.frames_captured:
        console.print(
            f"  Captura: {run_context.frames_captured} frames, "
            f"{run_context.frames_dropped} descartados "
            f"(cierre: {run_context.source_ended_reason})"
        )
```

- [ ] **Step 5: Resumen con métricas de operación continua**

En `sinks/run_artifact_writer.py`, dentro de `write_summary`, antes de `summary = RunSummary(`:

```python
        frames_captured = self.context.frames_captured or None
        frames_dropped = self.context.frames_dropped if frames_captured else None
        drop_rate = (
            round(self.context.frames_dropped / frames_captured, 4)
            if frames_captured
            else None
        )
        buffer_max_depth = self.context.buffer_max_depth if frames_captured else None
        backpressure_policy = "drop_oldest" if frames_captured else None
        # No se condiciona a frames_captured: una fuente inaccesible termina
        # con 0 frames y su razón de cierre debe quedar en el resumen.
        source_ended_reason = self.context.source_ended_reason
```

y en el constructor `RunSummary(...)`, tras `gpu_memory_peak_mb=...`:

```python
            frames_captured=frames_captured,
            frames_dropped=frames_dropped,
            drop_rate=drop_rate,
            buffer_max_depth=buffer_max_depth,
            backpressure_policy=backpressure_policy,
            source_ended_reason=source_ended_reason,
```

- [ ] **Step 6: Verificar que nada se rompió**

Run: `pytest -q && ruff check src tests`
Expected: suite completa PASS, lint limpio.

- [ ] **Step 7: Commit**

```bash
git add src/eovrt_media/runtime/pipeline.py src/eovrt_media/sinks/run_artifact_writer.py
git commit -m "feat: pipeline con fuente live_stream, progreso no acotado y métricas de captura"
```

---

### Task 8: Test de integración E2E — EBE simulado con mock detector

**Files:**
- Test: `tests/test_pipeline_ebe.py`

- [ ] **Step 1: Escribir el test de integración**

```python
"""E2E del escenario EBE: video sintético servido como fuente en vivo + mock detector."""

import json
import textwrap
from pathlib import Path

import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.runtime.pipeline import run_pipeline


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    """Genera un video corto de 20 frames con contenido variable."""
    path = tmp_path / "sim.mp4"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48)
    )
    for i in range(20):
        frame = np.full((48, 64, 3), i * 10 % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture
def ebe_config(tmp_path: Path, synthetic_video: Path) -> Path:
    prompts = tmp_path / "prompts.yaml"
    prompts.write_text(textwrap.dedent("""
        prompt_set:
          id: ebe_test
          items:
            - id: person
              text: "person"
    """))
    config = tmp_path / "ebe_run.yaml"
    config.write_text(textwrap.dedent(f"""
        run:
          scenario: EBE
          name: ebe_e2e_test
        source:
          type: live_stream
          path: {synthetic_video}
          buffer_size: 2
        sampling:
          max_units: 5
          max_duration_s: 30
        model:
          name: mock
        prompts:
          file: {prompts}
        outputs:
          run_dir: {tmp_path / "runs"}
          save_previews: true
          preview_max: 2
    """))
    return config


class TestPipelineEbe:
    def test_ebe_run_produces_traceable_evidence(self, ebe_config, tmp_path):
        run_id = run_pipeline(load_run_config(ebe_config))
        run_dir = tmp_path / "runs" / run_id

        summary = json.loads((run_dir / "summary.json").read_text())
        assert summary["scenario"] == "EBE"
        assert summary["units_processed"] >= 1
        assert summary["frames_captured"] >= summary["units_processed"]
        assert summary["frames_dropped"] is not None
        assert summary["drop_rate"] is not None
        assert summary["buffer_max_depth"] >= 1
        assert summary["backpressure_policy"] == "drop_oldest"
        assert summary["source_ended_reason"] in ("max_units", "max_duration_s", "end_of_stream")

        events = [
            json.loads(line)
            for line in (run_dir / "detections.jsonl").read_text().splitlines()
        ]
        assert events
        for event in events:
            assert event["source"]["source_type"] == "live_frame"
            assert event["source"]["scenario"] == "EBE"
            assert event["source"]["captured_at_ms"] is not None

        metrics = [
            json.loads(line)
            for line in (run_dir / "metrics.jsonl").read_text().splitlines()
        ]
        assert any(m.get("capture_to_done_ms") is not None for m in metrics)

    def test_ebe_and_dbe_share_the_same_pipeline_entrypoint(self, ebe_config):
        # La convergencia es estructural: no existe otro run_pipeline.
        # Este test es documentación ejecutable del principio rector.
        from eovrt_media.runtime import pipeline

        assert not hasattr(pipeline, "run_pipeline_ebe")
        assert not hasattr(pipeline, "run_pipeline_live")
```

- [ ] **Step 2: Correr el test E2E**

Run: `pytest tests/test_pipeline_ebe.py -v`
Expected: PASS. Si `frames_captured < units_processed` aparece, revisar el orden de lectura de stats (deben leerse después de cerrar la fuente).

- [ ] **Step 3: Correr toda la suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: PASS, lint limpio.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_ebe.py
git commit -m "test: E2E del escenario EBE con fuente en vivo simulada"
```

---

### Task 9: Catálogo y run configs EBE

**Files:**
- Create: `configs/datasets/webcam0.yaml`
- Create: `configs/datasets/video_sim_live.yaml`
- Create: `configs/runs/ebe_mock_sim.yaml`
- Create: `configs/runs/ebe_yoloe_webcam.yaml`

- [ ] **Step 1: Entradas del catálogo de datasets**

`configs/datasets/webcam0.yaml`:

```yaml
# Catálogo de datasets — webcam local (EBE)
description: >
  Webcam local (dispositivo 0) como fuente en vivo para corridas EBE.
  Conectividad: captura directa, sin red (modo EN-0). Transporte: driver local.

type: live_stream
path: "0"
buffer_size: 1
```

`configs/datasets/video_sim_live.yaml`:

```yaml
# Catálogo de datasets — simulación EBE sin hardware
description: >
  Reproduce data/samples/videos/sample.mp4 a su FPS nativo como si fuera una
  cámara (realtime). Permite ejecutar y testear el escenario EBE sin cámara.

type: live_stream
path: data/samples/videos/sample.mp4
realtime: true
buffer_size: 1
```

> **Nota (Tabla 55 del diseño):** toda entrada `live_stream` del catálogo declara en su `description` el medio de conectividad y el mecanismo de transporte — p. ej. "RTSP sobre LAN cableada" para una futura cámara IP. El archivo simulado y la webcam local son "sin red"; eso también se declara.

- [ ] **Step 2: Run configs EBE**

`configs/runs/ebe_mock_sim.yaml`:

```yaml
# Smoke test EBE: fuente en vivo simulada + detector mock
run:
  scenario: EBE
  name: ebe_mock_sim
  description: "EBE simulado (video a FPS nativo) con detector mock"

source:
  ref: video_sim_live

sampling:
  target_fps: 2
  max_duration_s: 20

model:
  ref: mock

prompts:
  ref: cr01_cr02_v1
  active_ids: [person, helmet, vest]
```

`configs/runs/ebe_yoloe_webcam.yaml`:

```yaml
# EBE real: webcam local + YOLOE-26s en GPU
run:
  scenario: EBE
  name: ebe_yoloe_webcam
  description: "EBE sobre webcam local con YOLOE-26s, 60 segundos de operación continua"

source:
  ref: webcam0

sampling:
  target_fps: 5
  max_duration_s: 60

model:
  ref: yoloe/yoloe-26s
  device: cuda

prompts:
  ref: cr01_cr02_v2_short
  active_ids: [person, helmet, vest]
```

- [ ] **Step 3: Validar las cuatro configs**

Run:
```bash
for f in configs/runs/ebe_mock_sim.yaml configs/runs/ebe_yoloe_webcam.yaml; do
  eovrt-media validate-config --config "$f"
done
```
Expected: `✓ Configuración válida` para ambas.

- [ ] **Step 4: Smoke run manual (requiere data/samples/videos/sample.mp4)**

Run: `eovrt-media run --config configs/runs/ebe_mock_sim.yaml`
Expected: corrida EBE que corta a los 20 s, con `frames_captured`/`frames_dropped` en el resumen. Si no existe `sample.mp4`, omitir este paso (el E2E de la Task 8 cubre el flujo con video sintético).

- [ ] **Step 5: Commit**

```bash
git add configs/datasets/webcam0.yaml configs/datasets/video_sim_live.yaml configs/runs/ebe_mock_sim.yaml configs/runs/ebe_yoloe_webcam.yaml
git commit -m "feat: catálogo y run configs del escenario EBE (webcam y simulación)"
```

---

### Task 10: Documentación — ADR, arquitectura y uso

**Files:**
- Create: `docs/decisions/ADR-0005-ebe-modo-entrada.md`
- Modify: `docs/architecture.md` (flujo y escenarios)
- Modify: `docs/usage.md` (sección EBE)
- Modify: `configs/README.md` (datasets live)
- Modify: `docs/README.md` (índice de ADRs)
- Modify: `CLAUDE.md` (abstracciones clave)

- [ ] **Step 1: Escribir ADR-0005**

`docs/decisions/ADR-0005-ebe-modo-entrada.md`:

```markdown
# ADR-0005 — EBE como modo de entrada sobre el mismo plano de medios

- **Estado**: aceptada
- **Fecha**: (fecha de implementación)

## Contexto

El plano de medios debía soportar dos escenarios: DBE (dataset offline,
corridas reproducibles) y EBE (cámara/stream en vivo, operación continua).
El diseño arquitectónico de la plataforma (Etapa 3, §17.3.14) los define como
topologías de ejecución de una misma arquitectura, no como arquitecturas
distintas; DBE precede a EBE como escenario de estabilización (DA-10).
El riesgo era bifurcar el pipeline en dos rutas de procesamiento.

## Decisión

DBE y EBE no son dos pipelines: son dos adaptadores de entrada sobre un mismo
plano de medios. Ambos convergen en `VisualUnit`; desde ahí, inferencia,
postproceso, publicación de evidencia, métricas y trazabilidad son idénticos.

- `LiveStreamSource` (EBE) implementa la misma interfaz `BaseSource` que las
  fuentes DBE: hilo de captura → buffer acotado con descarte de frames viejos
  (backpressure contabilizado) → iterador con pacing por `target_fps` y corte
  por `max_units` / `max_duration_s`.
- `VisualUnit` gana `frame` (payload en memoria, no serializado) y
  `captured_at_ms` (epoch ms): los frames vivos no pueden re-leerse de disco.
- `captured_at_ms` tiene semántica de *recepción/decodificación* en el nodo
  de procesamiento (contrato FrameMetadata: "instante de captura o recepción
  cuando aplique"); en webcam local captura ≈ recepción, en RTSP no existe
  reloj de cámara.
- La evidencia (`DetectionEvent.source`) incorpora `scenario` y
  `captured_at_ms`; las métricas agregan `capture_to_done_ms` por unidad y,
  en el resumen, `frames_captured` / `frames_dropped` / `drop_rate` /
  `buffer_max_depth` / `backpressure_policy` / `source_ended_reason`
  (señales de colas, backpressure y degradación — Tablas 53 y 55 del diseño).
  Una fuente inaccesible se registra además como `ErrorEvent` en
  `errors.jsonl`.
- EBE se simula sin hardware con un archivo de video en `realtime: true`,
  lo que mantiene el escenario testeable en CI.

## Consecuencias

- El núcleo de procesamiento no conoce el origen: cambiar de DBE a EBE es
  cambiar `source.ref` y el escenario en la run config.
- La salida sigue siendo evidencia perceptiva primaria; patrones de riesgo y
  alertas siguen perteneciendo al plano de control (ADR-0001).
- El tracking opcional tiene su costura definida tras el postproceso, sin
  implementación (fuera de alcance del repo).
- Una webcam o cámara IP/RTSP en la red local corresponde al modo EN-0
  ("captura sin análisis local") del despliegue lógico; EN-1/EN-2
  (preprocesamiento o preselección en borde) quedan fuera de alcance.
- La nomenclatura contractual del diseño (Tabla 50) se conserva:
  `RunConfig`, `DetectionEvent`, `MetricSample` y `ErrorEvent` son idénticos;
  `VisualUnit` materializa FrameMetadata ("unidad visual" + payload);
  `SourceSection`/`ModelSection`/`PromptSet` + catálogos materializan
  SourceDefinition, ModelProfile y PromptDefinition.
```

- [ ] **Step 2: Actualizar docs/architecture.md**

Reemplazar la sección "Flujo del pipeline" por:

```markdown
## Flujo del pipeline

```
Fuente visual (configs/datasets/)
    ↓
Adaptador de entrada (sources/: ImageFolderSource | VideoFileSource | LiveStreamSource)
    ↓
VisualUnit normalizada  ←── punto de convergencia DBE/EBE
    ↓
Control de ritmo y muestreo (sampling: every_n / target_fps / max_units / max_duration_s)
    ↓
Preprocesamiento → Inferencia OVD (models/) → Postproceso (postprocessing/)
    ↓
[costura de tracking opcional — no implementada]
    ↓
Publicación de evidencia (sinks/: detections.jsonl) + métricas + trazabilidad (runs/<run_id>/)
```

## Escenarios DBE y EBE

DBE y EBE no son dos pipelines distintos: son dos modos de entrada sobre un
mismo plano de medios modular.

- **DBE** — dataset/videos offline → mismo pipeline → evidencia y métricas
  reproducibles (comparación controlada de modelos, prompts, resoluciones,
  umbrales y muestreo).
- **EBE** — cámara/stream/entorno controlado → mismo pipeline → evidencia y
  métricas de operación continua (buffers, descarte de frames, backpressure,
  latencia captura→publicación).

A partir de `VisualUnit`, ningún módulo depende del origen del frame.
```

y en "Entrada", agregar a la lista de fuentes: `cámara o stream en vivo (EBE)`.

- [ ] **Step 3: Actualizar docs/usage.md**

Agregar tras la sección "Sobre video local":

```markdown
### Escenario EBE (fuente en vivo)

Las corridas EBE usan una fuente `live_stream`: webcam, URL RTSP/HTTP, o un
archivo de video reproducido a FPS nativo para simular una cámara.

```bash
# EBE simulado sin hardware (sample.mp4 como cámara, detector mock)
eovrt-media run --config configs/runs/ebe_mock_sim.yaml

# EBE real con webcam local y YOLOE
eovrt-media run --config configs/runs/ebe_yoloe_webcam.yaml
```

El ritmo se controla con `sampling.target_fps` y la corrida corta por
`sampling.max_duration_s` o `max_units`. El resumen agrega `frames_captured`,
`frames_dropped`, `drop_rate`, `buffer_max_depth`, `backpressure_policy` y
`source_ended_reason` (por qué terminó la corrida: corte configurado, fin del
stream o fuente inaccesible); cada métrica incluye `capture_to_done_ms`
(latencia captura → publicación). Una fuente inaccesible queda además
registrada en `errors.jsonl`.
```

- [ ] **Step 4: Actualizar configs/README.md, docs/README.md y CLAUDE.md**

`configs/README.md`, en la sección Catálogos, ampliar la entrada de datasets:

```markdown
**`datasets/<nombre>.yaml`** — una fuente de datos: `type`
(`image_folder` | `video_file` | `live_stream`), `path` y opcionales. Para
`live_stream`, `path` es la URI (índice de webcam, rtsp://, o un archivo con
`realtime: true` para simular una cámara) y aplican `buffer_size`,
`reconnect_attempts` y `read_timeout_s`.
```

`docs/README.md`, agregar a la lista de ADRs:

```markdown
- [decisions/ADR-0005-ebe-modo-entrada.md](decisions/ADR-0005-ebe-modo-entrada.md) — EBE como modo de entrada sobre el mismo pipeline (convergencia en VisualUnit).
```

`CLAUDE.md`, en Key abstractions, actualizar la línea de `BaseSource`:

```markdown
- `BaseSource` (`sources/base.py`) — yields `VisualUnit` objects; implementations: `ImageFolderSource`, `VideoFileSource` (DBE), `LiveStreamSource` (EBE live capture with bounded buffer + frame dropping). Live units carry the frame in memory (`VisualUnit.frame`).
```

- [ ] **Step 5: Verificación final completa**

Run: `pytest -q && ruff check src tests && for f in configs/runs/*.yaml; do eovrt-media validate-config --config "$f" > /dev/null || echo "FALLO: $f"; done && echo OK`
Expected: suite PASS, lint limpio, `OK`.

- [ ] **Step 6: Commit**

```bash
git add docs/ configs/README.md CLAUDE.md
git commit -m "docs: ADR-0005 y documentación del escenario EBE"
```

---

## Fuera de alcance (explícito)

- **Anotaciones embebidas en la unidad visual (DBE)**: la especificación pide
  conservar la referencia a las "anotaciones disponibles". Se satisface por
  referencia, no por copia: `VisualUnit.source_path` + el manifiesto del
  dataset (`data/samples/images/dataset_v1/selection_manifest.json`, COCO de
  MOCS) permiten recuperar las anotaciones de cada unidad. Embeber ground
  truth en la evidencia mezclaría evaluación con percepción (YAGNI hasta que
  exista un evaluador que lo consuma).
- **MOT / tracking**: solo queda definida la costura (post-postproceso). Sin implementación.
- **Buses de mensajes / MQ** para publicación: la evidencia sigue saliendo por `RunArtifactWriter`. La interfaz de sinks ya desacopla; un publisher de red sería un sink adicional futuro.
- **MediaMTX / streaming de infraestructura**: la simulación `realtime` cubre la necesidad experimental local.
- **Reglas de riesgo, alertas, zonas**: plano de control (ADR-0001).

## Riesgos y mitigaciones

- **Tests con timing** (pacing, max_duration): se usan timeouts generosos y asserts tolerantes (`>= 1`, `<= N`) para evitar flakiness; la lógica de descarte se testea de forma determinista en el buffer, no por timing.
- **`cv2.VideoCapture` sobre RTSP** puede bloquear más que `read_timeout_s`: el hilo de captura es daemon y el `join(timeout=2.0)` en `close()` evita colgar el cierre de la corrida.
- **Memoria**: el buffer acotado (default 1) garantiza que nunca se acumulan frames sin procesar.
```
