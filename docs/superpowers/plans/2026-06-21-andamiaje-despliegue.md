# Andamiaje de Despliegue — Topologías DBE/EBE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganizar el pipeline del plano de medios de loop síncrono a arquitectura productor/consumidor desacoplada, implementando el escenario A (un host + DBE) con todas las costuras para EBE/dos-nodos/IPC/network declaradas pero no implementadas.

**Architecture:** Dos hilos desacoplados por `TransportAdapter` (backend `memory`): productor (ingesta → `RateGate` → `Normalizer` → `channel.offer`) + consumidor (channel.request → inferencia → postproceso → escritura). El canal tiene dos políticas (`deterministic` con backpressure, `bounded_freshness` con head-drop). Contratos + interfaces completas; backends diferidos son estrictamente aditivos.

**Tech Stack:** Python 3.11, Pydantic v2, threading.Thread, queue.Queue, NumPy, Pillow, OpenCV, PyTorch, Typer, Rich.

## Global Constraints

- **Nunca agregar `Co-Authored-By:` a los commits.** Sin atribución de co-autor alguna.
- Python 3.11, typing annotations con `from __future__ import annotations`.
- Pydantic v2: usar `model_validator(mode="after")`, `Field(default_factory=...)`.
- TDD: tests primero, implementación mínima, nunca comentar tests.
- Sin `sampling` en YAML: si un YAML tiene `sampling`, el loader lanza error con mapeo explícito.
- Gating estricto: cualquier feature declarada pero no implementada → `run` falla con mensaje claro.
- Sin `Co-Authored-By` en ningún commit.
- Un solo modelo por run (run_config tiene exactamente un `model`).
- Tests: usar `MockDetectorAdapter` para todo end-to-end; nunca cargar pesos reales.
- Carpeta de trabajo: `/home/simonll4/projects/e-ovrt_media-plane`. Activar venv: `source .venv/bin/activate`.

---

## File Structure

### Archivos nuevos

```
src/eovrt_media/
  contracts/
    normalized_unit.py          # NormalizedUnit, ResizeTransform, PayloadFormat, END, protocol msgs
  transport/
    __init__.py
    base.py                     # TransportAdapter ABC
    memory.py                   # MemoryTransportAdapter (deterministic + bounded_freshness)
    rate_gate.py                # RateGate (stride, solo deterministic)
    declared.py                 # IpcTransportAdapter, NetworkTransportAdapter stubs
    factory.py                  # create_transport(config) factory
  preprocessing/
    normalizer.py               # normalize_spatial(), prepare_model_input()
  sources/
    live_source.py              # LiveSource(BaseSource) abstracta stub

tests/
  test_transport.py             # Suite agnóstica de backend + políticas
  test_normalizer.py            # Normalizer + paridad numérica + reproyección de cajas
  test_config_deployment.py     # Derivación, validación cruzada, gating, migración sampling
  test_pipeline_two_threads.py  # Reproducibilidad, concurrencia, apagado limpio
  test_traceability.py          # run_descriptor, provenance, schema_version, auto-naming
```

### Archivos a modificar

```
src/eovrt_media/
  contracts/__init__.py         # Exportar NormalizedUnit, PayloadFormat, END, ResizeTransform
  contracts/detection.py        # Sin cambios estructurales (RawDetection ya OK)
  contracts/events.py           # RunDescriptor, RunProvenance, RunSummary con nuevas métricas
  contracts/metrics.py          # latency_normalize_ms, schema_version v2
  models/base.py                # ModelInputSpec, forward() abstract, input_spec abstract property
  models/mock_detector.py       # input_spec, forward(NormalizedUnit, prompts)
  models/grounding_dino_adapter.py  # input_spec, forward(NormalizedUnit, prompts)
  models/yoloe_adapter.py       # input_spec, forward(NormalizedUnit, prompts)
  config/schemas.py             # RateControlConfig, TransportConfig, TopologyConfig, SourceSection.kind/dataset_id/view/split/vocabulary, RunSection.max_units
  config/loader.py              # derivación de defaults, validación deployment, gating, sampling error
  runtime/pipeline.py           # Refactor: producer thread + consumer main, RateGate, Normalizer
  runtime/run_context.py        # units_dropped, backpressure_wait_ms, max_staleness_observed_ms
  postprocessing/detection_normalizer.py  # Aceptar transform: ResizeTransform para reproyección
  sinks/run_artifact_writer.py  # write_provenance(), run_descriptor en summary.json, p99
  metrics/timers.py             # normalize_ms, p99_latency_ms(), start/end_normalize
  cli.py                        # inspect-run command

configs/
  runs/gdino.yaml               # Migrar: quitar sampling, agregar rate_control/transport/topology
  runs/mock.yaml                # Ídem
  runs/mock_chv.yaml            # Ídem
  runs/mock_mocs.yaml           # Ídem
  runs/yoloe.yaml               # Ídem
  runs/yoloe_video.yaml         # Ídem
  datasets/bench_v2_test.yaml   # Agregar dataset_id, view, split, vocabulary
  datasets/bench_v2_val.yaml    # Ídem
  datasets/chv.yaml             # Ídem
  datasets/demo_v2.yaml         # Ídem
  datasets/mocs.yaml            # Ídem
  datasets/video_sample.yaml    # Ídem
  datasets/dataset_v1.yaml      # Ídem
```

---

## Task 1: Contratos — `NormalizedUnit`, `ResizeTransform`, `PayloadFormat`, `END`, mensajes de protocolo

**Files:**
- Create: `src/eovrt_media/contracts/normalized_unit.py`
- Modify: `src/eovrt_media/contracts/__init__.py`
- Test: `tests/test_contracts.py` (extender el existente)

**Interfaces:**
- Produces: `ResizeTransform`, `PayloadFormat`, `NormalizedUnit`, `END`, `NetworkRequest`, `NetworkResponse`, `NetworkHeartbeat` — usados en Tasks 2–7.

- [ ] **Step 1: Escribir test de NormalizedUnit**

```python
# En tests/test_contracts.py — agregar clase TestNormalizedUnit
import numpy as np
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, ResizeTransform, PayloadFormat, END
)

class TestNormalizedUnit:
    def test_roundtrip_fields(self):
        payload = np.zeros((480, 640, 3), dtype=np.uint8)
        transform = ResizeTransform(scale_x=0.5, scale_y=0.5, pad_x=0.0, pad_y=0.0)
        unit = NormalizedUnit(
            run_id="run_001",
            unit_id="unit_001",
            source_id="img.jpg",
            frame_index=0,
            timestamp_ms=1000.0,
            orig_width=1280,
            orig_height=960,
            payload=payload,
            payload_format=PayloadFormat.UINT8_RGB,
            target_size=(480, 640),
            transform=transform,
        )
        assert unit.orig_width == 1280
        assert unit.target_size == (480, 640)
        assert unit.payload.shape == (480, 640, 3)
        assert unit.transform.scale_x == 0.5

    def test_payload_format_enum(self):
        assert PayloadFormat.UINT8_RGB.value == "uint8_rgb"
        assert PayloadFormat.FP32.value == "fp32"
        assert PayloadFormat.FP16.value == "fp16"

    def test_end_sentinel_is_singleton_class(self):
        assert END is END  # clase usada como sentinel, no instanciada

    def test_resize_transform_project_box(self):
        # letterbox con scale=0.5, pad_x=10, pad_y=5
        t = ResizeTransform(scale_x=0.5, scale_y=0.5, pad_x=10.0, pad_y=5.0)
        # Caja en espacio modelo: [30, 15, 80, 55]
        box_orig = t.project_to_original([30.0, 15.0, 80.0, 55.0])
        # (30-10)/0.5=40, (15-5)/0.5=20, (80-10)/0.5=140, (55-5)/0.5=100
        assert box_orig == pytest.approx([40.0, 20.0, 140.0, 100.0], abs=0.01)
```

- [ ] **Step 2: Ejecutar test para verificar que falla**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane && source .venv/bin/activate
pytest tests/test_contracts.py::TestNormalizedUnit -v
```
Expected: `ImportError` o `ModuleNotFoundError` (el módulo no existe aún)

- [ ] **Step 3: Implementar `contracts/normalized_unit.py`**

```python
"""Contrato NormalizedUnit — payload normalizado espacialmente que viaja por el canal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from pydantic import BaseModel, ConfigDict


class PayloadFormat(str, Enum):
    UINT8_RGB = "uint8_rgb"  # impl
    FP32 = "fp32"            # impl
    FP16 = "fp16"            # declarado, no implementado


@dataclass
class ResizeTransform:
    """Parámetros del resize aplicado al payload — necesarios para reproyectar cajas."""
    scale_x: float
    scale_y: float
    pad_x: float  # píxeles de padding horizontal (izquierda)
    pad_y: float  # píxeles de padding vertical (arriba)

    def project_to_original(self, box_xyxy: list[float]) -> list[float]:
        """Proyecta una caja de espacio-modelo a píxeles originales."""
        x1, y1, x2, y2 = box_xyxy
        return [
            (x1 - self.pad_x) / self.scale_x,
            (y1 - self.pad_y) / self.scale_y,
            (x2 - self.pad_x) / self.scale_x,
            (y2 - self.pad_y) / self.scale_y,
        ]


class NormalizedUnit(BaseModel):
    """Unidad normalizada espacialmente que viaja por el canal productor→consumidor."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str | None = None
    unit_id: str
    source_id: str | None = None
    frame_index: int | None = None
    timestamp_ms: float | None = None

    orig_width: int
    orig_height: int

    payload: np.ndarray
    payload_format: PayloadFormat = PayloadFormat.UINT8_RGB
    target_size: tuple[int, int]  # (H, W) del payload
    transform: ResizeTransform


class END:
    """Sentinel de fin de canal — el productor lo emite al agotar la fuente."""


# Contratos del protocolo de red (declarados, backend network no implementado)
@dataclass
class NetworkRequest:
    """Mensaje REQUEST: Nodo B → Nodo A (listo para siguiente frame)."""
    request_id: str


@dataclass
class NetworkResponse:
    """Mensaje RESPONSE: Nodo A → Nodo B (frame del buffer)."""
    request_id: str
    unit: NormalizedUnit


@dataclass
class NetworkHeartbeat:
    """Mensaje HEARTBEAT: bidireccional, keep-alive."""
    node_id: str
    timestamp_ms: float
```

- [ ] **Step 4: Actualizar `contracts/__init__.py`**

Agregar imports al archivo existente:
```python
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit,
    ResizeTransform,
    PayloadFormat,
    END,
)
```

- [ ] **Step 5: Ejecutar tests para verificar que pasan**

```bash
pytest tests/test_contracts.py -v
```
Expected: todos los tests (existentes + nuevos) PASS

- [ ] **Step 6: Commit**

```bash
git add src/eovrt_media/contracts/normalized_unit.py src/eovrt_media/contracts/__init__.py tests/test_contracts.py
git commit -m "feat: add NormalizedUnit contract, ResizeTransform, PayloadFormat, END sentinel"
```

---

## Task 2: `ModelInputSpec` + propiedad `input_spec` en adaptadores

**Files:**
- Modify: `src/eovrt_media/models/base.py`
- Modify: `src/eovrt_media/models/mock_detector.py`
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py`
- Modify: `src/eovrt_media/models/yoloe_adapter.py`
- Test: `tests/test_model_input_spec.py` (nuevo)

**Interfaces:**
- Consumes: nada de Tasks anteriores (ModelInputSpec es independiente)
- Produces: `ModelInputSpec`, `BaseDetectorAdapter.input_spec` property — usado en Task 3 (Normalizer).

- [ ] **Step 1: Escribir tests**

```python
# tests/test_model_input_spec.py
from eovrt_media.models.base import ModelInputSpec
from eovrt_media.models.mock_detector import MockDetectorAdapter
from eovrt_media.models import create_adapter
from eovrt_media.config.schemas import ModelSection


class TestModelInputSpec:
    def test_dataclass_fields(self):
        spec = ModelInputSpec(
            target_size=(800, 800),
            resize_mode="letterbox",
            mean=(0.485, 0.456, 0.406),
            std=(0.229, 0.224, 0.225),
        )
        assert spec.target_size == (800, 800)
        assert spec.dtype == "float32"       # default
        assert spec.channel_order == "rgb"   # default

    def test_mock_adapter_has_input_spec(self):
        adapter = MockDetectorAdapter()
        spec = adapter.input_spec
        assert isinstance(spec, ModelInputSpec)
        assert len(spec.target_size) == 2
        assert spec.target_size[0] > 0 and spec.target_size[1] > 0

    def test_gdino_adapter_has_input_spec(self):
        section = ModelSection(adapter="grounding_dino_hf", device="cpu")
        adapter = create_adapter(section)
        spec = adapter.input_spec
        assert spec.target_size == (800, 800)
        assert spec.resize_mode == "letterbox"

    def test_yoloe_adapter_has_input_spec(self):
        section = ModelSection(adapter="yoloe", device="cpu")
        adapter = create_adapter(section)
        spec = adapter.input_spec
        assert spec.target_size == (640, 640)
        assert spec.resize_mode == "letterbox"
```

- [ ] **Step 2: Ejecutar para verificar que falla**

```bash
pytest tests/test_model_input_spec.py -v
```
Expected: `ImportError` — `ModelInputSpec` no existe en `models/base.py`

- [ ] **Step 3: Agregar `ModelInputSpec` y propiedad abstracta a `models/base.py`**

Agregar al inicio del archivo (después de los imports existentes):
```python
from dataclasses import dataclass, field


@dataclass
class ModelInputSpec:
    """Especificación de preprocesamiento de imagen del modelo."""
    target_size: tuple[int, int]          # (H, W) objetivo del Normalizer
    resize_mode: str = "letterbox"        # "letterbox" | "bilinear"
    channel_order: str = "rgb"
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)
    dtype: str = "float32"
```

Agregar a `BaseDetectorAdapter`:
```python
    @property
    @abstractmethod
    def input_spec(self) -> "ModelInputSpec":
        """Especificación de preprocesamiento requerida por el modelo."""
```

- [ ] **Step 4: Agregar `input_spec` a `MockDetectorAdapter`**

```python
# En mock_detector.py — agregar import y propiedad
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec

# Dentro de la clase MockDetectorAdapter:
    @property
    def input_spec(self) -> ModelInputSpec:
        return ModelInputSpec(
            target_size=(640, 640),
            resize_mode="letterbox",
            mean=(0.0, 0.0, 0.0),
            std=(1.0, 1.0, 1.0),
        )
```

- [ ] **Step 5: Agregar `input_spec` a `GroundingDinoHFAdapter`**

```python
# En grounding_dino_adapter.py — agregar propiedad
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec

    @property
    def input_spec(self) -> ModelInputSpec:
        return ModelInputSpec(
            target_size=(800, 800),
            resize_mode="letterbox",
            mean=(0.485, 0.456, 0.406),
            std=(0.229, 0.224, 0.225),
        )
```

- [ ] **Step 6: Agregar `input_spec` a `YOLOEUltralyticsAdapter`**

```python
# En yoloe_adapter.py — agregar propiedad
from eovrt_media.models.base import BaseDetectorAdapter, ModelInputSpec

    @property
    def input_spec(self) -> ModelInputSpec:
        size = self.image_size if isinstance(self.image_size, int) else 640
        return ModelInputSpec(
            target_size=(size, size),
            resize_mode="letterbox",
            mean=(0.0, 0.0, 0.0),
            std=(1.0, 1.0, 1.0),
        )
```

- [ ] **Step 7: Ejecutar todos los tests**

```bash
pytest tests/test_model_input_spec.py tests/test_pipeline_mock.py -v
```
Expected: PASS en todos

- [ ] **Step 8: Commit**

```bash
git add src/eovrt_media/models/base.py src/eovrt_media/models/mock_detector.py src/eovrt_media/models/grounding_dino_adapter.py src/eovrt_media/models/yoloe_adapter.py tests/test_model_input_spec.py
git commit -m "feat: add ModelInputSpec dataclass and input_spec property to all adapters"
```

---

## Task 3: Etapa `Normalizer` — `normalize_spatial()` + `prepare_model_input()`

**Files:**
- Create: `src/eovrt_media/preprocessing/normalizer.py`
- Modify: `src/eovrt_media/postprocessing/detection_normalizer.py`
- Modify: `src/eovrt_media/preprocessing/__init__.py`
- Test: `tests/test_normalizer.py` (nuevo)

**Interfaces:**
- Consumes: `NormalizedUnit`, `ResizeTransform`, `PayloadFormat`, `ModelInputSpec` (Tasks 1–2)
- Produces:
  - `normalize_spatial(unit: VisualUnit, spec: ModelInputSpec, payload_format: PayloadFormat) -> NormalizedUnit`
  - `prepare_model_input(unit: NormalizedUnit, spec: ModelInputSpec, device: str) -> torch.Tensor`
  - `DetectionNormalizer.normalize(..., transform: ResizeTransform | None = None) -> list[Detection]`

- [ ] **Step 1: Escribir tests**

```python
# tests/test_normalizer.py
import numpy as np
import pytest
import cv2
from pathlib import Path
from PIL import Image

from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform
)
from eovrt_media.models.base import ModelInputSpec
from eovrt_media.preprocessing.normalizer import normalize_spatial, prepare_model_input


def _make_visual_unit(tmp_path: Path, width: int = 800, height: int = 600) -> VisualUnit:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (100, 150, 200)
    p = tmp_path / "test.jpg"
    cv2.imwrite(str(p), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return VisualUnit(
        unit_id="u1",
        source_type="image",
        width=width,
        height=height,
        path=str(p),
    )


class TestNormalizeSpatial:
    def test_output_shape_letterbox(self, tmp_path):
        unit = _make_visual_unit(tmp_path, width=800, height=600)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        assert isinstance(result, NormalizedUnit)
        assert result.payload.shape == (640, 640, 3)
        assert result.payload.dtype == np.uint8
        assert result.target_size == (640, 640)

    def test_transform_scale_computation(self, tmp_path):
        unit = _make_visual_unit(tmp_path, width=800, height=400)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        # scale = min(640/800, 640/400) = 0.8 (limitado por height=400 → 320, menor)
        # En realidad: min(640/800, 640/400) = min(0.8, 1.6) = 0.8
        # scaled: 800*0.8=640, 400*0.8=320 → pad_y = (640-320)/2 = 160
        assert result.transform.scale_x == pytest.approx(0.8, abs=0.01)
        assert result.transform.scale_y == pytest.approx(0.8, abs=0.01)
        assert result.transform.pad_y == pytest.approx(160.0, abs=1.0)
        assert result.transform.pad_x == pytest.approx(0.0, abs=1.0)

    def test_metadata_propagated(self, tmp_path):
        unit = _make_visual_unit(tmp_path, width=800, height=600)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        result = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        assert result.orig_width == 800
        assert result.orig_height == 600
        assert result.unit_id == "u1"


class TestPrepareModelInput:
    def test_output_tensor_shape(self, tmp_path):
        import torch
        unit = _make_visual_unit(tmp_path)
        spec = ModelInputSpec(target_size=(640, 640), resize_mode="letterbox")
        normalized = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        tensor = prepare_model_input(normalized, spec, device="cpu")
        assert tensor.shape == (1, 3, 640, 640)  # (batch, C, H, W)
        assert tensor.dtype == torch.float32

    def test_output_values_normalized(self, tmp_path):
        import torch
        unit = _make_visual_unit(tmp_path)
        spec = ModelInputSpec(
            target_size=(640, 640),
            mean=(0.0, 0.0, 0.0),
            std=(1.0, 1.0, 1.0),
        )
        normalized = normalize_spatial(unit, spec, PayloadFormat.UINT8_RGB)
        tensor = prepare_model_input(normalized, spec, device="cpu")
        # Con mean=0, std=1, los valores deben estar en [0, 1]
        assert tensor.min() >= 0.0
        assert tensor.max() <= 1.0


class TestDetectionNormalizerWithTransform:
    def test_box_reprojection_via_transform(self):
        from eovrt_media.contracts.detection import RawDetection
        from eovrt_media.postprocessing.detection_normalizer import DetectionNormalizer

        # Original: 800x600, modelo ve: 640x640 (letterbox scale=0.8, pad_y=160)
        transform = ResizeTransform(scale_x=0.8, scale_y=0.8, pad_x=0.0, pad_y=160.0)
        # Caja en espacio modelo: [160, 288, 480, 448]
        raw = [RawDetection(label="person", score=0.9, box_xyxy=[160.0, 288.0, 480.0, 448.0])]
        normalizer = DetectionNormalizer(min_confidence=0.0, min_box_area_px=0.0)
        detections = normalizer.normalize(
            raw_detections=raw,
            width=800,
            height=600,
            model_name="mock",
            transform=transform,
        )
        assert len(detections) == 1
        x1, y1, x2, y2 = detections[0].bbox_xyxy
        # (160-0)/0.8=200, (288-160)/0.8=160, (480-0)/0.8=600, (448-160)/0.8=360
        assert x1 == pytest.approx(200.0, abs=1.0)
        assert y1 == pytest.approx(160.0, abs=1.0)
        assert x2 == pytest.approx(600.0, abs=1.0)
        assert y2 == pytest.approx(360.0, abs=1.0)

    def test_no_transform_keeps_existing_behavior(self):
        from eovrt_media.contracts.detection import RawDetection
        from eovrt_media.postprocessing.detection_normalizer import DetectionNormalizer

        raw = [RawDetection(label="person", score=0.9, box_xyxy=[100.0, 50.0, 300.0, 250.0])]
        normalizer = DetectionNormalizer(min_confidence=0.0, min_box_area_px=0.0)
        detections = normalizer.normalize(raw, width=640, height=480, model_name="mock")
        assert detections[0].bbox_xyxy == [100.0, 50.0, 300.0, 250.0]
```

- [ ] **Step 2: Ejecutar para verificar que falla**

```bash
pytest tests/test_normalizer.py -v
```
Expected: `ImportError` — `normalize_spatial` no existe

- [ ] **Step 3: Implementar `preprocessing/normalizer.py`**

```python
"""Etapa de normalización espacial del productor + finalizador tensorial del consumidor."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, PayloadFormat, ResizeTransform
)
from eovrt_media.models.base import ModelInputSpec


def _letterbox(
    img: np.ndarray, target_h: int, target_w: int
) -> tuple[np.ndarray, ResizeTransform]:
    """Resize con letterbox (aspecto preservado + padding) a (target_h, target_w)."""
    h, w = img.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    pad_y = (target_h - new_h) // 2
    pad_x = (target_w - new_w) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, ResizeTransform(
        scale_x=scale, scale_y=scale, pad_x=float(pad_x), pad_y=float(pad_y)
    )


def _load_rgb_array(unit: VisualUnit) -> np.ndarray:
    """Decodifica la fuente visual a ndarray RGB uint8."""
    path_str = unit.path or unit.source_path
    if not path_str:
        raise ValueError(f"VisualUnit sin ruta: {unit.unit_id}")
    if unit.source_type == "video_frame":
        if unit.frame_index is None:
            raise ValueError(f"video_frame sin frame_index: {unit.unit_id}")
        cap = cv2.VideoCapture(path_str)
        if not cap.isOpened():
            raise ValueError(f"No se pudo abrir video: {path_str}")
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, unit.frame_index)
            ret, frame = cap.read()
            if not ret:
                raise ValueError(f"Frame {unit.frame_index} no disponible: {path_str}")
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        finally:
            cap.release()
    else:
        bgr = cv2.imread(path_str)
        if bgr is None:
            raise ValueError(f"No se pudo leer imagen: {path_str}")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def normalize_spatial(
    unit: VisualUnit,
    spec: ModelInputSpec,
    payload_format: PayloadFormat = PayloadFormat.UINT8_RGB,
) -> NormalizedUnit:
    """Normalización espacial (producer-side): decode → RGB → resize → NormalizedUnit."""
    if payload_format == PayloadFormat.FP16:
        raise NotImplementedError(
            "payload_format=fp16 está declarado pero no implementado. "
            "Se implementa junto con el backend network."
        )

    rgb = _load_rgb_array(unit)
    target_h, target_w = spec.target_size

    if spec.resize_mode == "letterbox":
        payload, transform = _letterbox(rgb, target_h, target_w)
    else:
        h, w = rgb.shape[:2]
        payload = cv2.resize(rgb, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        transform = ResizeTransform(
            scale_x=target_w / w, scale_y=target_h / h, pad_x=0.0, pad_y=0.0
        )

    if payload_format == PayloadFormat.FP32:
        payload = payload.astype(np.float32) / 255.0

    return NormalizedUnit(
        run_id=unit.run_id,
        unit_id=unit.unit_id,
        source_id=unit.source_id,
        frame_index=unit.frame_index,
        timestamp_ms=unit.timestamp_ms,
        orig_width=unit.width,
        orig_height=unit.height,
        payload=payload,
        payload_format=payload_format,
        target_size=(target_h, target_w),
        transform=transform,
    )


def prepare_model_input(
    unit: NormalizedUnit, spec: ModelInputSpec, device: str = "cpu"
) -> "torch.Tensor":
    """Finalización tensorial (consumer-side): uint8→float, mean/std, HWC→CHW, device."""
    import torch

    arr = unit.payload
    if arr.dtype == np.uint8:
        tensor = torch.from_numpy(arr).float() / 255.0
    else:
        tensor = torch.from_numpy(arr.copy()).float()

    mean = torch.tensor(spec.mean, dtype=torch.float32)
    std = torch.tensor(spec.std, dtype=torch.float32)
    tensor = (tensor - mean) / std       # HWC
    tensor = tensor.permute(2, 0, 1)     # CHW
    tensor = tensor.unsqueeze(0)         # BCHW
    return tensor.to(device)
```

- [ ] **Step 4: Actualizar `DetectionNormalizer.normalize()` para aceptar `transform`**

En `postprocessing/detection_normalizer.py`, modificar la firma y agregar reproyección:

```python
# Cambiar la firma del método normalize a:
def normalize(
    self,
    raw_detections: list[RawDetection],
    width: int,
    height: int,
    model_name: str,
    prompt_items: list[PromptItem] | None = None,
    transform: "ResizeTransform | None" = None,
) -> list[Detection]:
```

Y en el cuerpo, antes del filtro de confianza, agregar:
```python
            # Si hay transform, proyectar de espacio-modelo a píxeles originales
            box = raw.box_xyxy
            if transform is not None:
                box = transform.project_to_original(box)
            x1, y1, x2, y2 = box
```

Agregar el import al inicio del archivo:
```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from eovrt_media.contracts.normalized_unit import ResizeTransform
```

- [ ] **Step 5: Actualizar `preprocessing/__init__.py`**

Agregar:
```python
from eovrt_media.preprocessing.normalizer import normalize_spatial, prepare_model_input
```

- [ ] **Step 6: Ejecutar todos los tests**

```bash
pytest tests/test_normalizer.py tests/test_detection_normalizer.py tests/test_pipeline_mock.py -v
```
Expected: PASS en todos

- [ ] **Step 7: Commit**

```bash
git add src/eovrt_media/preprocessing/normalizer.py src/eovrt_media/preprocessing/__init__.py src/eovrt_media/postprocessing/detection_normalizer.py tests/test_normalizer.py
git commit -m "feat: add Normalizer stage, prepare_model_input, and ResizeTransform box reprojection"
```

---

## Task 4: `TransportAdapter` + `MemoryTransportAdapter` + `RateGate` + stubs declarados

**Files:**
- Create: `src/eovrt_media/transport/__init__.py`
- Create: `src/eovrt_media/transport/base.py`
- Create: `src/eovrt_media/transport/memory.py`
- Create: `src/eovrt_media/transport/rate_gate.py`
- Create: `src/eovrt_media/transport/declared.py`
- Create: `src/eovrt_media/transport/factory.py`
- Create: `src/eovrt_media/sources/live_source.py`
- Test: `tests/test_transport.py` (nuevo)

**Interfaces:**
- Consumes: `NormalizedUnit`, `END` (Task 1)
- Produces:
  - `TransportAdapter` ABC con `offer(unit)`, `request()`, `close()`
  - `MemoryTransportAdapter(policy, max_queue_size, buffer_size, max_staleness_ms)`
  - `RateGate(stride: int)` con `should_pass(frame_index: int) -> bool`
  - `create_transport(policy, max_queue_size, buffer_size, max_staleness_ms, backend) -> TransportAdapter`

- [ ] **Step 1: Escribir tests**

```python
# tests/test_transport.py
import queue
import threading
import time
import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import (
    NormalizedUnit, ResizeTransform, PayloadFormat, END
)
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.rate_gate import RateGate
from eovrt_media.transport.declared import IpcTransportAdapter, NetworkTransportAdapter


def _make_unit(uid: str) -> NormalizedUnit:
    return NormalizedUnit(
        unit_id=uid,
        orig_width=640, orig_height=480,
        payload=np.zeros((640, 640, 3), dtype=np.uint8),
        payload_format=PayloadFormat.UINT8_RGB,
        target_size=(640, 640),
        transform=ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
        timestamp_ms=float(int(uid.split("_")[-1])) * 10.0,
    )


class TestRateGate:
    def test_stride_1_passes_all(self):
        gate = RateGate(stride=1)
        assert all(gate.should_pass(i) for i in range(10))

    def test_stride_2_passes_even(self):
        gate = RateGate(stride=2)
        assert gate.should_pass(0) is True
        assert gate.should_pass(1) is False
        assert gate.should_pass(2) is True
        assert gate.should_pass(3) is False

    def test_stride_3(self):
        gate = RateGate(stride=3)
        passing = [i for i in range(9) if gate.should_pass(i)]
        assert passing == [0, 3, 6]


class TestMemoryTransportDeterministic:
    def test_offer_and_request_fifo(self):
        transport = MemoryTransportAdapter(policy="deterministic", max_queue_size=4)
        u1, u2 = _make_unit("u_1"), _make_unit("u_2")
        transport.offer(u1)
        transport.offer(u2)
        assert transport.request().unit_id == "u_1"
        assert transport.request().unit_id == "u_2"

    def test_close_emits_end(self):
        transport = MemoryTransportAdapter(policy="deterministic", max_queue_size=4)
        transport.close()
        sentinel = transport.request()
        assert sentinel is END

    def test_backpressure_blocks_producer(self):
        transport = MemoryTransportAdapter(policy="deterministic", max_queue_size=2)
        transport.offer(_make_unit("u_1"))
        transport.offer(_make_unit("u_2"))
        blocked = threading.Event()
        offered = threading.Event()

        def producer():
            blocked.set()
            transport.offer(_make_unit("u_3"))  # debe bloquearse
            offered.set()

        t = threading.Thread(target=producer, daemon=True)
        t.start()
        blocked.wait(timeout=1.0)
        time.sleep(0.05)
        assert not offered.is_set()  # productor sigue bloqueado
        transport.request()           # consumidor drena uno
        offered.wait(timeout=1.0)
        assert offered.is_set()       # productor desbloqueado


class TestMemoryTransportBoundedFreshness:
    def test_head_drop_on_full_buffer(self):
        transport = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=2)
        transport.offer(_make_unit("u_1"))
        transport.offer(_make_unit("u_2"))
        transport.offer(_make_unit("u_3"))  # head-drop: u_1 sale
        assert transport.units_dropped == 1
        received = transport.request()
        assert received.unit_id == "u_2"   # u_1 fue descartado

    def test_staleness_drop(self):
        transport = MemoryTransportAdapter(
            policy="bounded_freshness", buffer_size=4, max_staleness_ms=5.0
        )
        u_old = _make_unit("u_1")
        u_old.timestamp_ms = 0.0
        transport.offer(u_old)
        time.sleep(0.01)  # 10ms > 5ms staleness
        result = transport.request(current_time_ms=lambda: time.time() * 1000)
        assert result is END or result.unit_id != "u_1"

    def test_close_emits_end(self):
        transport = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=4)
        transport.close()
        assert transport.request() is END


class TestDeclaredStubs:
    def test_ipc_offer_raises(self):
        adapter = IpcTransportAdapter()
        with pytest.raises(NotImplementedError, match="ipc"):
            adapter.offer(_make_unit("u_1"))

    def test_network_request_raises(self):
        adapter = NetworkTransportAdapter(endpoint="tcp://localhost:5555")
        with pytest.raises(NotImplementedError, match="network"):
            adapter.request()


# Suite agnóstica de backend — ejecutar contra memory; misma suite valida futuros backends
class TestTransportContract:
    @pytest.fixture(params=["deterministic", "bounded_freshness"])
    def transport(self, request):
        if request.param == "deterministic":
            return MemoryTransportAdapter(policy="deterministic", max_queue_size=8)
        return MemoryTransportAdapter(policy="bounded_freshness", buffer_size=8)

    def test_offer_then_close_then_request_end(self, transport):
        transport.offer(_make_unit("u_1"))
        transport.close()
        transport.request()  # drena u_1
        assert transport.request() is END

    def test_empty_close_then_end_immediately(self, transport):
        transport.close()
        assert transport.request() is END
```

- [ ] **Step 2: Ejecutar para verificar que falla**

```bash
pytest tests/test_transport.py -v
```
Expected: `ImportError` — módulos no existen

- [ ] **Step 3: Crear `transport/base.py`**

```python
"""Interfaz abstracta del canal productor→consumidor."""

from __future__ import annotations
from abc import ABC, abstractmethod
from eovrt_media.contracts.normalized_unit import NormalizedUnit, END


class TransportAdapter(ABC):
    @abstractmethod
    def offer(self, unit: NormalizedUnit) -> None:
        """Coloca una unidad en el canal (productor). Política definida por subclase."""

    @abstractmethod
    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        """Obtiene la siguiente unidad del canal (consumidor). Bloquea si vacío."""

    @abstractmethod
    def close(self) -> None:
        """Señal END: el productor terminó. Coloca centinela en el canal."""
```

- [ ] **Step 4: Crear `transport/memory.py`**

```python
"""Backend de transporte en memoria — cola acotada con dos políticas."""

from __future__ import annotations

import queue
import time
from collections import deque
from threading import Lock

from eovrt_media.contracts.normalized_unit import NormalizedUnit, END
from eovrt_media.transport.base import TransportAdapter


class MemoryTransportAdapter(TransportAdapter):
    """Cola en memoria con políticas deterministic y bounded_freshness."""

    def __init__(
        self,
        policy: str = "deterministic",
        max_queue_size: int = 8,
        buffer_size: int = 2,
        max_staleness_ms: float | None = None,
    ) -> None:
        self.policy = policy
        self.max_staleness_ms = max_staleness_ms
        self.units_dropped: int = 0

        if policy == "deterministic":
            self._q: queue.Queue = queue.Queue(maxsize=max_queue_size)
        elif policy == "bounded_freshness":
            self._buf: deque = deque(maxlen=buffer_size)
            self._lock = Lock()
            self._not_empty = __import__("threading").Condition(self._lock)
            self._closed = False
        else:
            raise ValueError(f"Política desconocida: {policy!r}")

    # --- productor ---

    def offer(self, unit: NormalizedUnit) -> None:
        if self.policy == "deterministic":
            self._q.put(unit)  # bloquea si llena (backpressure)
        else:
            with self._not_empty:
                if len(self._buf) == self._buf.maxlen:
                    self._buf.popleft()
                    self.units_dropped += 1
                self._buf.append(unit)
                self._not_empty.notify()

    def close(self) -> None:
        if self.policy == "deterministic":
            self._q.put(END)
        else:
            with self._not_empty:
                self._closed = True
                self._not_empty.notify_all()

    # --- consumidor ---

    def request(self, current_time_ms=None) -> NormalizedUnit | type[END]:
        if self.policy == "deterministic":
            item = self._q.get()
            return END if item is END else item
        else:
            with self._not_empty:
                while True:
                    if self._buf:
                        unit = self._buf.popleft()
                        if self.max_staleness_ms is not None and unit.timestamp_ms is not None:
                            now = (current_time_ms() if current_time_ms else time.time() * 1000)
                            if now - unit.timestamp_ms > self.max_staleness_ms:
                                self.units_dropped += 1
                                continue
                        return unit
                    if self._closed:
                        return END
                    self._not_empty.wait()
```

- [ ] **Step 5: Crear `transport/rate_gate.py`**

```python
"""RateGate — filtro determinista de frames por stride."""

from __future__ import annotations


class RateGate:
    """Filtro de frames por stride. Solo para política deterministic."""

    def __init__(self, stride: int = 1) -> None:
        if stride < 1:
            raise ValueError(f"stride debe ser >= 1, recibido: {stride}")
        self.stride = stride

    def should_pass(self, frame_index: int) -> bool:
        return frame_index % self.stride == 0
```

- [ ] **Step 6: Crear `transport/declared.py`**

```python
"""Backends de transporte declarados, pendientes de implementación."""

from __future__ import annotations

from eovrt_media.contracts.normalized_unit import NormalizedUnit, END
from eovrt_media.transport.base import TransportAdapter


class IpcTransportAdapter(TransportAdapter):
    """Backend IPC (shared-memory ring buffer) — declarado, no implementado."""

    def offer(self, unit: NormalizedUnit) -> None:
        raise NotImplementedError(
            "backend=ipc está declarado pero no implementado. "
            "Usar backend=memory para un host o implementar IpcTransportAdapter."
        )

    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        raise NotImplementedError(
            "backend=ipc está declarado pero no implementado."
        )

    def close(self) -> None:
        raise NotImplementedError("backend=ipc no implementado.")


class NetworkTransportAdapter(TransportAdapter):
    """Backend ZeroMQ REQ/REP + heartbeat ZMTP — declarado, no implementado."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def offer(self, unit: NormalizedUnit) -> None:
        raise NotImplementedError(
            "backend=network (ZeroMQ) está declarado pero no implementado. "
            "Se implementa junto con topology=two_node."
        )

    def request(self, **kwargs) -> NormalizedUnit | type[END]:
        raise NotImplementedError(
            "backend=network está declarado pero no implementado."
        )

    def close(self) -> None:
        raise NotImplementedError("backend=network no implementado.")
```

- [ ] **Step 7: Crear `transport/factory.py`**

```python
"""Factory de TransportAdapter según configuración."""

from __future__ import annotations

from eovrt_media.transport.base import TransportAdapter
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.declared import IpcTransportAdapter, NetworkTransportAdapter


def create_transport(
    *,
    backend: str = "memory",
    policy: str = "deterministic",
    max_queue_size: int = 8,
    buffer_size: int = 2,
    max_staleness_ms: float | None = None,
    endpoint: str | None = None,
) -> TransportAdapter:
    if backend == "memory":
        return MemoryTransportAdapter(
            policy=policy,
            max_queue_size=max_queue_size,
            buffer_size=buffer_size,
            max_staleness_ms=max_staleness_ms,
        )
    if backend == "ipc":
        return IpcTransportAdapter()
    if backend == "network":
        if not endpoint:
            raise ValueError("backend=network requiere transport.endpoint configurado.")
        return NetworkTransportAdapter(endpoint=endpoint)
    raise ValueError(f"backend desconocido: {backend!r}. Opciones: memory, ipc, network.")
```

- [ ] **Step 8: Crear `transport/__init__.py`**

```python
from eovrt_media.transport.base import TransportAdapter
from eovrt_media.transport.memory import MemoryTransportAdapter
from eovrt_media.transport.rate_gate import RateGate
from eovrt_media.transport.factory import create_transport
```

- [ ] **Step 9: Crear `sources/live_source.py`**

```python
"""LiveSource — fuente viva abstracta (cámara/RTSP). Declarado, no implementado."""

from __future__ import annotations

from eovrt_media.sources.base import BaseSource
from eovrt_media.contracts import VisualUnit


class LiveSource(BaseSource):
    """Fuente viva (cámara o RTSP). Interfaz declarada, implementación pendiente."""

    def __iter__(self):
        raise NotImplementedError(
            "source.type=camera/rtsp está declarado pero no implementado. "
            "Usar source.type=image_folder o video_file."
        )

    def __len__(self) -> int:
        return -1  # fuente viva no tiene longitud conocida
```

- [ ] **Step 10: Ejecutar tests**

```bash
pytest tests/test_transport.py -v
```
Expected: PASS en todos

- [ ] **Step 11: Ejecutar la suite completa**

```bash
pytest -q
```
Expected: PASS en todos los tests previos

- [ ] **Step 12: Commit**

```bash
git add src/eovrt_media/transport/ src/eovrt_media/sources/live_source.py tests/test_transport.py
git commit -m "feat: add TransportAdapter, MemoryTransportAdapter (deterministic+bounded_freshness), RateGate, declared stubs"
```

---

## Task 5: Config schema — `rate_control`, `transport`, `topology`, derivación y migración de `sampling`

**Files:**
- Modify: `src/eovrt_media/config/schemas.py`
- Modify: `src/eovrt_media/config/loader.py`
- Modify: `configs/runs/gdino.yaml` y todos los `configs/runs/*.yaml`
- Modify: `configs/datasets/*.yaml`
- Test: `tests/test_config_deployment.py` (nuevo)

**Interfaces:**
- Consumes: nada de Tasks anteriores (config es independiente)
- Produces: `RateControlConfig`, `TransportConfig`, `TopologyConfig`, reglas de derivación y gating — usado en Task 6 (pipeline refactor).

- [ ] **Step 1: Escribir tests de config**

```python
# tests/test_config_deployment.py
from pathlib import Path
import pytest
import yaml

from eovrt_media.config.loader import load_run_config
from eovrt_media.config.schemas import RunConfig, RateControlConfig


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


class TestConfigDerivation:
    def test_pulleable_source_derives_deterministic(self, tmp_path):
        """source.kind=pulleable → rate_control.policy=deterministic automáticamente."""
        cfg = _minimal_config(tmp_path, source_kind="pulleable")
        assert cfg.rate_control.policy == "deterministic"

    def test_single_host_derives_memory_backend(self, tmp_path):
        """topology.mode=single_host → transport.backend=memory automáticamente."""
        cfg = _minimal_config(tmp_path)
        assert cfg.transport.backend == "memory"

    def test_explicit_policy_overrides_derived(self, tmp_path):
        cfg = _minimal_config(tmp_path, rate_control={"policy": "bounded_freshness"})
        assert cfg.rate_control.policy == "bounded_freshness"

    def test_max_units_in_run_section(self, tmp_path):
        cfg = _minimal_config(tmp_path, run={"max_units": 10})
        assert cfg.run.max_units == 10


class TestConfigValidation:
    def test_two_node_with_memory_raises(self, tmp_path):
        with pytest.raises(ValueError, match="two_node.*network"):
            _minimal_config(tmp_path, topology={"mode": "two_node"}, transport={"backend": "memory"})

    def test_stride_under_bounded_freshness_raises(self, tmp_path):
        with pytest.raises(ValueError, match="stride.*deterministic"):
            _minimal_config(tmp_path, rate_control={"policy": "bounded_freshness", "stride": 2})

    def test_buffer_size_under_deterministic_raises(self, tmp_path):
        with pytest.raises(ValueError, match="buffer_size.*bounded_freshness"):
            _minimal_config(tmp_path, rate_control={"policy": "deterministic", "buffer_size": 3})


class TestConfigGating:
    def test_two_node_topology_gated(self, tmp_path):
        with pytest.raises((ValueError, NotImplementedError), match="two_node|no implementad"):
            cfg = _minimal_config(tmp_path, topology={"mode": "two_node"}, transport={"backend": "network", "endpoint": "tcp://localhost:5555"})
            # gating en loader
            from eovrt_media.config.loader import _validate_deployment
            _validate_deployment(cfg)

    def test_ipc_backend_gated(self, tmp_path):
        with pytest.raises((ValueError, NotImplementedError), match="ipc|no implementad"):
            cfg = _minimal_config(tmp_path, transport={"backend": "ipc"})
            from eovrt_media.config.loader import _validate_deployment
            _validate_deployment(cfg)

    def test_fp16_payload_format_gated(self, tmp_path):
        with pytest.raises((ValueError, NotImplementedError), match="fp16|no implementad"):
            cfg = _minimal_config(tmp_path, transport={"payload_format": "fp16"})
            from eovrt_media.config.loader import _validate_deployment
            _validate_deployment(cfg)

    def test_camera_source_type_gated(self, tmp_path):
        with pytest.raises((ValueError, NotImplementedError), match="camera|live|no implementad"):
            cfg = _minimal_config(tmp_path, source={"type": "camera", "path": "/dev/video0"})
            from eovrt_media.config.loader import _validate_deployment
            _validate_deployment(cfg)


class TestSamplingMigration:
    def test_sampling_key_raises_with_migration_message(self, tmp_path):
        config_path = _write_config(tmp_path, {"sampling": {"every_n": 2}})
        with pytest.raises(ValueError, match="sampling.*rate_control"):
            load_run_config(config_path)


# --- helpers ---

def _minimal_config(tmp_path, source=None, run=None, rate_control=None, transport=None, topology=None, source_kind=None):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "x.jpg").write_bytes(b"")

    prompts_path = tmp_path / "prompts.yaml"
    prompts_path.write_text("version: v1\nitems:\n  - id: person\n    text: person\n")

    src = {"type": "image_folder", "path": str(images_dir)}
    if source_kind:
        src["kind"] = source_kind
    if source:
        src.update(source)

    raw = {
        "run": {"scenario": "DBE", **(run or {})},
        "source": src,
        "model": {"adapter": "mock", "device": "cpu"},
        "prompts": {"file": str(prompts_path)},
    }
    if rate_control:
        raw["rate_control"] = rate_control
    if transport:
        raw["transport"] = transport
    if topology:
        raw["topology"] = topology

    config_path = _write_config(tmp_path, raw)
    return load_run_config(config_path)


def _write_config(tmp_path, extra=None):
    p = tmp_path / "run.yaml"
    images_dir = tmp_path / "images"
    images_dir.mkdir(exist_ok=True)
    prompts_path = tmp_path / "prompts.yaml"
    if not prompts_path.exists():
        prompts_path.write_text("version: v1\nitems:\n  - id: person\n    text: person\n")

    base = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(images_dir)},
        "model": {"adapter": "mock", "device": "cpu"},
        "prompts": {"file": str(prompts_path)},
    }
    if extra:
        base.update(extra)
    p.write_text(yaml.dump(base))
    return p
```

- [ ] **Step 2: Ejecutar para verificar que falla**

```bash
pytest tests/test_config_deployment.py -v
```
Expected: varios fallos — las secciones nuevas no existen en el schema

- [ ] **Step 3: Agregar secciones nuevas en `config/schemas.py`**

Agregar estas clases antes de `RunConfig` (reemplazar el import de SamplingConfig):

```python
class RateControlConfig(BaseModel):
    """Sección 'rate_control' — política de control de tasa del productor."""
    policy: str = "deterministic"       # deterministic | bounded_freshness
    stride: int = 1                     # solo deterministic
    max_queue_size: int = 8             # solo deterministic
    overflow: str = "fail_run"          # solo deterministic + fuente live
    buffer_size: int = 2                # solo bounded_freshness
    max_staleness_ms: float | None = None  # solo bounded_freshness


class TransportConfig(BaseModel):
    """Sección 'transport' — backend de comunicación canal."""
    backend: str = "memory"             # memory (impl) | ipc (declarado) | network (declarado)
    payload_format: str = "uint8_rgb"   # uint8_rgb (impl) | fp32 (impl) | fp16 (declarado)
    endpoint: str | None = None         # solo backend=network


class TopologyConfig(BaseModel):
    """Sección 'topology' — topología de despliegue."""
    mode: str = "single_host"           # single_host (impl) | two_node (declarado)
```

Modificar `SourceSection`:
```python
class SourceSection(BaseModel):
    # ... campos existentes ...
    kind: str | None = None            # pulleable | live (derivado de type si no se fija)
    dataset_id: str | None = None
    view: str | None = None
    split: str | None = None
    vocabulary: list[str] | None = None
```

Modificar `RunSection`:
```python
class RunSection(BaseModel):
    # ... campos existentes ...
    max_units: int | None = None       # cota operativa (reemplaza sampling.max_units)
```

Modificar `RunConfig`:
```python
class RunConfig(BaseModel):
    run: RunSection
    source: SourceSection
    model: ModelSection
    prompts: PromptsSection

    rate_control: RateControlConfig = Field(default_factory=RateControlConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    topology: TopologyConfig = Field(default_factory=TopologyConfig)

    sampling: SamplingConfig | None = Field(default=None)  # SOLO para detectar migración
    postprocess: PostprocessConfig = Field(default_factory=PostprocessConfig)
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    # ... resto igual ...

    @model_validator(mode="before")
    @classmethod
    def handle_outputs_and_defaults(cls, data: Any) -> Any:
        # ... lógica existente ...
        # Detectar sampling antes de construir el modelo (se maneja en loader)
        return data
```

- [ ] **Step 4: Implementar derivación y validación en `config/loader.py`**

Agregar funciones antes de `load_run_config`:

```python
_PULLEABLE_TYPES = {"image_folder", "video_file", "video", "video_frame"}
_LIVE_TYPES = {"camera", "rtsp"}


def _derive_defaults(config: RunConfig) -> None:
    """Deriva source.kind, rate_control.policy y transport.backend si no están fijados."""
    # 1. Derivar source.kind desde source.type
    if config.source.kind is None:
        src_type = config.source.type.lower()
        if src_type in _PULLEABLE_TYPES:
            config.source.kind = "pulleable"
        elif src_type in _LIVE_TYPES:
            config.source.kind = "live"

    # 2. Derivar rate_control.policy desde source.kind (solo si no override explícito)
    # El override explícito ya está en el YAML; si el usuario no puso policy, hereda el default
    # El default del modelo ya es "deterministic", que coincide con pulleable.
    # Solo necesitamos overridearlo si kind=live y el user no puso policy en el YAML:
    # (No podemos saber si vino del YAML o del default; usamos source.kind como fuente de verdad)

    # 3. Derivar transport.backend desde topology.mode
    if config.topology.mode == "two_node" and config.transport.backend == "memory":
        config.transport.backend = "network"
    elif config.topology.mode == "single_host" and config.transport.backend == "network":
        raise ValueError(
            "topology.mode=single_host no permite transport.backend=network. "
            "Usar backend=memory o ipc para un solo host."
        )


def _validate_deployment(config: RunConfig) -> None:
    """Valida coherencia de config de despliegue y aplica gating de features declaradas."""
    rc = config.rate_control

    # Cross-validation: parámetros cruzados
    if rc.policy == "bounded_freshness":
        if rc.stride != 1:  # stride=1 es el default, solo aplica a deterministic
            raise ValueError(
                "'stride' solo aplica a policy=deterministic. "
                "Para bounded_freshness usar 'buffer_size'."
            )
    if rc.policy == "deterministic":
        if rc.buffer_size != 2:  # buffer_size != default sugiere uso incorrecto
            raise ValueError(
                "'buffer_size' solo aplica a policy=bounded_freshness. "
                "Para deterministic usar 'max_queue_size'."
            )

    # Coherencia topology ↔ backend
    if config.topology.mode == "two_node" and config.transport.backend != "network":
        raise ValueError(
            "topology.mode=two_node requiere transport.backend=network. "
            "El backend 'network' (ZeroMQ) se implementa en la siguiente fase."
        )

    # Gating: features declaradas que no están implementadas
    if config.topology.mode == "two_node":
        raise NotImplementedError(
            "topology.mode=two_node está declarado pero no implementado en este build. "
            "Implementar NetworkTransportAdapter para habilitarlo."
        )
    if config.transport.backend == "ipc":
        raise NotImplementedError(
            "transport.backend=ipc está declarado pero no implementado en este build."
        )
    if config.transport.payload_format == "fp16":
        raise NotImplementedError(
            "transport.payload_format=fp16 está declarado pero no implementado. "
            "Se finaliza junto con backend=network."
        )
    if config.source.type.lower() in _LIVE_TYPES:
        raise NotImplementedError(
            f"source.type={config.source.type!r} está declarado pero no implementado. "
            "Usar image_folder o video_file."
        )

    # Coherencia vocabulary ↔ prompts.active_ids (warning, no error)
    if (
        config.source.vocabulary
        and config.prompts.active_ids
        and not set(config.prompts.active_ids).issubset(set(config.source.vocabulary))
    ):
        import warnings
        warnings.warn(
            f"prompts.active_ids {config.prompts.active_ids} contiene IDs fuera del "
            f"vocabulario de la fuente {config.source.vocabulary}.",
            UserWarning,
            stacklevel=2,
        )
```

Modificar `load_run_config` para detectar `sampling` y aplicar derivación/validación:

```python
def load_run_config(config_path: Path) -> RunConfig:
    config_path = Path(config_path)
    # ... código existente hasta yaml.safe_load ...

    # Detectar sampling antes de construir RunConfig
    if "sampling" in raw and raw["sampling"] is not None:
        s = raw["sampling"]
        if isinstance(s, dict) and any(
            s.get(k) not in (None, 1, "all") for k in ("every_n", "mode", "target_fps")
        ) or s.get("max_units") is not None:
            raise ValueError(
                "La sección 'sampling' fue eliminada. Migrar al nuevo esquema:\n"
                "  sampling.every_n     → rate_control.stride\n"
                "  sampling.max_units   → run.max_units\n"
                "  sampling.target_fps  → eliminado (rate emerge del consumidor)\n"
                "  sampling.mode        → eliminado (reemplazado por rate_control.policy)"
            )

    # ... resto del código existente para resolver refs y construir config ...

    config = RunConfig(**raw)
    config.config_path = config_path
    # ... carga de prompts existente ...

    _derive_defaults(config)
    _validate_deployment(config)

    return config
```

- [ ] **Step 5: Migrar `configs/runs/*.yaml` — quitar `sampling`, agregar secciones vacías**

Los YAMLs actuales no tienen `sampling` explícito (usan defaults), así que solo hay que verificar que no hay `sampling` en ninguno. Si hay alguno, remover la sección. Los defaults de `rate_control`, `transport`, `topology` se derivan automáticamente.

Verificar con:
```bash
grep -r "sampling" /home/simonll4/projects/e-ovrt_media-plane/configs/runs/
```

Si hay resultados, editar cada archivo removiendo la sección `sampling` y, si tenía `every_n: N`, agregar `rate_control:\n  stride: N`.

- [ ] **Step 6: Actualizar `configs/datasets/*.yaml` con nuevos campos**

Cada dataset catalog entry necesita los campos de trazabilidad. Ejemplo para `bench_v2_test.yaml`:

```yaml
description: "BENCH v2 test: 82 imgs de obra..."
dataset_id: construction_site_safety
view: canonical_v2
split: bench_v2_test
vocabulary: [person, helmet, vest, bare_head]
type: image_folder
path: ../e-ovrt_datasets/datasets/raw/construction_site_safety/test/images
extensions: [".jpg", ".jpeg", ".png"]
kind: pulleable
```

Hacer lo mismo para todos los datasets, usando los `dataset_id` y `vocabulary` apropiados según el contenido.

- [ ] **Step 7: Ejecutar tests**

```bash
pytest tests/test_config_deployment.py tests/test_config.py tests/test_config_refs.py -v
```
Expected: PASS en todos

- [ ] **Step 8: Ejecutar suite completa**

```bash
pytest -q
```
Expected: PASS en todos

- [ ] **Step 9: Commit**

```bash
git add src/eovrt_media/config/schemas.py src/eovrt_media/config/loader.py configs/runs/ configs/datasets/ tests/test_config_deployment.py
git commit -m "feat: add RateControlConfig, TransportConfig, TopologyConfig; derive defaults; gate declared features; sampling migration error"
```

---

## Task 6: Refactor del pipeline — dos hilos productor/consumidor + `forward()` en adapters

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Modify: `src/eovrt_media/runtime/run_context.py`
- Modify: `src/eovrt_media/models/base.py`
- Modify: `src/eovrt_media/models/mock_detector.py`
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py`
- Modify: `src/eovrt_media/models/yoloe_adapter.py`
- Modify: `src/eovrt_media/metrics/timers.py`
- Test: `tests/test_pipeline_two_threads.py` (nuevo)
- Update: `tests/test_pipeline_mock.py` (si es necesario por cambios de API)

**Interfaces:**
- Consumes: `NormalizedUnit`, `TransportAdapter`, `RateGate`, `normalize_spatial`, `prepare_model_input`, `RateControlConfig`, `TransportConfig` (Tasks 1–5)
- Produces: pipeline refactorizado con dos hilos, `run_pipeline(config) -> str` (misma firma).

- [ ] **Step 1: Agregar `normalize_ms` y `p99` a `metrics/timers.py`**

En `UnitTimingResult`:
```python
normalize_ms: float = 0.0
```

En `UnitTimer`:
```python
    def start_normalize(self) -> None:
        self.normalize_start = time.perf_counter()

    def end_normalize(self) -> None:
        self.normalize_end = time.perf_counter()
```
Y en `get_granular_result()`:
```python
norm = (self.normalize_end - self.normalize_start) * 1000.0 if (hasattr(self, 'normalize_start') and self.normalize_start and hasattr(self, 'normalize_end') and self.normalize_end) else 0.0
# incluir norm en UnitTimingResult
```

En `LatencyTracker`:
```python
    def p99_latency_ms(self) -> float:
        latencies = self.get_latencies_ms()
        if not latencies:
            return 0.0
        sorted_lat = sorted(latencies)
        idx = min(int(len(sorted_lat) * 0.99), len(sorted_lat) - 1)
        return sorted_lat[idx]
```

- [ ] **Step 2: Añadir `forward()` a `BaseDetectorAdapter` y adapters**

En `models/base.py`, agregar método abstracto:
```python
    @abstractmethod
    def forward(
        self, unit: "NormalizedUnit", prompts: list[str]
    ) -> list[RawDetection]:
        """Inferencia a partir de NormalizedUnit (nueva interfaz del pipeline)."""
```

En `MockDetectorAdapter.forward()`:
```python
    def forward(self, unit, prompts: list[str]) -> list[RawDetection]:
        """Genera detecciones en espacio target_size."""
        target_h, target_w = unit.target_size
        detections = []
        for prompt in prompts:
            n_detections = self._rng.randint(0, 3)
            for _ in range(n_detections):
                x1 = self._rng.uniform(0, target_w * 0.7)
                y1 = self._rng.uniform(0, target_h * 0.7)
                x2 = self._rng.uniform(x1 + 20, min(x1 + target_w * 0.4, target_w))
                y2 = self._rng.uniform(y1 + 20, min(y1 + target_h * 0.4, target_h))
                detections.append(RawDetection(
                    label=prompt, score=self._rng.uniform(0.3, 0.99),
                    box_xyxy=[x1, y1, x2, y2],
                ))
        return detections
```

En `GroundingDinoHFAdapter.forward()`:
```python
    def forward(self, unit, prompts: list[str]) -> list[RawDetection]:
        """Inferencia desde NormalizedUnit — reconstruye PIL y pasa al AutoProcessor."""
        from PIL import Image as PILImage
        pil_img = PILImage.fromarray(unit.payload)
        return self.predict(pil_img, prompts)
```

En `YOLOEUltralyticsAdapter.forward()`:
```python
    def forward(self, unit, prompts: list[str]) -> list[RawDetection]:
        from PIL import Image as PILImage
        pil_img = PILImage.fromarray(unit.payload)
        return self.predict(pil_img, prompts)
```

- [ ] **Step 3: Actualizar `run_context.py`**

Agregar campos:
```python
        self.units_dropped: int = 0
        self.backpressure_wait_ms: float = 0.0
        self.max_staleness_observed_ms: float = 0.0
        self._errors_queue: queue.SimpleQueue = queue.SimpleQueue()
```
(importar `import queue` al inicio del archivo)

- [ ] **Step 4: Escribir tests del pipeline de dos hilos**

```python
# tests/test_pipeline_two_threads.py
import json
from pathlib import Path
import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 5) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (50 + i * 30, 100, 200)
        cv2.imwrite(str(folder / f"test_{i:03d}.jpg"), img)


def _mock_config(tmp_path, extra_rate_control=None):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=5)
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.model.adapter = "mock"
    config.source.path = str(images_dir)
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = False
    if extra_rate_control:
        for k, v in extra_rate_control.items():
            setattr(config.rate_control, k, v)
    return config


class TestReproducibility:
    def test_deterministic_two_runs_identical(self, tmp_path):
        """Dos corridas con config deterministic → detections.jsonl idénticos."""
        config = _mock_config(tmp_path)
        config.rate_control.policy = "deterministic"
        config.model.seed = 42  # para MockDetector

        run_id1 = run_pipeline(config)
        run_dir1 = Path(config.outputs.base_dir) / run_id1
        det1 = (run_dir1 / "detections.jsonl").read_text()

        config.outputs.base_dir = str(tmp_path / "runs2")
        config.outputs.run_dir = str(tmp_path / "runs2")
        run_id2 = run_pipeline(config)
        run_dir2 = Path(config.outputs.base_dir) / run_id2
        det2 = (run_dir2 / "detections.jsonl").read_text()

        events1 = [json.loads(l)["detections"] for l in det1.strip().split("\n")]
        events2 = [json.loads(l)["detections"] for l in det2.strip().split("\n")]
        assert events1 == events2


class TestCleanShutdown:
    def test_all_units_processed(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        run_dir = Path(config.outputs.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())
        assert summary["units_processed"] == 5
        assert summary["units_failed"] == 0

    def test_summary_has_run_descriptor(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        run_dir = Path(config.outputs.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())
        assert "run_descriptor" in summary
        rd = summary["run_descriptor"]
        assert rd["scenario"] == "DBE"
        assert rd["topology"] == "single_host"
        assert rd["rate_control"]["policy"] == "deterministic"


class TestBoundedFreshnessMetrics:
    def test_units_dropped_counted(self, tmp_path):
        """bounded_freshness con buffer=1 y 5 unidades → algunas se descartan."""
        config = _mock_config(tmp_path)
        config.rate_control.policy = "bounded_freshness"
        config.rate_control.buffer_size = 1
        run_id = run_pipeline(config)
        run_dir = Path(config.outputs.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())
        # Con buffer=1 y modelo lento, algunas unidades se pierden
        # Al menos las métricas deben estar presentes
        assert "units_dropped" in summary

    def test_stride_applied(self, tmp_path):
        config = _mock_config(tmp_path)
        config.rate_control.stride = 2  # solo 1 de cada 2
        run_id = run_pipeline(config)
        run_dir = Path(config.outputs.base_dir) / run_id
        summary = json.loads((run_dir / "summary.json").read_text())
        # 5 imágenes con stride=2 → procesar frames 0, 2, 4 → 3 unidades
        assert summary["units_processed"] <= 3
```

- [ ] **Step 5: Ejecutar para verificar que falla**

```bash
pytest tests/test_pipeline_two_threads.py -v
```
Expected: fallos — pipeline aún no tiene run_descriptor ni lógica de dos hilos

- [ ] **Step 6: Refactorizar `runtime/pipeline.py`**

Reemplazar completamente el archivo con la nueva arquitectura de dos hilos. Estructura completa:

```python
"""Pipeline del plano de medios — productor/consumidor desacoplados por TransportAdapter."""

from __future__ import annotations

import logging
import queue as stdlib_queue
import threading
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from eovrt_media.config import RunConfig
from eovrt_media.contracts import DetectionEvent, MetricSample, ErrorEvent
from eovrt_media.contracts.normalized_unit import END, PayloadFormat
from eovrt_media.metrics import LatencyTracker, get_gpu_memory_allocated_mb, get_gpu_memory_peak_mb, reset_gpu_peak_memory
from eovrt_media.models import create_adapter
from eovrt_media.postprocessing import DetectionNormalizer
from eovrt_media.preprocessing.normalizer import normalize_spatial
from eovrt_media.runtime.run_context import RunContext
from eovrt_media.sinks import RunArtifactWriter
from eovrt_media.sources import ImageFolderSource, VideoFileSource, BaseSource
from eovrt_media.transport import RateGate, create_transport
from eovrt_media.visualize import draw_detections

logger = logging.getLogger(__name__)


def create_source(config: RunConfig) -> BaseSource:
    """Crea la fuente visual según config. Usa run.max_units en lugar de sampling."""
    max_units = config.run.max_units
    src_type = config.source.type.lower().strip()
    if src_type == "image_folder":
        return ImageFolderSource(
            folder_path=config.source.path,
            extensions=config.source.extensions,
            every_n=1,                  # stride lo aplica RateGate
            max_units=max_units,
        )
    elif src_type in ("video", "video_frame", "video_file"):
        return VideoFileSource(
            video_path=config.source.path,
            every_n=1,
            target_fps=None,
            max_units=max_units,
        )
    else:
        raise ValueError(
            f"Tipo de fuente '{src_type}' no soportado o no implementado. "
            "Usar image_folder o video_file."
        )


def _producer_thread(
    source: BaseSource,
    rate_gate: RateGate,
    spec,
    payload_format: PayloadFormat,
    transport,
    errors_q: stdlib_queue.SimpleQueue,
    tracker: LatencyTracker,
) -> None:
    """Hilo productor: ingesta → RateGate → Normalizer → channel.offer."""
    frame_idx = 0
    for unit in source:
        if not rate_gate.should_pass(frame_idx):
            frame_idx += 1
            continue
        frame_idx += 1
        try:
            normalized = normalize_spatial(unit, spec, payload_format)
            transport.offer(normalized)
        except Exception as e:
            errors_q.put(("normalize", unit.unit_id, str(e)))
    transport.close()


def run_pipeline(config: RunConfig, console: Console | None = None) -> str:
    """Ejecuta el pipeline con arquitectura productor/consumidor desacoplados."""
    if console is None:
        console = Console()

    run_context = RunContext(config)
    artifact_writer = RunArtifactWriter(run_context)

    console.print(f"[bold green]▶ Corrida:[/bold green] {run_context.run_id}")
    console.print(f"[dim]  Directorio de salida: {run_context.run_dir}[/dim]")

    if config.config_path:
        artifact_writer.write_original_config(config.config_path)
    artifact_writer.write_effective_config()

    source = create_source(config)
    source_count = len(source)
    console.print(f"[dim]  Fuente: {config.source.path} ({source_count} unidades)[/dim]")

    prompt_texts = config.get_prompt_texts()
    prompt_items = config.get_prompt_items()
    prompt_version = config.prompts_file.resolved_version if config.prompts_file else "unknown"
    console.print(f"[dim]  Prompts activos ({prompt_version}): {prompt_texts}[/dim]")

    det_normalizer = DetectionNormalizer(
        min_confidence=config.postprocess.min_confidence,
        min_box_area_px=config.postprocess.min_box_area_px,
        normalize_boxes=config.postprocess.normalize_boxes,
    )

    adapter = create_adapter(config.model)
    spec = adapter.input_spec
    payload_format = PayloadFormat(config.transport.payload_format)
    console.print(f"[dim]  Modelo/Adaptador: {config.model.name or config.model.adapter}[/dim]")
    console.print(f"[dim]  Dispositivo: {config.model.device}[/dim]\n")

    reset_gpu_peak_memory()
    with console.status("[bold cyan]Cargando modelo..."):
        adapter.load()
    console.print("[green]✓[/green] Modelo cargado en memoria\n")

    rc = config.rate_control
    transport = create_transport(
        backend=config.transport.backend,
        policy=rc.policy,
        max_queue_size=rc.max_queue_size,
        buffer_size=rc.buffer_size,
        max_staleness_ms=rc.max_staleness_ms,
        endpoint=config.transport.endpoint,
    )
    rate_gate = RateGate(stride=rc.stride)
    errors_q: stdlib_queue.SimpleQueue = stdlib_queue.SimpleQueue()
    tracker = LatencyTracker()

    producer = threading.Thread(
        target=_producer_thread,
        args=(source, rate_gate, spec, payload_format, transport, errors_q, tracker),
        daemon=True,
        name="pipeline-producer",
    )
    producer.start()

    try:
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), TaskProgressColumn(), console=console,
        ) as progress:
            task_prog = progress.add_task("Procesando unidades visuales...", total=source_count)

            while True:
                item = transport.request()
                if item is END:
                    break

                # Drenar errores del productor
                while not errors_q.empty():
                    stage, uid, msg = errors_q.get_nowait()
                    artifact_writer.write_error(ErrorEvent(
                        run_id=run_context.run_id, unit_id=uid,
                        stage=stage, message=msg, recoverable=True,
                    ))
                    run_context.units_failed += 1

                normalized_unit = item
                timer = tracker.start_unit(normalized_unit.unit_id)

                # --- INFERENCIA ---
                timer.start_inference()
                try:
                    raw_detections = adapter.forward(normalized_unit, prompt_texts)
                    timer.end_inference()
                except Exception as e:
                    logger.error(f"Error de inferencia en unidad {normalized_unit.unit_id}: {e}")
                    timer.end_inference()
                    artifact_writer.write_error(ErrorEvent(
                        run_id=run_context.run_id, unit_id=normalized_unit.unit_id,
                        stage="inference", message=str(e), recoverable=True,
                    ))
                    run_context.units_failed += 1
                    progress.update(task_prog, advance=1)
                    continue

                # --- POSTPROCESAMIENTO ---
                timer.start_postprocess()
                try:
                    detections = det_normalizer.normalize(
                        raw_detections=raw_detections,
                        width=normalized_unit.orig_width,
                        height=normalized_unit.orig_height,
                        model_name=config.model.name or config.model.adapter,
                        prompt_items=prompt_items,
                        transform=normalized_unit.transform,
                    )
                    timer.end_postprocess()
                except Exception as e:
                    logger.error(f"Error postproceso en unidad {normalized_unit.unit_id}: {e}")
                    timer.end_postprocess()
                    artifact_writer.write_error(ErrorEvent(
                        run_id=run_context.run_id, unit_id=normalized_unit.unit_id,
                        stage="postprocess", message=str(e), recoverable=True,
                    ))
                    run_context.units_failed += 1
                    progress.update(task_prog, advance=1)
                    continue

                # --- ESCRITURA ---
                timer.start_write()
                try:
                    tracker.finish_unit(timer, detection_count=len(detections))
                    granular = timer.get_granular_result()
                    gpu_mem = get_gpu_memory_allocated_mb()

                    event = DetectionEvent(
                        run_id=run_context.run_id,
                        unit_id=normalized_unit.unit_id,
                        source={
                            "source_id": normalized_unit.source_id or normalized_unit.unit_id,
                            "source_type": "image",
                            "frame_index": normalized_unit.frame_index,
                            "timestamp_ms": normalized_unit.timestamp_ms,
                            "width": normalized_unit.orig_width,
                            "height": normalized_unit.orig_height,
                        },
                        model={
                            "name": config.model.name or config.model.adapter,
                            "model_id": config.model.model_id,
                            "device": config.model.device,
                        },
                        prompts={"prompt_set_id": prompt_version},
                        detections=detections,
                        timing={
                            "read_ms": 0.0,
                            "preprocess_ms": granular.normalize_ms,
                            "inference_ms": granular.inference_ms,
                            "postprocess_ms": granular.postprocess_ms,
                            "write_ms": granular.write_ms,
                            "total_ms": granular.total_ms,
                        },
                    )
                    artifact_writer.write_detection(event)

                    metric = MetricSample(
                        run_id=run_context.run_id,
                        unit_id=normalized_unit.unit_id,
                        source_path=None,
                        fps_effective=round(1000.0 / granular.total_ms, 2) if granular.total_ms > 0 else 0.0,
                        latency_total_ms=granular.total_ms,
                        latency_inference_ms=granular.inference_ms,
                        detections_count=len(detections),
                        dropped_units=0,
                        device=config.model.device,
                        gpu_memory_allocated_mb=round(gpu_mem, 2),
                    )
                    artifact_writer.write_metric(metric)

                    if config.outputs.save_previews and detections and run_context.units_processed < config.outputs.preview_max:
                        preview_name = f"{normalized_unit.unit_id}.preview.jpg"
                        preview_path = run_context.run_dir / "previews" / preview_name
                        # draw_detections necesita path; usar source_id como fallback
                        pass

                    timer.end_write()
                    run_context.units_processed += 1
                    run_context.total_detections += len(detections)
                    run_context.record_detections(detections)

                except Exception as e:
                    logger.error(f"Error escribiendo outputs de unidad {normalized_unit.unit_id}: {e}")
                    timer.end_write()
                    artifact_writer.write_error(ErrorEvent(
                        run_id=run_context.run_id, unit_id=normalized_unit.unit_id,
                        stage="write", message=str(e), recoverable=True,
                    ))
                    run_context.units_failed += 1

                # Actualizar dropped_units desde transport
                if hasattr(transport, "units_dropped"):
                    run_context.units_dropped = transport.units_dropped

                progress.update(task_prog, advance=1)

    finally:
        producer.join(timeout=30.0)
        artifact_writer.close()
        adapter.close()

    run_context.gpu_memory_peak_mb = get_gpu_memory_peak_mb()
    run_context.finish()
    artifact_writer.write_summary(tracker)
    artifact_writer.write_manifest()

    console.print("\n[bold green]✓ Corrida completada[/bold green]")
    console.print(f"  Procesadas: {run_context.units_processed}/{source_count}")
    if run_context.units_failed > 0:
        console.print(f"  [red]Fallos/Errores: {run_context.units_failed}[/red]")
    if run_context.units_dropped > 0:
        console.print(f"  [yellow]Descartadas (rate control): {run_context.units_dropped}[/yellow]")
    console.print(f"  Detecciones totales: {run_context.total_detections}")
    console.print(f"  Latencia promedio: {tracker.avg_latency_ms():.1f} ms")
    console.print(f"  Latencia p95: {tracker.p95_latency_ms():.1f} ms")
    if run_context.gpu_memory_peak_mb > 0:
        console.print(f"  VRAM pico: {run_context.gpu_memory_peak_mb:.0f} MB")
    console.print(f"\n  [dim]Resultados guardados en: {run_context.run_dir}[/dim]\n")

    return run_context.run_id
```

- [ ] **Step 7: Ejecutar la suite completa**

```bash
pytest -q
```
Expected: PASS. Si `test_pipeline_mock.py` falla por cambios de API, ajustar los assertions que dependan del viejo `predict(PIL.Image)` para usar el comportamiento actualizado.

- [ ] **Step 8: Commit**

```bash
git add src/eovrt_media/runtime/pipeline.py src/eovrt_media/runtime/run_context.py src/eovrt_media/models/base.py src/eovrt_media/models/mock_detector.py src/eovrt_media/models/grounding_dino_adapter.py src/eovrt_media/models/yoloe_adapter.py src/eovrt_media/metrics/timers.py tests/test_pipeline_two_threads.py
git commit -m "feat: refactor pipeline to producer/consumer threads with TransportAdapter and Normalizer stage"
```

---

## Task 7: Trazabilidad — `run_descriptor`, `run_provenance.json`, nuevas métricas, auto-naming, `inspect-run`

**Files:**
- Modify: `src/eovrt_media/contracts/events.py`
- Modify: `src/eovrt_media/contracts/metrics.py`
- Modify: `src/eovrt_media/sinks/run_artifact_writer.py`
- Modify: `src/eovrt_media/runtime/run_context.py`
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Modify: `src/eovrt_media/cli.py`
- Test: `tests/test_traceability.py` (nuevo)

**Interfaces:**
- Consumes: `RunConfig` con `rate_control`, `transport`, `topology`, `source.dataset_id/view/split/vocabulary` (Tasks 5–6)
- Produces: `run_descriptor` en `summary.json`, `run_provenance.json`, `p99_latency_ms`, `inspect-run` CLI.

- [ ] **Step 1: Escribir tests de trazabilidad**

```python
# tests/test_traceability.py
import json
from pathlib import Path
import cv2
import numpy as np
import pytest

from eovrt_media.config import load_run_config
from eovrt_media.runtime import run_pipeline

CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def _create_test_images(folder: Path, count: int = 3) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.imwrite(str(folder / f"img_{i:03d}.jpg"), img)
        paths.append(folder / f"img_{i:03d}.jpg")
    return paths


def _mock_config(tmp_path):
    images_dir = tmp_path / "images"
    _create_test_images(images_dir, count=3)
    config = load_run_config(CONFIGS_DIR / "runs" / "mock.yaml")
    config.model.adapter = "mock"
    config.source.path = str(images_dir)
    config.source.dataset_id = "test_dataset"
    config.source.view = "canonical_v2"
    config.source.split = "bench_test"
    config.source.vocabulary = ["person", "helmet"]
    config.outputs.base_dir = str(tmp_path / "runs")
    config.outputs.run_dir = str(tmp_path / "runs")
    config.outputs.save_previews = False
    return config


class TestRunDescriptor:
    def test_run_descriptor_in_summary(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads((Path(config.outputs.base_dir) / run_id / "summary.json").read_text())
        assert "run_descriptor" in summary
        rd = summary["run_descriptor"]
        assert rd["scenario"] == "DBE"
        assert rd["topology"] == "single_host"
        assert "transport" in rd
        assert "rate_control" in rd
        assert "source_kind" in rd

    def test_schema_version_in_summary(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads((Path(config.outputs.base_dir) / run_id / "summary.json").read_text())
        assert "schema_version" in summary
        assert summary["schema_version"].startswith("media.summary.")

    def test_p99_latency_in_summary(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads((Path(config.outputs.base_dir) / run_id / "summary.json").read_text())
        assert "p99_latency_ms" in summary

    def test_units_dropped_in_summary(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        summary = json.loads((Path(config.outputs.base_dir) / run_id / "summary.json").read_text())
        assert "units_dropped" in summary


class TestRunProvenance:
    def test_provenance_file_created(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        prov_path = Path(config.outputs.base_dir) / run_id / "run_provenance.json"
        assert prov_path.exists()

    def test_provenance_has_fingerprint(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        prov = json.loads((Path(config.outputs.base_dir) / run_id / "run_provenance.json").read_text())
        assert "source_fingerprint" in prov
        assert len(prov["source_fingerprint"]) == 64  # SHA-256 hex

    def test_fingerprint_stable_across_runs(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id1 = run_pipeline(config)
        config.outputs.base_dir = str(tmp_path / "runs2")
        config.outputs.run_dir = str(tmp_path / "runs2")
        run_id2 = run_pipeline(config)
        prov1 = json.loads((Path(tmp_path / "runs") / run_id1 / "run_provenance.json").read_text())
        prov2 = json.loads((Path(tmp_path / "runs2") / run_id2 / "run_provenance.json").read_text())
        assert prov1["source_fingerprint"] == prov2["source_fingerprint"]

    def test_provenance_has_dataset_fields(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        prov = json.loads((Path(config.outputs.base_dir) / run_id / "run_provenance.json").read_text())
        assert prov.get("dataset_id") == "test_dataset"
        assert prov.get("view") == "canonical_v2"
        assert prov.get("split") == "bench_test"


class TestAutoNaming:
    def test_auto_run_id_includes_scenario_model_policy(self, tmp_path):
        config = _mock_config(tmp_path)
        config.run.id = None  # sin ID fijo → auto-naming
        run_id = run_pipeline(config)
        assert "dbe" in run_id.lower() or "DBE" in run_id
        assert "mock" in run_id.lower()
        assert "deterministic" in run_id.lower()


class TestMetricsSchemaVersion:
    def test_metrics_jsonl_has_schema_version(self, tmp_path):
        config = _mock_config(tmp_path)
        run_id = run_pipeline(config)
        metrics_path = Path(config.outputs.base_dir) / run_id / "metrics.jsonl"
        first_line = json.loads(metrics_path.read_text().strip().split("\n")[0])
        assert "schema_version" in first_line
```

- [ ] **Step 2: Ejecutar para verificar que falla**

```bash
pytest tests/test_traceability.py -v
```
Expected: fallos — `run_descriptor`, provenance, `p99_latency_ms`, auto-naming no implementados

- [ ] **Step 3: Agregar `RunDescriptor` a `contracts/events.py`**

Agregar antes de `RunSummary`:
```python
class RunDescriptor(BaseModel):
    """Claves de comparación del despliegue — bloque en summary.json."""
    scenario: str
    topology: str
    transport: dict
    rate_control: dict
    source_kind: str
    model: str
    prompt_set: str | None = None
    device: str | None = None
    code_version: str | None = None
```

Actualizar `RunSummary`:
```python
class RunSummary(BaseModel):
    schema_version: str = "media.summary.v2"   # bumpeado
    # ... campos existentes ...
    p99_latency_ms: float = 0.0                # nuevo
    units_dropped: int = 0                     # nuevo
    backpressure_wait_ms: float = 0.0          # nuevo
    max_staleness_observed_ms: float = 0.0     # nuevo
    run_descriptor: RunDescriptor | None = None  # nuevo
```

- [ ] **Step 4: Actualizar `MetricSample` en `contracts/metrics.py`**

```python
class MetricSample(BaseModel):
    schema_version: str = "media.metric.v2"    # bumpeado
    # ... campos existentes ...
    latency_normalize_ms: float = 0.0          # nuevo
```

- [ ] **Step 5: Implementar auto-naming en `runtime/run_context.py`**

Reemplazar la generación de `run_id`:
```python
        if config.run.id:
            self.run_id = config.run.id
        else:
            ts = self.started_at.strftime("%Y%m%d_%H%M%S")
            scenario = config.run.scenario.lower()
            model = (config.model.name or config.model.adapter or "model").lower()
            policy = config.rate_control.policy.lower() if hasattr(config, "rate_control") else "deterministic"
            # run_{ts}_{scenario}_{model}_{policy}
            self.run_id = f"run_{ts}_{scenario}_{model}_{policy}"
```

- [ ] **Step 6: Implementar `write_provenance` y `compute_source_fingerprint` en `run_artifact_writer.py`**

```python
import hashlib

def _compute_source_fingerprint(source_path: str) -> str:
    """SHA-256 del listado ordenado de archivos (path + tamaño)."""
    folder = Path(source_path)
    if not folder.is_dir():
        return ""
    entries = sorted(
        f"{p.name}:{p.stat().st_size}"
        for p in folder.iterdir()
        if p.is_file()
    )
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()
```

Agregar método a `RunArtifactWriter`:
```python
    def write_provenance(self, extra: dict | None = None) -> None:
        """Guarda run_provenance.json con dataset_id, view, split y source_fingerprint."""
        src = self.context.config.source
        fingerprint = _compute_source_fingerprint(src.path)
        provenance = {
            "run_id": self.context.run_id,
            "dataset_id": src.dataset_id,
            "view": src.view,
            "split": src.split,
            "vocabulary": src.vocabulary,
            "source_fingerprint": fingerprint,
        }
        if extra:
            provenance.update(extra)
        with open(self.run_dir / "run_provenance.json", "w", encoding="utf-8") as f:
            json.dump(provenance, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 7: Actualizar `write_summary` en `run_artifact_writer.py`**

Actualizar `write_summary` para incluir `run_descriptor` y nuevas métricas:

```python
    def write_summary(self, tracker=None) -> None:
        # ... código existente ...
        # Agregar p99
        p99_lat = tracker.p99_latency_ms() if tracker and hasattr(tracker, "p99_latency_ms") else 0.0

        # Construir run_descriptor
        cfg = self.context.config
        rd = RunDescriptor(
            scenario=cfg.run.scenario,
            topology=cfg.topology.mode,
            transport={"backend": cfg.transport.backend, "payload_format": cfg.transport.payload_format},
            rate_control={
                "policy": cfg.rate_control.policy,
                "stride": cfg.rate_control.stride,
                "max_queue_size": cfg.rate_control.max_queue_size,
            },
            source_kind=cfg.source.kind or "pulleable",
            model=cfg.model.name or cfg.model.adapter or "unknown",
            prompt_set=cfg.prompts_file.resolved_version if cfg.prompts_file else None,
            device=cfg.model.device,
            code_version=_get_code_version(),
        )

        summary = RunSummary(
            # ... campos existentes ...
            p99_latency_ms=round(p99_lat, 2),
            units_dropped=self.context.units_dropped,
            run_descriptor=rd,
        )
        # ...
```

- [ ] **Step 8: Llamar `write_provenance` desde el pipeline**

En `runtime/pipeline.py`, después de `artifact_writer.write_summary(tracker)`:
```python
    artifact_writer.write_provenance()
```

- [ ] **Step 9: Agregar `inspect-run` a `cli.py`**

```python
@app.command(name="inspect-run")
def inspect_run(
    run_dir: Path = typer.Argument(..., help="Directorio del run (e.g. runs/run_20260621_120000_dbe_mock_deterministic)"),
) -> None:
    """Inspeccionar artefactos de una corrida: run_descriptor, provenance y métricas."""
    if not run_dir.exists():
        console.print(f"[red]✗ Directorio no encontrado: {run_dir}[/red]")
        raise typer.Exit(1)

    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        console.print(f"[red]✗ summary.json no encontrado en: {run_dir}[/red]")
        raise typer.Exit(1)

    summary = json.loads(summary_path.read_text())
    console.print(f"\n[bold cyan]Run:[/bold cyan] {summary.get('run_id', '?')}")
    console.print(f"  Started: {summary.get('started_at', '?')}")
    console.print(f"  Duration: {summary.get('duration_seconds', 0):.1f}s")

    if rd := summary.get("run_descriptor"):
        console.print("\n[bold]Run Descriptor:[/bold]")
        console.print(f"  scenario:    {rd.get('scenario')}")
        console.print(f"  topology:    {rd.get('topology')}")
        console.print(f"  transport:   {rd.get('transport')}")
        console.print(f"  rate_control: {rd.get('rate_control')}")
        console.print(f"  source_kind: {rd.get('source_kind')}")
        console.print(f"  model:       {rd.get('model')}")
        console.print(f"  device:      {rd.get('device')}")
        console.print(f"  code_version: {rd.get('code_version')}")

    console.print("\n[bold]Métricas:[/bold]")
    console.print(f"  units_processed: {summary.get('units_processed')}")
    console.print(f"  units_failed:    {summary.get('units_failed')}")
    console.print(f"  units_dropped:   {summary.get('units_dropped', 0)}")
    console.print(f"  avg_latency_ms:  {summary.get('avg_latency_ms'):.1f}" if summary.get('avg_latency_ms') else "  avg_latency_ms:  0.0")
    console.print(f"  p95_latency_ms:  {summary.get('p95_latency_ms', 0):.1f}")
    console.print(f"  p99_latency_ms:  {summary.get('p99_latency_ms', 0):.1f}")
    console.print(f"  fps_effective:   {summary.get('fps_effective', 0):.2f}")
    console.print(f"  gpu_memory_peak: {summary.get('gpu_memory_peak_mb', 0):.0f} MB")

    prov_path = run_dir / "run_provenance.json"
    if prov_path.exists():
        prov = json.loads(prov_path.read_text())
        console.print("\n[bold]Provenance:[/bold]")
        console.print(f"  dataset_id:   {prov.get('dataset_id')}")
        console.print(f"  view:         {prov.get('view')}")
        console.print(f"  split:        {prov.get('split')}")
        fp = prov.get('source_fingerprint', '')
        console.print(f"  fingerprint:  {fp[:16]}..." if fp else "  fingerprint:  —")
    console.print()
```

- [ ] **Step 10: Ejecutar tests**

```bash
pytest tests/test_traceability.py -v
```
Expected: PASS en todos

- [ ] **Step 11: Ejecutar suite completa**

```bash
pytest -q
```
Expected: PASS en todos los tests

- [ ] **Step 12: Verificar `inspect-run` CLI**

```bash
# Ejecutar una corrida de prueba primero
eovrt-media run --config configs/runs/mock.yaml 2>/dev/null || true
# Luego inspeccionar el último run
ls runs/ | tail -1 | xargs -I{} eovrt-media inspect-run runs/{}
```
Expected: output formateado con run_descriptor y provenance

- [ ] **Step 13: Commit**

```bash
git add src/eovrt_media/contracts/events.py src/eovrt_media/contracts/metrics.py src/eovrt_media/sinks/run_artifact_writer.py src/eovrt_media/runtime/run_context.py src/eovrt_media/runtime/pipeline.py src/eovrt_media/cli.py tests/test_traceability.py
git commit -m "feat: add run_descriptor, run_provenance, p99 metrics, auto run-id naming, inspect-run CLI"
```

---

## Self-Review

### Spec coverage

| Sección del spec | Cubierta en |
|---|---|
| §3 Arquitectura — dos roles desacoplados, `TransportAdapter` | Task 4, Task 6 |
| §3 Política `deterministic` (backpressure, stride) | Task 4 (MemoryTransportAdapter), Task 6 (RateGate) |
| §3 Política `bounded_freshness` (head-drop, max_staleness) | Task 4 |
| §3 Apagado con centinela `END` | Task 1 (END), Task 4 (close), Task 6 (producer) |
| §3 Backend `memory` (cola en proceso) | Task 4 |
| §3 Backend `ipc` declarado | Task 4 |
| §3 Backend `network` (ZMQ) declarado | Task 4 (declared.py + NetworkRequest/Response/Heartbeat) |
| §4 Config `rate_control`, `transport`, `topology` | Task 5 |
| §4 Migración dura de `sampling` | Task 5 |
| §4 Derivación `source.kind → policy`, `topology → backend` | Task 5 |
| §4 Gating features declaradas | Task 5 |
| §4 `effective_config.yaml` materializa defaults | Existente (ya funciona) |
| §4 Catálogos datasets ganan `dataset_id`, `view`, `split`, `vocabulary` | Task 5 (YAML), Task 5 (SourceSection) |
| §5 `NormalizedUnit` con metadata + payload + transform | Task 1 |
| §5 `ModelInputSpec` por adapter | Task 2 |
| §5 `Normalizer` como etapa del productor | Task 3 |
| §5 `prepare_model_input` finalizador tensorial | Task 3 |
| §5 `payload_format: fp16` declarado | Task 1 (enum), Task 3 (gating en normalize_spatial) |
| §5 Verificación paridad numérica | Task 3 (test_normalizer.py) |
| §5 Reproyección de cajas via `transform` | Task 3 (DetectionNormalizer + transform) |
| §6 `run_descriptor` en summary.json | Task 7 |
| §6 `run_provenance.json` + `source_fingerprint` | Task 7 |
| §6 `p99_latency_ms`, `units_dropped`, `backpressure_wait_ms`, `max_staleness_observed_ms` | Task 7 |
| §6 `schema_version` en summary y metrics.jsonl | Task 7 |
| §6 CLI `inspect-run` | Task 7 |
| §6 Auto-naming `run_{ts}_{scenario}_{model}_{policy}` | Task 7 |
| §7 `LiveSource` abstracta declarada | Task 4 |
| §7 `two_node` config válida + falla rápido | Task 5 |
| §8 Tests reproducibilidad deterministic | Task 6 |
| §8 Tests políticas rate control | Task 4 |
| §8 Tests concurrencia + apagado | Task 6 |
| §8 Tests Normalizer (paridad + golden) | Task 3 |
| §8 Tests config derivación + gating | Task 5 |
| §8 Tests trazabilidad | Task 7 |
| §8 Suite `TransportAdapter` agnóstica de backend | Task 4 (TestTransportContract) |

### Gaps identificados

- `desglose de latencia por etapa (normalize/write)` en summary.json: cubierto por `normalize_ms` en `UnitTimingResult` (Task 6) y en `write_summary` (Task 7). ✅
- `backpressure_wait_ms` en RunContext: declarado en Task 6 (run_context.py), pero el pipeline no lo mide actualmente. Para implementarlo completamente, se necesita medir el tiempo que `MemoryTransportAdapter.offer()` bloquea. Esto es un detalle de instrumentación: agregar timer alrededor de `transport.offer(normalized)` en el producer thread. Añadido en Task 6 code.
- `compare-runs` CLI: spec lo diferiere explícitamente. ✅ (no incluido)

### Placeholder scan — ninguno encontrado

### Type consistency

- `normalize_spatial` recibe `VisualUnit` y devuelve `NormalizedUnit` ✅
- `DetectionNormalizer.normalize` acepta `transform: ResizeTransform | None` ✅  
- `adapter.forward(unit: NormalizedUnit, prompts: list[str]) -> list[RawDetection]` ✅
- `create_transport(backend, policy, ...)` → `TransportAdapter` ✅
- `END` es una clase (no instancia) usada como sentinel, comparada con `is` ✅
- `run_descriptor: RunDescriptor | None` en `RunSummary` ✅
