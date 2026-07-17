# Pre-filtro EN-2 on-device en OAK-D + latencia de captura — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activar el modo EN-2 (preselección conservadora on-device) en `OakDSource`: gate por detector de personas en la cámara con fail-open estructural, más knobs de latencia (XLink chunking, escala ISP) y la métrica `capture_to_host_ms` — todo config-driven, aditivo, y sin alterar los plugins `rtsp`/`video_file`/`image_folder`.

**Architecture:** El pipeline DepthAI v2 de `OakDSource` gana una rama opcional: `ColorCamera.preview` (544×320) → `MobileNetDetectionNetwork` (blob `person-detection-retail-0013`) → nodo `Script` que reenvía `cam.video` al host solo con evidencia reciente de persona (o heartbeat / fail-open), publicando contadores por una segunda cola `prefilter_stats`. El lado host queda intacto salvo telemetría aditiva (`RunContext` → `summary.json`) y el campo opcional `capture_to_host_ms` que viaja `VisualUnit`→`NormalizedUnit`→`MetricSample`.

**Tech Stack:** Python 3.11, DepthAI v2 (`depthai>=2.24,<3`), Pydantic, pytest (dobles del SDK, sin hardware), blobconverter.

**Spec:** `docs/superpowers/specs/2026-07-15-oak-d-prefilter-en2-design.md` — leerlo antes de empezar; las secciones se citan como §N.

## Global Constraints

- **DepthAI v2 solamente** (`depthai>=2.24,<3`): API `Pipeline`/`XLinkOut`/`MobileNetDetectionNetwork`/`Script`. Nada de la API v3.
- **Config-driven**: ningún umbral/ruta hardcodeado fuera de defaults de schema Pydantic.
- **Default off**: `prefilter.enabled: false` y `isp_scale` ausente ⇒ pipeline byte-idéntico al actual (EN-0). Única excepción deliberada: `xlink_chunk_size` default `0` (§7.1).
- **Invariantes de compatibilidad (§8)**: la suite existente de `rtsp`/`video_file`/`image_folder` debe pasar **sin modificar ni un test**; `detections.jsonl` no se toca; campos nuevos de contratos son opcionales con default `None`.
- **NO COMMITS**: regla del workspace (`projects/CLAUDE.md`) — nunca commitear salvo pedido explícito del usuario en ese turno. Los pasos de cierre de cada task son "checkpoint" (correr tests + lint), no commits.
- Ejecutar tests desde la raíz del repo con el venv activo: `source .venv/bin/activate`.

---

### Task 1: Schema de configuración (`OakDPrefilterConfig`, `isp_scale`, `xlink_chunk_size`)

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (constantes en ~línea 140, `SourceSection` en 147–211)
- Test: `tests/test_oak_d_prefilter_config.py` (nuevo)

**Interfaces:**
- Produces: `OakDPrefilterConfig` (campos: `enabled: bool=False`, `model_blob: str`, `confidence: float=0.25`, `keepalive_window_ms: int=1500`, `heartbeat_interval_ms: int=2000`, `stall_failopen_ms: int=3000`); `SourceSection.prefilter: OakDPrefilterConfig | None`, `SourceSection.isp_scale: tuple[int, int] | None`, `SourceSection.xlink_chunk_size: int = 0`. Tasks 2, 6 y 7 consumen exactamente estos nombres.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_oak_d_prefilter_config.py`:

```python
"""Schema del prefilter EN-2 y knobs de latencia de oak_d (spec 2026-07-15 §6/§7/§8)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from eovrt_media.config.schemas import OakDPrefilterConfig, SourceSection

OAK = {"type": "oak_d", "url": "192.168.1.50"}


def test_prefilter_defaults_off():
    s = SourceSection(**OAK)
    assert s.prefilter is None
    assert s.isp_scale is None
    assert s.xlink_chunk_size == 0


def test_prefilter_block_defaults():
    cfg = OakDPrefilterConfig(enabled=True)
    assert cfg.model_blob == "models/edge/person-detection-retail-0013_6shave.blob"
    assert cfg.confidence == 0.25
    assert cfg.keepalive_window_ms == 1500
    assert cfg.heartbeat_interval_ms == 2000
    assert cfg.stall_failopen_ms == 3000


def test_prefilter_confidence_out_of_range():
    with pytest.raises(ValidationError):
        OakDPrefilterConfig(confidence=0.0)
    with pytest.raises(ValidationError):
        OakDPrefilterConfig(confidence=1.0)


def test_prefilter_stall_must_cover_keepalive():
    with pytest.raises(ValidationError, match="stall_failopen_ms"):
        OakDPrefilterConfig(keepalive_window_ms=5000, stall_failopen_ms=1000)


def test_prefilter_accepted_for_oak_d():
    s = SourceSection(**OAK, prefilter={"enabled": True})
    assert s.prefilter is not None and s.prefilter.enabled


@pytest.mark.parametrize("source_type,extra", [
    ("rtsp", {"url": "rtsp://cam/1"}),
    ("image_folder", {"path": "/tmp/imgs"}),
    ("video_file", {"path": "/tmp/v.mp4"}),
])
def test_new_fields_rejected_on_non_oak_d(source_type, extra):
    with pytest.raises(ValidationError, match="oak_d"):
        SourceSection(type=source_type, **extra, prefilter={"enabled": True})
    with pytest.raises(ValidationError, match="oak_d"):
        SourceSection(type=source_type, **extra, isp_scale=(3, 4))
    with pytest.raises(ValidationError, match="oak_d"):
        SourceSection(type=source_type, **extra, xlink_chunk_size=0)  # seteado, aun con el valor default


def test_non_oak_d_without_new_fields_still_valid():
    # Invariante §8.2: configs existentes validan idéntico.
    s = SourceSection(type="rtsp", url="rtsp://cam/1")
    assert s.xlink_chunk_size == 0


def test_isp_scale_shape_validated():
    assert SourceSection(**OAK, isp_scale=(3, 4)).isp_scale == (3, 4)
    assert SourceSection(**OAK, isp_scale=(2, 4)).isp_scale == (2, 4)  # simplifica a 1/2: ok
    with pytest.raises(ValidationError, match="isp_scale"):
        SourceSection(**OAK, isp_scale=(0, 4))
    with pytest.raises(ValidationError, match="isp_scale"):
        SourceSection(**OAK, isp_scale=(17, 5))   # num>16 irreducible
    with pytest.raises(ValidationError, match="isp_scale"):
        SourceSection(**OAK, isp_scale=(1, 64))   # den>63 irreducible


def test_xlink_chunk_size_range():
    assert SourceSection(**OAK, xlink_chunk_size=-1).xlink_chunk_size == -1
    assert SourceSection(**OAK, xlink_chunk_size=65536).xlink_chunk_size == 65536
    with pytest.raises(ValidationError, match="xlink_chunk_size"):
        SourceSection(**OAK, xlink_chunk_size=-2)
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_oak_d_prefilter_config.py -q`
Expected: FAIL con `ImportError: cannot import name 'OakDPrefilterConfig'`.

- [ ] **Step 3: Implementar en `schemas.py`**

Agregar `import math` arriba (junto a los imports existentes). Antes de `class SourceSection` (después de `OAK_D_ORIENTATIONS`, ~línea 145):

```python
class OakDPrefilterConfig(BaseModel):
    """Prefilter EN-2 on-device (spec 2026-07-15): gate de personas en la cámara.

    Sesgo fail-open estructural: umbral bajo + ventana de evidencia + heartbeat
    incondicional + apertura total ante silencio de la NN. Solo source.type=oak_d.
    """

    enabled: bool = False
    # Ruta relativa a la raíz del repo (convención de pesos); ver Task 6 (fail-fast).
    model_blob: str = "models/edge/person-detection-retail-0013_6shave.blob"
    confidence: float = Field(default=0.25, gt=0.0, lt=1.0)
    keepalive_window_ms: int = Field(default=1500, gt=0)
    heartbeat_interval_ms: int = Field(default=2000, gt=0)
    stall_failopen_ms: int = Field(default=3000, gt=0)

    @model_validator(mode="after")
    def _check_windows(self) -> OakDPrefilterConfig:
        if self.stall_failopen_ms < self.keepalive_window_ms:
            raise ValueError(
                "prefilter.stall_failopen_ms debe ser >= prefilter.keepalive_window_ms "
                "(el fail-open no puede dispararse antes de que venza la evidencia)."
            )
        return self
```

En `SourceSection`, debajo de `orientation: str = "normal"` (línea 185):

```python
    # Prefilter EN-2 on-device y knobs de latencia (spec 2026-07-15 §6/§7).
    # Solo válidos para source.type=oak_d; seteados en otro tipo -> 422.
    prefilter: OakDPrefilterConfig | None = None
    isp_scale: tuple[int, int] | None = None
    # 0 = sin chunking XLink (baseline oficial de baja latencia); -1 = default
    # del device (64 KiB). Solo lo lee OakDSource.
    xlink_chunk_size: int = 0
```

En `_check_locator`, como PRIMER bloque del método (antes del `if source_type == "rtsp"`):

```python
        source_type = self.type.lower().strip()
        if source_type != "oak_d":
            # §8.2: setear knobs de oak_d en otra fuente es error explícito, no
            # silencio. Para xlink_chunk_size (default 0, indistinguible por
            # valor) se usa model_fields_set.
            if self.prefilter is not None:
                raise ValueError("source.prefilter solo aplica a source.type='oak_d'")
            if self.isp_scale is not None:
                raise ValueError("source.isp_scale solo aplica a source.type='oak_d'")
            if "xlink_chunk_size" in self.model_fields_set:
                raise ValueError("source.xlink_chunk_size solo aplica a source.type='oak_d'")
```

(la línea `source_type = ...` ya existe; no duplicarla — mover el bloque nuevo justo después). Dentro de la rama `elif source_type == "oak_d":`, después de la validación de `orientation`:

```python
            if self.isp_scale is not None:
                num, den = self.isp_scale
                if num <= 0 or den <= 0:
                    raise ValueError("source.isp_scale debe ser [num, den] con enteros > 0")
                g = math.gcd(num, den)
                if num // g > 16 or den // g > 63:
                    raise ValueError(
                        f"source.isp_scale {list(self.isp_scale)!r} fuera del rango del "
                        "scaler ISP (tras simplificar: num <= 16, den <= 63)."
                    )
            if self.xlink_chunk_size < -1:
                raise ValueError(
                    "source.xlink_chunk_size debe ser >= -1 "
                    "(0 = sin chunking, -1 = default del device)."
                )
```

- [ ] **Step 4: Verificar que pasan**

Run: `pytest tests/test_oak_d_prefilter_config.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: suite completa verde (los tests de config existentes no cambian) y ruff limpio.

---

### Task 2: Knobs de latencia en `OakDSource` (`setXLinkChunkSize`, `setIspScale`) + registry

**Files:**
- Modify: `src/eovrt_media/sources/oak_d_source.py` (constructor 64–102, `_build_pipeline` 124–139)
- Modify: `src/eovrt_media/sources/registry.py:96-105` (rama `oak_d` de `create_source`)
- Test: `tests/test_oak_d_source.py` (extender fakes y agregar tests)

**Interfaces:**
- Consumes: `SourceSection.isp_scale`, `SourceSection.xlink_chunk_size` (Task 1).
- Produces: `OakDSource.__init__(..., isp_scale: tuple[int, int] | None = None, xlink_chunk_size: int = 0)`. Task 6 extiende este mismo constructor con `prefilter`.

- [ ] **Step 1: Extender el fake y escribir tests que fallan**

En `tests/test_oak_d_source.py`, `_FakePipeline` (línea 77) gana el método de chunking, registrando en `calls`:

```python
class _FakePipeline:
    def __init__(self, calls: dict) -> None:
        self._calls = calls

    def create(self, node_cls):
        return _FakeNode(self._calls)

    def setXLinkChunkSize(self, size: int) -> None:
        self._calls["setXLinkChunkSize"] = size
```

Agregar tests (mismo archivo, al final):

```python
def test_build_pipeline_disables_xlink_chunking_by_default():
    calls: dict = {}
    source = OakDSource(url="192.168.1.50")
    source._build_pipeline(_fake_dai(calls))
    assert calls["setXLinkChunkSize"] == 0


def test_build_pipeline_respects_device_default_chunking():
    calls: dict = {}
    source = OakDSource(url="192.168.1.50", xlink_chunk_size=-1)
    source._build_pipeline(_fake_dai(calls))
    assert "setXLinkChunkSize" not in calls  # -1 = no tocar el default del device


def test_build_pipeline_applies_isp_scale():
    calls: dict = {}
    source = OakDSource(url="192.168.1.50", isp_scale=(3, 4))
    source._build_pipeline(_fake_dai(calls))
    assert calls["setIspScale"] == (3, 4)


def test_build_pipeline_without_isp_scale_does_not_touch_scaler():
    calls: dict = {}
    OakDSource(url="192.168.1.50")._build_pipeline(_fake_dai(calls))
    assert "setIspScale" not in calls
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_oak_d_source.py -q -k "xlink or isp_scale"`
Expected: FAIL (`TypeError: unexpected keyword argument` / `KeyError: 'setXLinkChunkSize'`).

- [ ] **Step 3: Implementar**

Constructor de `OakDSource` — firma nueva (insertar tras `orientation`):

```python
    def __init__(
        self,
        url: str,
        resolution: str = "1080p",
        fps: int = 10,
        orientation: str = "normal",
        isp_scale: tuple[int, int] | None = None,
        xlink_chunk_size: int = 0,
        reconnect_retries: int = 5,
        reconnect_delay_ms: int = 1000,
        max_units: int | None = None,
        source_id: str | None = None,
    ) -> None:
```

y guardar (junto a los asserts de valores existentes; el schema ya validó rangos — acá solo se almacena):

```python
        self.isp_scale = tuple(isp_scale) if isp_scale is not None else None
        self.xlink_chunk_size = xlink_chunk_size
```

En `_build_pipeline`, después de `pipeline = dai.Pipeline()` y antes de crear la cámara:

```python
        if self.xlink_chunk_size >= 0:
            # 0 = sin chunking: baseline oficial de baja latencia de Luxonis
            # (spec §7.1). -1 deja el default del device (64 KiB).
            pipeline.setXLinkChunkSize(self.xlink_chunk_size)
```

y después de `cam.setFps(self.fps)`:

```python
        if self.isp_scale is not None:
            # Escala en el bloque scaler del ISP (hardware, sin SHAVEs); afecta
            # .video y todo lo derivado (spec §7.2).
            cam.setIspScale(*self.isp_scale)
```

En `registry.py`, rama `oak_d` (línea 96), agregar los kwargs:

```python
        return OakDSource(
            url=config.source.url,
            resolution=config.source.resolution,
            fps=config.source.fps,
            orientation=config.source.orientation,
            isp_scale=config.source.isp_scale,
            xlink_chunk_size=config.source.xlink_chunk_size,
            reconnect_retries=config.source.reconnect_retries,
            reconnect_delay_ms=config.source.reconnect_delay_ms,
            max_units=config.run.max_units,
            source_id=config.source.source_id,
        )
```

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_oak_d_source.py tests/test_source_registry.py -q` (si el archivo de tests del registry tiene otro nombre, correr `pytest tests/ -q -k registry`).
Expected: PASS, incluida la suite previa sin cambios.

- [ ] **Step 5: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde.

---

### Task 3: Métrica `capture_to_host_ms` de punta a punta

**Files:**
- Modify: `src/eovrt_media/contracts/visual_unit.py` (campo nuevo, ~línea 36)
- Modify: `src/eovrt_media/contracts/normalized_unit.py:39+` (campo nuevo en `NormalizedUnit`)
- Modify: `src/eovrt_media/preprocessing/normalizer.py:82` (copiado explícito, junto a `capture_monotonic_ns`)
- Modify: `src/eovrt_media/contracts/metrics.py` (campo en `MetricSample`)
- Modify: `src/eovrt_media/contracts/events.py:88-121` (campo en `RunSummary`)
- Modify: `src/eovrt_media/runtime/run_context.py:35-44` (acumulador)
- Modify: `src/eovrt_media/runtime/pipeline.py:342-366` (pasar el campo + acumular)
- Modify: `src/eovrt_media/sinks/run_artifact_writer.py:203-240` (percentiles en summary)
- Modify: `src/eovrt_media/sources/oak_d_source.py` (medición al leer)
- Test: `tests/test_oak_d_source.py`, `tests/test_capture_to_host_metric.py` (nuevo)

**Interfaces:**
- Produces: `VisualUnit.capture_to_host_ms: float | None = None` (ídem `NormalizedUnit`, `MetricSample`); `RunContext.capture_to_host_samples: list[float]`; `RunSummary.capture_to_host: dict | None` con forma `{"p50_ms": float, "p95_ms": float, "samples": int}`.

- [ ] **Step 1: Tests que fallan — fuente**

En `tests/test_oak_d_source.py`: extender `_FakeMsg` y `_fake_dai` con timestamps sincronizados:

```python
from datetime import timedelta


class _FakeMsg:
    def __init__(self, frame: np.ndarray, ts: timedelta | None = None) -> None:
        self._frame = frame
        self._ts = ts

    def getCvFrame(self) -> np.ndarray:
        return self._frame

    def getTimestamp(self) -> timedelta:
        if self._ts is None:
            raise RuntimeError("sin timestamp")  # firmwares/fakes viejos
        return self._ts
```

En `_fake_dai(...)` agregar al `SimpleNamespace`:

```python
        Clock=SimpleNamespace(now=lambda: timedelta(seconds=100.0)),
```

En `_FakeQueue.tryGet`, construir el msg con timestamp 42 ms en el pasado:

```python
        return _FakeMsg(frame, ts=timedelta(seconds=100.0) - timedelta(milliseconds=42))
```

Tests nuevos:

```python
def test_capture_to_host_ms_measured_from_device_timestamp(monkeypatch):
    source = _make_source(monkeypatch, [_FakeDevice(_FakeQueue(n_frames=1))], max_units=1)
    unit = next(iter(source))
    assert unit.capture_to_host_ms == pytest.approx(42.0, abs=0.5)


def test_capture_to_host_ms_none_when_timestamp_unavailable(monkeypatch):
    class _NoTsQueue(_FakeQueue):
        def tryGet(self):
            msg = super().tryGet()
            if msg is not None:
                msg._ts = None  # getTimestamp lanzará
            return msg

    source = _make_source(monkeypatch, [_FakeDevice(_NoTsQueue(n_frames=1))], max_units=1)
    unit = next(iter(source))
    assert unit.capture_to_host_ms is None
```

- [ ] **Step 2: Tests que fallan — plumbing y summary**

Crear `tests/test_capture_to_host_metric.py`:

```python
"""capture_to_host_ms: contrato aditivo y agregación p50/p95 (spec §7.3, §8.4)."""
from __future__ import annotations

import numpy as np

from eovrt_media.contracts import VisualUnit
from eovrt_media.contracts.metrics import MetricSample
from eovrt_media.preprocessing.normalizer import normalize_spatial


def test_visual_unit_field_is_optional_and_defaults_none():
    unit = VisualUnit(unit_id="u", source_type="image", width=8, height=8)
    assert unit.capture_to_host_ms is None  # §8: aditivo, None para otras fuentes


def test_metric_sample_field_is_optional():
    m = MetricSample(run_id="r", unit_id="u")
    assert m.capture_to_host_ms is None


def test_normalize_spatial_copies_capture_to_host_ms():
    unit = VisualUnit(
        unit_id="u", source_type="video_frame", width=16, height=16,
        pixel_data=np.zeros((16, 16, 3), dtype=np.uint8),
        capture_to_host_ms=37.5,
    )
    # Usar la misma spec/formato que los tests existentes de normalize_spatial
    # (ver tests/test_normalizer*.py para el fixture de input_spec del repo).
    normalized = normalize_spatial(unit, _spec_from_existing_tests(), _payload_format())
    assert normalized.capture_to_host_ms == 37.5
```

Nota para el implementador: `_spec_from_existing_tests()`/`_payload_format()` son la spec/formato que ya usan los tests existentes del normalizador — copiar la construcción exacta desde `tests/test_normalizer*.py` (buscar `normalize_spatial(` en `tests/`) en lugar de inventar una. Para el summary, agregar en el mismo archivo un test estilo los de `run_artifact_writer` existentes (buscar `write_summary` en `tests/`): poblar `context.capture_to_host_samples = [10.0, 20.0, 30.0, 40.0]`, llamar `write_summary`, leer `summary.json` y afirmar `summary["capture_to_host"] == {"p50_ms": 30.0, "p95_ms": 40.0, "samples": 4}` y que con `capture_to_host_samples == []` el campo es `None`.

- [ ] **Step 3: Verificar que fallan**

Run: `pytest tests/test_capture_to_host_metric.py tests/test_oak_d_source.py -q`
Expected: FAIL (campo inexistente en `VisualUnit`).

- [ ] **Step 4: Implementar**

`contracts/visual_unit.py` — debajo de `capture_wallclock_ms` (línea 24):

```python
    # Latencia sensor->host medida con el timestamp de device sincronizado
    # (spec 2026-07-15 §7.3). Solo la emite OakDSource; None = no medida.
    capture_to_host_ms: float | None = None
```

`contracts/normalized_unit.py` — mismo campo, mismo comentario, dentro de `NormalizedUnit` (línea 39+), junto a su `capture_monotonic_ns`.

`preprocessing/normalizer.py:82` — junto al copiado existente:

```python
        capture_monotonic_ns=unit.capture_monotonic_ns,
        capture_to_host_ms=unit.capture_to_host_ms,
```

`contracts/metrics.py` — debajo de `g2a_ms` (línea 23):

```python
    # Tramo sensor->host (solo oak_d; None = fuente sin timestamps de device).
    capture_to_host_ms: float | None = None
```

`contracts/events.py` — en `RunSummary`, debajo de `g2a` (línea 121):

```python
    # p50/p95 del tramo sensor->host (solo corridas oak_d). None = sin muestras.
    capture_to_host: dict | None = None
```

`runtime/run_context.py` — junto a los contadores (línea 44):

```python
        self.capture_to_host_samples: list[float] = []
```

`runtime/pipeline.py` — en el `MetricSample(` de la línea 342, agregar `capture_to_host_ms=item.capture_to_host_ms,` después de `g2a_ms=...`; y junto a `run_context.units_processed += 1` (línea 364):

```python
            if item.capture_to_host_ms is not None:
                run_context.capture_to_host_samples.append(item.capture_to_host_ms)
```

`sinks/run_artifact_writer.py` — antes de construir `RunSummary` (línea 203):

```python
        cth_samples = sorted(self.context.capture_to_host_samples)
        capture_to_host = None
        if cth_samples:
            def _pct(p: float) -> float:
                return cth_samples[min(int(len(cth_samples) * p), len(cth_samples) - 1)]
            capture_to_host = {
                "p50_ms": round(_pct(0.50), 2),
                "p95_ms": round(_pct(0.95), 2),
                "samples": len(cth_samples),
            }
```

y en el constructor de `RunSummary`: `capture_to_host=capture_to_host,`.

`sources/oak_d_source.py` — en `__iter__`, después de `frame = msg.getCvFrame()` (línea 229):

```python
                try:
                    # Timestamp de device ya traducido al steady_clock del host
                    # (timesync <0.5 ms en PoE); clamp a 0 por jitter del sync.
                    delta = dai.Clock.now() - msg.getTimestamp()
                    capture_to_host_ms = round(max(delta.total_seconds() * 1000.0, 0.0), 2)
                except Exception:
                    capture_to_host_ms = None
```

y en el `yield VisualUnit(...)`: `capture_to_host_ms=capture_to_host_ms,`.

- [ ] **Step 5: Verificar y checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde. Atención al test-centinela del G2A (el del `sleep`): no debe verse afectado — solo se agregó un copiado más.

---

### Task 4: Provisión del blob (`scripts/download_prefilter_blob.py` + Makefile + pyproject)

**Files:**
- Create: `scripts/download_prefilter_blob.py`
- Modify: `Makefile` (target nuevo + `.PHONY`)
- Modify: `pyproject.toml:19` (extra `edge`)

**Interfaces:**
- Produces: `models/edge/person-detection-retail-0013_6shave.blob` (el default de `OakDPrefilterConfig.model_blob`, Task 1).

- [ ] **Step 1: Escribir el script**

```python
"""Descarga y compila el blob RVC2 del detector de personas del prefilter EN-2.

Modelo: person-detection-retail-0013 (Open Model Zoo, Apache-2.0), 544x320,
2.3 GFLOPs — spec 2026-07-15 §3. Compilado para 6 SHAVEs vía blobconverter.
Requiere red; el blob (~3 MB) queda git-ignorado como el resto de los pesos.
"""
from __future__ import annotations

from pathlib import Path

import blobconverter

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "models" / "edge"
TARGET = OUT_DIR / "person-detection-retail-0013_6shave.blob"


def main() -> None:
    if TARGET.exists():
        print(f"Ya existe: {TARGET}")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    blob = blobconverter.from_zoo(
        name="person-detection-retail-0013",
        zoo_type="intel",
        shaves=6,
        output_dir=str(OUT_DIR),
    )
    # blobconverter agrega sufijos de versión OpenVINO al nombre: renombrar al
    # nombre canónico que espera el default del schema.
    Path(blob).replace(TARGET)
    print(f"Blob listo: {TARGET}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Makefile y pyproject**

Makefile — agregar `download-prefilter-blob` al `.PHONY` (línea 1) y el target (después de `download-models`, línea 13):

```makefile
download-prefilter-blob:
	python scripts/download_prefilter_blob.py
```

`pyproject.toml` línea 19:

```toml
edge = ["depthai>=2.24,<3", "blobconverter>=1.4.3"]
```

- [ ] **Step 3: Verificar (con red; opcional si no hay conectividad)**

Run: `pip install -e ".[edge]" && make download-prefilter-blob && ls -la models/edge/`
Expected: `person-detection-retail-0013_6shave.blob` (~3 MB). Verificar que `models/` ya está en `.gitignore` (lo está para los pesos actuales; si `models/edge/` no quedara cubierto, agregarlo).

- [ ] **Step 4: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde (el script no tiene tests: es tooling de red, mismo criterio que `download-models`).

---

### Task 5: Template del script de gate + lógica testeada en host

**Files:**
- Modify: `src/eovrt_media/sources/oak_d_source.py` (constante `_GATE_SCRIPT_TEMPLATE` + método `_render_gate_script`)
- Test: `tests/test_oak_d_prefilter_gate.py` (nuevo)

**Interfaces:**
- Consumes: `OakDPrefilterConfig` (Task 1).
- Produces: `OakDSource._render_gate_script() -> str` (usado por Task 6). Contrato del script: inputs `node.io["frames"]` (`.get()`, bloqueante) y `node.io["detections"]` (`.tryGet()`); outputs `node.io["out"]` (frames que pasan) y `node.io["stats"]` (`Buffer` con JSON `{"seen", "forwarded", "dropped_no_person", "forwarded_by_reason": {person, heartbeat, failopen, warmup}, "nn_results"}` cada ~1 s).

- [ ] **Step 1: Tests que fallan**

Crear `tests/test_oak_d_prefilter_gate.py`. El harness ejecuta el template con `exec()` inyectando un `time` falso vía `__import__` (el nodo Script real corre CPython 3.9 on-device; acá se testea la LÓGICA):

```python
"""Lógica del gate EN-2 (spec §5): se ejecuta el script del nodo Script en host
con dobles de node.io/time/Buffer. Sin depthai ni hardware."""
from __future__ import annotations

import builtins
import json
from types import SimpleNamespace

import pytest

from eovrt_media.config.schemas import OakDPrefilterConfig
from eovrt_media.sources.oak_d_source import OakDSource


class _EndOfFrames(Exception):
    pass


class _FakeBuffer:
    def __init__(self, size: int) -> None:
        self._data = b""

    def setData(self, data) -> None:
        self._data = bytes(data)


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t


def _run_gate(prefilter: OakDPrefilterConfig, ticks):
    """Ejecuta el script contra un plan de ticks.

    ticks: lista de (dt_s, detections | None) — cada tick avanza el reloj dt_s,
    entrega opcionalmente un ImgDetections falso y luego un frame. detections es
    una lista de (label, confidence). Devuelve (frames_enviados, stats_json).
    """
    source = OakDSource(url="192.168.1.50", prefilter=prefilter, _skip_blob_check=True)
    script = source._render_gate_script()
    clock = _FakeClock()
    plan = list(ticks)
    sent, stats = [], []
    pending_dets = []

    def frames_get():
        if not plan:
            raise _EndOfFrames()
        dt, dets = plan.pop(0)
        clock.t += dt
        if dets is not None:
            pending_dets.append(SimpleNamespace(
                detections=[SimpleNamespace(label=lbl, confidence=c) for lbl, c in dets]
            ))
        return f"frame@{clock.t}"

    node = SimpleNamespace(io={
        "frames": SimpleNamespace(get=frames_get),
        "detections": SimpleNamespace(
            tryGet=lambda: pending_dets.pop(0) if pending_dets else None
        ),
        "out": SimpleNamespace(send=sent.append),
        "stats": SimpleNamespace(send=lambda b: stats.append(json.loads(b._data))),
    })
    fake_time = SimpleNamespace(monotonic=clock.monotonic)

    def fake_import(name, *args, **kwargs):
        if name == "time":
            return fake_time
        return builtins.__import__(name, *args, **kwargs)

    glb = {
        "__builtins__": {**vars(builtins), "__import__": fake_import},
        "node": node,
        "Buffer": _FakeBuffer,
    }
    with pytest.raises(_EndOfFrames):
        exec(script, glb)  # noqa: S102 - ejecuta NUESTRO template, es el SUT
    return sent, stats


CFG = OakDPrefilterConfig(
    enabled=True, confidence=0.25,
    keepalive_window_ms=1500, heartbeat_interval_ms=2000, stall_failopen_ms=3000,
)
PERSON = [(1, 0.8)]     # label 1 = person en retail-0013
NOBODY = [(1, 0.1)]     # bajo el umbral


def test_warmup_forwards_everything_until_first_nn_result():
    sent, _ = _run_gate(CFG, [(0.1, None), (0.1, None), (0.1, None)])
    assert len(sent) == 3  # regla 4: sin resultados de NN aún -> pasa todo


def test_person_opens_gate_for_keepalive_window():
    # NN ve persona en t=0.1; frames dentro de la ventana de 1.5 s pasan.
    sent, _ = _run_gate(CFG, [(0.1, PERSON), (0.5, NOBODY), (0.5, NOBODY), (1.0, NOBODY)])
    # t=0.1 (person), t=0.6 (dentro ventana), t=1.1 (dentro), t=2.1 (fuera, sin heartbeat vencido)
    assert len(sent) == 3


def test_no_person_drops_until_heartbeat():
    # Sin personas: solo el warmup inicial y después 1 frame por heartbeat (2 s).
    ticks = [(0.5, NOBODY)] + [(0.5, NOBODY)] * 7
    sent, _ = _run_gate(CFG, ticks)
    # t=0.5 primer NN result -> gate cerrado; heartbeat abre a los >=2 s del último envío.
    assert 1 <= len(sent) <= 3  # exacto abajo con stats; acota el comportamiento


def test_nn_stall_fails_open():
    # NN responde una vez y se calla; pasado stall_failopen_ms (3 s) pasa todo.
    ticks = [(0.1, NOBODY), (1.0, None), (1.0, None), (1.5, None), (0.5, None), (0.5, None)]
    sent, _ = _run_gate(CFG, ticks)
    # A partir de t>=3.1 desde el último NN result, todos los frames pasan.
    assert len(sent) >= 3


def test_stats_report_counters_and_reasons():
    ticks = [(1.1, PERSON), (1.1, NOBODY), (1.1, NOBODY)]
    _, stats = _run_gate(CFG, ticks)
    assert stats, "debe emitir stats ~1/s"
    last = stats[-1]
    assert set(last) == {"seen", "forwarded", "dropped_no_person", "forwarded_by_reason", "nn_results"}
    assert last["seen"] == last["forwarded"] + last["dropped_no_person"]
    assert set(last["forwarded_by_reason"]) == {"person", "heartbeat", "failopen", "warmup"}
```

Nota: `_skip_blob_check=True` es un kwarg privado del constructor que se define en Task 6; para esta task, definirlo ya en el constructor como `_skip_blob_check: bool = False` guardado en `self._skip_blob_check` (todavía sin uso) para que estos tests compilen — Task 6 le da semántica.

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_oak_d_prefilter_gate.py -q`
Expected: FAIL (`AttributeError: _render_gate_script` / `TypeError` por kwargs).

- [ ] **Step 3: Implementar el template**

En `oak_d_source.py`, constante de módulo (después de `_NO_FRAME_TIMEOUT_S`). Tokens `__X__` por `str.replace` — NO usar `str.format` (el template está lleno de llaves):

```python
# Código del nodo Script (CPython 3.9 en el LEON de la cámara). Solo lógica de
# enrutamiento: nada de píxeles (límite documentado del nodo). Reglas (spec §5):
# reenviar si (1) evidencia de persona en ventana, (2) heartbeat vencido,
# (3) NN muda hace >= stall (fail-open), (4) warm-up sin resultados de NN.
_GATE_SCRIPT_TEMPLATE = '''
import time
import json

CONFIDENCE = __CONFIDENCE__
KEEPALIVE_S = __KEEPALIVE_S__
HEARTBEAT_S = __HEARTBEAT_S__
STALL_S = __STALL_S__
PERSON_LABEL = 1  # person-detection-retail-0013: 0=background, 1=person
STATS_PERIOD_S = 1.0

NEG = -1000000.0
last_person_t = NEG
last_nn_t = NEG
last_sent_t = NEG
nn_results = 0
seen = 0
forwarded = 0
dropped_no_person = 0
by_reason = {"person": 0, "heartbeat": 0, "failopen": 0, "warmup": 0}
last_stats_t = time.monotonic()

while True:
    dets = node.io["detections"].tryGet()
    while dets is not None:
        nn_results += 1
        last_nn_t = time.monotonic()
        for d in dets.detections:
            if d.label == PERSON_LABEL and d.confidence >= CONFIDENCE:
                last_person_t = last_nn_t
                break
        dets = node.io["detections"].tryGet()
    frame = node.io["frames"].get()
    seen += 1
    now = time.monotonic()
    if nn_results == 0:
        reason = "warmup"
    elif now - last_person_t <= KEEPALIVE_S:
        reason = "person"
    elif now - last_nn_t >= STALL_S:
        reason = "failopen"
    elif now - last_sent_t >= HEARTBEAT_S:
        reason = "heartbeat"
    else:
        reason = None
    if reason is None:
        dropped_no_person += 1
    else:
        node.io["out"].send(frame)
        forwarded += 1
        by_reason[reason] += 1
        last_sent_t = now
    if now - last_stats_t >= STATS_PERIOD_S:
        payload = json.dumps({
            "seen": seen,
            "forwarded": forwarded,
            "dropped_no_person": dropped_no_person,
            "forwarded_by_reason": by_reason,
            "nn_results": nn_results,
        }).encode()
        buf = Buffer(len(payload))
        buf.setData(payload)
        node.io["stats"].send(buf)
        last_stats_t = now
'''
```

Método en `OakDSource`:

```python
    def _render_gate_script(self) -> str:
        """Interpola SOLO números ya validados por el schema (sin inyección)."""
        cfg = self.prefilter
        return (
            _GATE_SCRIPT_TEMPLATE
            .replace("__CONFIDENCE__", repr(float(cfg.confidence)))
            .replace("__KEEPALIVE_S__", repr(cfg.keepalive_window_ms / 1000.0))
            .replace("__HEARTBEAT_S__", repr(cfg.heartbeat_interval_ms / 1000.0))
            .replace("__STALL_S__", repr(cfg.stall_failopen_ms / 1000.0))
        )
```

Constructor: agregar los kwargs `prefilter: "OakDPrefilterConfig | None" = None` y `_skip_blob_check: bool = False`, guardando `self.prefilter = prefilter` y `self._skip_blob_check = _skip_blob_check` (import de `OakDPrefilterConfig` desde `eovrt_media.config.schemas`, junto a los imports existentes de ese módulo).

- [ ] **Step 4: Verificar y ajustar aserciones acotadas**

Run: `pytest tests/test_oak_d_prefilter_gate.py -q -x`
Expected: PASS. Si `test_no_person_drops_until_heartbeat` o `test_nn_stall_fails_open` fallan por ±1 frame, razonar el timeline tick a tick y fijar la aserción EXACTA (reemplazar el rango por `== N` con el N correcto): el objetivo es un test determinista, no uno laxo.

- [ ] **Step 5: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde.

---

### Task 6: Pipeline prefiltrado on-device + cola de stats + watchdog escalado + fail-fast

**Files:**
- Modify: `src/eovrt_media/sources/oak_d_source.py` (`_build_pipeline` bifurca; `__iter__` drena stats; blob check en `__init__`)
- Modify: `src/eovrt_media/sources/registry.py` (pasar `prefilter`)
- Test: `tests/test_oak_d_source.py`

**Interfaces:**
- Consumes: `_render_gate_script()` (Task 5), `OakDPrefilterConfig` (Task 1).
- Produces: `OakDSource.prefilter_stats: dict | None` y `OakDSource.prefilter_stats_at: float | None` (reloj `time.monotonic()`), consumidos por Task 7. Streams del device: `"rgb"` (existente) y `"prefilter_stats"` (nuevo, `maxSize=4, blocking=False`).

- [ ] **Step 1: Tests que fallan**

Extender los fakes de `tests/test_oak_d_source.py`:

```python
class _FakeStatsQueue:
    """Cola prefilter_stats: entrega los payloads dados y después None."""

    def __init__(self, payloads: list[bytes]) -> None:
        self._payloads = list(payloads)

    def tryGet(self):
        if not self._payloads:
            return None
        data = self._payloads.pop(0)
        return SimpleNamespace(getData=lambda: data)
```

`_FakeDevice` pasa a rutear por nombre (reemplaza el assert de la línea 53):

```python
class _FakeDevice:
    def __init__(self, queue: _FakeQueue, queue_fails: bool = False,
                 stats_queue: "_FakeStatsQueue | None" = None) -> None:
        self.queue = queue
        self.stats_queue = stats_queue or _FakeStatsQueue([])
        self.closed = False
        self._queue_fails = queue_fails

    def getOutputQueue(self, name: str, maxSize: int, blocking: bool):
        if self._queue_fails:
            raise RuntimeError("X_LINK: no se pudo abrir la cola")
        if name == "rgb":
            assert maxSize == 1
            return self.queue
        if name == "prefilter_stats":
            assert maxSize == 4 and blocking is False
            return self.stats_queue
        raise AssertionError(f"stream inesperado: {name}")
```

`_fake_dai`: agregar a `node`: `MobileNetDetectionNetwork=object, Script=object`. `_FakeNode`: agregar en `__init__`: `self.preview = SimpleNamespace(link=lambda _inp: None)`, `self.out = SimpleNamespace(link=lambda _inp: None)`, `self.inputs = {}`, `self.outputs = {}` — y hacer que `inputs`/`outputs` devuelvan nodos-sumidero:

```python
        _sink = lambda: SimpleNamespace(  # noqa: E731
            setBlocking=lambda *_: None, setQueueSize=lambda *_: None,
            link=lambda *_: None,
        )
        self.inputs = defaultdict(_sink)
        self.outputs = defaultdict(_sink)
```

(import `from collections import defaultdict` arriba). Tests nuevos:

```python
import json as _json

from eovrt_media.config.schemas import OakDPrefilterConfig

_PF = OakDPrefilterConfig(enabled=True)


def test_prefilter_requires_existing_blob(tmp_path):
    with pytest.raises(FileNotFoundError, match="blob"):
        OakDSource(url="192.168.1.50",
                   prefilter=OakDPrefilterConfig(enabled=True,
                                                 model_blob=str(tmp_path / "no.blob")))


def test_prefilter_disabled_builds_plain_pipeline():
    calls: dict = {}
    source = OakDSource(url="192.168.1.50",
                        prefilter=OakDPrefilterConfig(enabled=False))
    source._build_pipeline(_fake_dai(calls))
    assert "setPreviewSize" not in calls  # EN-0 exacto con enabled: false


def test_prefilter_pipeline_configures_nn_branch(tmp_path):
    blob = tmp_path / "person.blob"
    blob.write_bytes(b"\x00")
    calls: dict = {}
    source = OakDSource(
        url="192.168.1.50",
        prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(blob), confidence=0.3),
    )
    source._build_pipeline(_fake_dai(calls))
    assert calls["setPreviewSize"] == (544, 320)
    assert calls["setPreviewKeepAspectRatio"] is False
    assert calls["setBlobPath"] == str(blob)
    assert calls["setConfidenceThreshold"] == 0.3
    assert "setScript" in calls and "node.io" in calls["setScript"]


def test_iter_drains_prefilter_stats(monkeypatch, tmp_path):
    blob = tmp_path / "person.blob"
    blob.write_bytes(b"\x00")
    payload = _json.dumps({"seen": 10, "forwarded": 4, "dropped_no_person": 6,
                           "forwarded_by_reason": {"person": 3, "heartbeat": 1,
                                                    "failopen": 0, "warmup": 0},
                           "nn_results": 9}).encode()
    device = _FakeDevice(_FakeQueue(n_frames=2), stats_queue=_FakeStatsQueue([payload]))
    source = _make_source(monkeypatch, [device], max_units=2,
                          prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(blob)))
    list(source)
    assert source.prefilter_stats == _json.loads(payload)
    assert source.prefilter_stats_at is not None


def test_iter_survives_corrupt_stats(monkeypatch, tmp_path):
    blob = tmp_path / "person.blob"
    blob.write_bytes(b"\x00")
    device = _FakeDevice(_FakeQueue(n_frames=1),
                         stats_queue=_FakeStatsQueue([b"not-json"]))
    source = _make_source(monkeypatch, [device], max_units=1,
                          prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(blob)))
    units = list(source)
    assert len(units) == 1 and source.prefilter_stats is None


def test_watchdog_scales_with_heartbeat():
    # heartbeat 5 s -> timeout efectivo max(10, 3*5) = 15 s (spec §6).
    src = OakDSource(url="192.168.1.50", _skip_blob_check=True,
                     prefilter=OakDPrefilterConfig(enabled=True, heartbeat_interval_ms=5000,
                                                    stall_failopen_ms=5000))
    assert src._no_frame_timeout_s() == 15.0
    assert OakDSource(url="192.168.1.50")._no_frame_timeout_s() == 10.0
```

`_make_source` gana pass-through de `prefilter` (ya lo hace vía `**kwargs`).

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_oak_d_source.py -q -k prefilter`
Expected: FAIL.

- [ ] **Step 3: Implementar**

En `oak_d_source.py` — imports: `import json` y `from pathlib import Path` arriba. Constructor: al final, el fail-fast (§9, fila 1):

```python
        self.prefilter = prefilter
        self.prefilter_stats: dict | None = None
        self.prefilter_stats_at: float | None = None
        if (
            prefilter is not None
            and prefilter.enabled
            and not _skip_blob_check
        ):
            blob = Path(prefilter.model_blob)
            if not blob.is_absolute():
                # Convención de pesos: relativo a la raíz del repo.
                blob = Path(__file__).resolve().parents[3] / prefilter.model_blob
            if not blob.is_file():
                raise FileNotFoundError(
                    f"prefilter.model_blob no encontrado: {blob}. "
                    "Correr `make download-prefilter-blob` (fail-fast: nunca "
                    "degradar en silencio a EN-0)."
                )
            self._blob_path = blob
```

Helper del watchdog (reemplaza los usos directos de `_NO_FRAME_TIMEOUT_S` en `__iter__`):

```python
    def _prefilter_enabled(self) -> bool:
        return self.prefilter is not None and self.prefilter.enabled

    def _no_frame_timeout_s(self) -> float:
        """Con gate activo, un silencio <= heartbeat es normal (spec §6)."""
        if self._prefilter_enabled():
            return max(_NO_FRAME_TIMEOUT_S,
                       3.0 * self.prefilter.heartbeat_interval_ms / 1000.0)
        return _NO_FRAME_TIMEOUT_S
```

`_build_pipeline` bifurca — el tramo común (chunking + cámara con resolución/fps/isp_scale/orientación) se extrae a `_build_camera(pipeline, dai)` que devuelve `cam`; la rama plana agrega el `XLinkOut "rgb"` como hoy; la rama nueva:

```python
    def _build_pipeline(self, dai: Any) -> Any:
        pipeline = dai.Pipeline()
        if self.xlink_chunk_size >= 0:
            pipeline.setXLinkChunkSize(self.xlink_chunk_size)
        cam = self._build_camera(pipeline, dai)
        xout = pipeline.create(dai.node.XLinkOut)
        xout.setStreamName("rgb")
        if not self._prefilter_enabled():
            cam.video.link(xout.input)
            return pipeline
        # Rama EN-2 (spec §5): preview full-FOV -> NN -> Script gate -> "rgb".
        cam.setPreviewSize(544, 320)          # entrada de retail-0013 (WxH)
        cam.setPreviewKeepAspectRatio(False)  # estirar: no perder bordes del FOV
        nn = pipeline.create(dai.node.MobileNetDetectionNetwork)
        nn.setBlobPath(str(self._blob_path))
        nn.setConfidenceThreshold(self.prefilter.confidence)
        nn.input.setBlocking(False)
        nn.input.setQueueSize(1)              # siempre el frame más fresco
        cam.preview.link(nn.input)
        script = pipeline.create(dai.node.Script)
        script.setScript(self._render_gate_script())
        # frames en modo freshest-only: descartar en la entrada del Script es
        # equivalente al maxSize=1 del host hoy (misma semántica EN-0).
        script.inputs["frames"].setBlocking(False)
        script.inputs["frames"].setQueueSize(1)
        cam.video.link(script.inputs["frames"])
        nn.out.link(script.inputs["detections"])
        script.outputs["out"].link(xout.input)
        xstats = pipeline.create(dai.node.XLinkOut)
        xstats.setStreamName("prefilter_stats")
        script.outputs["stats"].link(xstats.input)
        return pipeline
```

En `__iter__`: variable `stats_queue: Any = None`; al abrir el device (después de obtener la cola `rgb`, dentro del mismo try):

```python
                            if self._prefilter_enabled():
                                stats_queue = candidate.getOutputQueue(
                                    name="prefilter_stats", maxSize=4, blocking=False
                                )
```

Antes del `msg = queue.tryGet()` de cada vuelta, drenar stats:

```python
                if stats_queue is not None:
                    try:
                        stats_msg = stats_queue.tryGet()
                    except Exception:
                        stats_msg = None
                    if stats_msg is not None:
                        try:
                            self.prefilter_stats = json.loads(
                                bytes(stats_msg.getData()).decode("utf-8")
                            )
                            self.prefilter_stats_at = time.monotonic()
                        except (ValueError, UnicodeDecodeError):
                            logger.warning(
                                "prefilter_stats ilegible; se conserva el último válido"
                            )
```

Reemplazar los dos usos de `_NO_FRAME_TIMEOUT_S` del loop por `self._no_frame_timeout_s()` (guardarlo en una local al inicio del `__iter__`: `no_frame_timeout = self._no_frame_timeout_s()`), y al reconectar poner `stats_queue = None` junto con `device = None` (la cola pertenece al device muerto).

En `registry.py`, agregar `prefilter=config.source.prefilter,` a los kwargs de `OakDSource`.

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_oak_d_source.py tests/test_oak_d_prefilter_gate.py -q`
Expected: PASS completo (suite vieja intacta: la rama plana sigue produciendo las mismas llamadas).

- [ ] **Step 5: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde.

---

### Task 7: Telemetría del prefilter (`RunContext` → `summary.json`, incl. two-node)

**Files:**
- Modify: `src/eovrt_media/runtime/run_context.py:35-44`
- Modify: `src/eovrt_media/runtime/pipeline.py` (~línea 561, junto al volcado de `transport.units_dropped`)
- Modify: `src/eovrt_media/contracts/events.py` (`RunSummary`)
- Modify: `src/eovrt_media/sinks/run_artifact_writer.py` (bloque `prefilter`)
- Test: `tests/test_prefilter_summary.py` (nuevo)

**Interfaces:**
- Consumes: `OakDSource.prefilter_stats` / `.prefilter_stats_at` (Task 6); `config.source.prefilter` (Task 1); `config.topology.mode` (existente).
- Produces: `RunSummary.prefilter: dict` — siempre presente: `{"enabled": false}` sin gate; con gate: config efectiva + `counters_available: bool` + `counters` + `stats_stale: bool`; en two-node: config + `counters_available: false, reason: "two_node_v1"`.

- [ ] **Step 1: Tests que fallan**

Crear `tests/test_prefilter_summary.py`. Reutilizar la técnica de construcción de contexto/writer de los tests existentes de `write_summary` (buscar `write_summary(` bajo `tests/` y copiar el fixture de config/contexto de ahí; abajo, el esqueleto de las aserciones):

```python
"""Bloque prefilter del summary (spec §6/§8): registro de descartes EN-2."""
from __future__ import annotations

import json

from eovrt_media.config.schemas import OakDPrefilterConfig


def _read_summary(run_dir):
    return json.loads((run_dir / "summary.json").read_text())


def test_summary_without_prefilter_reports_enabled_false(make_context_and_writer):
    # Fuente image_folder (default): el bloque existe y es {"enabled": false}.
    ctx, writer, tracker = make_context_and_writer()
    writer.write_summary(tracker)
    assert _read_summary(ctx.run_dir)["prefilter"] == {"enabled": False}


def test_summary_with_prefilter_includes_config_and_counters(make_context_and_writer):
    counters = {"seen": 100, "forwarded": 40, "dropped_no_person": 60,
                "forwarded_by_reason": {"person": 30, "heartbeat": 8,
                                         "failopen": 0, "warmup": 2},
                "nn_results": 95}
    ctx, writer, tracker = make_context_and_writer(
        source_overrides={"type": "oak_d", "url": "192.168.1.50",
                          "prefilter": OakDPrefilterConfig(enabled=True).model_dump()},
    )
    ctx.prefilter_stats = counters
    ctx.prefilter_stats_age_s = 1.2
    writer.write_summary(tracker)
    block = _read_summary(ctx.run_dir)["prefilter"]
    assert block["enabled"] is True
    assert block["counters_available"] is True
    assert block["counters"] == counters
    assert block["stats_stale"] is False
    assert block["confidence"] == 0.25 and block["heartbeat_interval_ms"] == 2000


def test_summary_marks_stale_stats(make_context_and_writer):
    ctx, writer, tracker = make_context_and_writer(
        source_overrides={"type": "oak_d", "url": "192.168.1.50",
                          "prefilter": OakDPrefilterConfig(enabled=True).model_dump()},
    )
    ctx.prefilter_stats = {"seen": 1, "forwarded": 1, "dropped_no_person": 0,
                           "forwarded_by_reason": {}, "nn_results": 1}
    ctx.prefilter_stats_age_s = 42.0
    writer.write_summary(tracker)
    assert _read_summary(ctx.run_dir)["prefilter"]["stats_stale"] is True


def test_summary_two_node_declares_counters_unavailable(make_context_and_writer):
    ctx, writer, tracker = make_context_and_writer(
        source_overrides={"type": "oak_d", "url": "192.168.1.50",
                          "prefilter": OakDPrefilterConfig(enabled=True).model_dump()},
        topology_mode="two_node",
    )
    writer.write_summary(tracker)
    block = _read_summary(ctx.run_dir)["prefilter"]
    assert block["counters_available"] is False
    assert block["reason"] == "two_node_v1"
    assert "counters" not in block
```

`make_context_and_writer` es un fixture local del archivo (construirlo con el mismo patrón del test existente de `write_summary`; parámetros `source_overrides: dict | None` y `topology_mode: str | None` que se inyectan en la run config antes de crear `RunContext`).

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_prefilter_summary.py -q`
Expected: FAIL (`KeyError: 'prefilter'`).

- [ ] **Step 3: Implementar**

`run_context.py` (junto a línea 44):

```python
        self.prefilter_stats: dict | None = None
        self.prefilter_stats_age_s: float | None = None
```

`pipeline.py` — junto al volcado de `transport.units_dropped` (~línea 561), en el cierre del run:

```python
    # Telemetría EN-2 (spec §6): solo OakDSource expone estos atributos;
    # getattr con default mantiene a las demás fuentes fuera del asunto (§8.1).
    run_context.prefilter_stats = getattr(source, "prefilter_stats", None)
    stats_at = getattr(source, "prefilter_stats_at", None)
    run_context.prefilter_stats_age_s = (
        (time.monotonic() - stats_at) if stats_at is not None else None
    )
```

(`import time` ya existe en `pipeline.py`; verificar). `events.py`, en `RunSummary` debajo de `capture_to_host`:

```python
    # Bloque EN-2 (spec 2026-07-15 §6): siempre presente; {"enabled": false}
    # cuando la corrida no usa el prefilter.
    prefilter: dict = Field(default_factory=lambda: {"enabled": False})
```

`run_artifact_writer.py` — método nuevo en la clase del writer:

```python
    def _build_prefilter_block(self) -> dict:
        cfg = getattr(self.context.config.source, "prefilter", None)
        if cfg is None or not cfg.enabled:
            return {"enabled": False}
        block = {
            "enabled": True,
            "model_blob": cfg.model_blob,
            "confidence": cfg.confidence,
            "keepalive_window_ms": cfg.keepalive_window_ms,
            "heartbeat_interval_ms": cfg.heartbeat_interval_ms,
            "stall_failopen_ms": cfg.stall_failopen_ms,
        }
        if self.context.config.topology.mode == "two_node":
            # §8 flujo: el source vive en Nodo A y este writer en Nodo B; no
            # hay canal para los contadores en v1 (extensión §11.6).
            block["counters_available"] = False
            block["reason"] = "two_node_v1"
            return block
        stats = self.context.prefilter_stats
        block["counters_available"] = stats is not None
        if stats is not None:
            block["counters"] = stats
            age = self.context.prefilter_stats_age_s
            block["stats_stale"] = bool(age is not None and age > 10.0)
        return block
```

y en `write_summary`, agregar al constructor de `RunSummary`: `prefilter=self._build_prefilter_block(),`.

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_prefilter_summary.py -q && pytest tests/ -q -k summary`
Expected: PASS; los tests existentes de summary siguen verdes (campo con default ⇒ aditivo).

- [ ] **Step 5: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde.

---

### Task 8: Config de ejemplo + documentación

**Files:**
- Modify: `configs/runs/local/oak_d_camera.yaml` (git-ignorado; igual actualizarlo — es el ejemplo operativo)
- Modify: `docs/contexto/oak-d-integration.md` (sección nueva: prefilter EN-2 + latencia + provisión del blob + tuning NIC)
- Modify: `CLAUDE.md` del media-plane (una línea en la descripción de `OakDSource`)
- Modify (repo hermano `docs/`, la tesis): `docs/contexto/diseno-arquitectonico.md` — EN-2 pasa de "condicionada, fuera de alcance" a "implementada como variante opcional, default off", citando el spec. NO tocar la Tabla 57 (el riesgo sigue vigente; la mitigación ahora existe).

- [ ] **Step 1: Ejemplo de config**

Agregar a `configs/runs/local/oak_d_camera.yaml`, dentro de `source:`, comentado (default off):

```yaml
  # --- Prefilter EN-2 on-device + latencia (spec 2026-07-15) -----------------
  # xlink_chunk_size: 0          # default; -1 = chunking default del device
  # isp_scale: [3, 4]            # 1080p -> 1440x810 en el ISP (gratis)
  # prefilter:
  #   enabled: true              # requiere: make download-prefilter-blob
  #   confidence: 0.25           # bajo a propósito (fail-open)
  #   keepalive_window_ms: 1500
  #   heartbeat_interval_ms: 2000
  #   stall_failopen_ms: 3000
```

- [ ] **Step 2: Documentar en `docs/contexto/oak-d-integration.md`**

Sección "Prefilter EN-2 y latencia" con: qué es (resumen §1/§5 del spec, con link), cómo activarlo (blob + config), la regla operativa del `isp_scale` (lado corto ≥ input del OVD), la nota del tuning NIC (`sudo ethtool -C <iface> rx-usecs 1022`, recomendación oficial Luxonis para PoE), y el procedimiento de la corrida A/B de validación (spec §10, E2E manual). Redacción en el estilo del doc existente.

- [ ] **Step 3: CLAUDE.md del media-plane**

En la línea de `BaseSource`/`OakDSource` del bloque "Key abstractions", extender:

```
`OakDSource` (OAK-D Pro PoE via DepthAI, live RGB por IP fija — ver `docs/contexto/oak-d-integration.md`; opcional: prefilter EN-2 on-device y knobs de latencia, spec 2026-07-15, default off)
```

- [ ] **Step 4: Tesis (repo `docs/`)**

En `diseno-arquitectonico.md`, tabla 56 fila EN-2: actualizar el estado a implementada-opcional (default off), referenciando el spec y aclarando que la inferencia OVD sigue en el CPN (EN-3 fuera de alcance) y que los contadores de descarte en two-node quedan declarados no-disponibles en v1. Sin commits (repo local de tesis; el usuario commitea).

- [ ] **Step 5: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: verde (solo docs/config en esta task).

---

### Task 9: Compuerta de regresión final (invariantes §8)

**Files:**
- Test: `tests/test_prefilter_regression.py` (nuevo) — solo si el chequeo (c) de abajo no quedó ya cubierto por Task 1/Task 7.

- [ ] **Step 1: Verificación de invariantes**

1. Suite completa **sin haber modificado ningún test preexistente** (verificable con `git diff --stat tests/` — solo archivos nuevos y las extensiones aditivas de `test_oak_d_source.py`):
   Run: `pytest tests/ -q`
   Expected: verde, cero tests preexistentes editados fuera de `test_oak_d_source.py` (cuyas ediciones son extensiones de fakes, no cambios de aserciones existentes).
2. `make lint` limpio.
3. Corrida sintética `image_folder` + `MockDetector` (usar el patrón del test E2E existente `tests/test_pipeline_mock.py`): el `summary.json` contiene `prefilter == {"enabled": false}` y `capture_to_host == None`; `metrics.jsonl` trae `capture_to_host_ms: null` por fila; `detections.jsonl` NO tiene campos nuevos. Si `test_pipeline_mock.py` ya materializa el summary, agregar estas tres aserciones en `tests/test_prefilter_regression.py` reutilizando su fixture — sin tocar el test original.

- [ ] **Step 2: Checkpoint (sin commit)**

Run: `pytest tests/ -q && make lint`
Expected: todo verde. Los tests contra la cámara real son las Tasks 10 y 11.

---

### Task 10: Tests de hardware en código contra la cámara real

Suite pytest que corre contra la OAK-D conectada. **Gateada por env var**: sin
`EOVRT_OAK_D_HW_URL` los tests se SKIPean (CI y `make test` no la setean, así que la
suite normal no se ve afectada). **La conectividad se verifica PRIMERO**: un fixture de
sesión intenta conectar una vez; si la cámara no responde, TODOS los tests de hardware
fallan con un mensaje accionable en vez de colgarse uno por uno.

**Files:**
- Create: `scripts/check_oak_d.py` (verificador de conexión standalone)
- Create: `tests/test_oak_d_hw_e2e.py`

**Interfaces:**
- Consumes: `OakDSource` completo (Tasks 2–6), blob (Task 4).
- Produces: procedimiento reproducible `EOVRT_OAK_D_HW_URL=192.168.1.50 pytest tests/test_oak_d_hw_e2e.py -q -x`.

- [ ] **Step 1: Verificador de conexión standalone**

Crear `scripts/check_oak_d.py` (también lo usa la Task 11 como pre-check):

```python
"""Verifica conectividad con la OAK-D antes de cualquier test de hardware.

Uso: python scripts/check_oak_d.py [ip]   (default: 192.168.1.50 o EOVRT_OAK_D_HW_URL)
Sale con 0 si conecta; 1 con diagnóstico si no.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    ip = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "EOVRT_OAK_D_HW_URL", "192.168.1.50"
    )
    try:
        import depthai as dai
    except ImportError:
        print("FALTA depthai: pip install -e '.[edge]'")
        return 1
    try:
        # Pipeline vacío: solo handshake XLink por IP fija (nunca autodiscovery).
        with dai.Device(dai.Pipeline(), dai.DeviceInfo(ip)) as dev:
            cams = dev.getConnectedCameras()
            temp = dev.getChipTemperature().average
            print(f"OK: OAK-D en {ip} — cámaras: {cams}, chip: {temp:.1f}°C")
            return 0
    except Exception as exc:
        print(
            f"SIN CONEXIÓN con la OAK-D en {ip}: {exc}\n"
            "Checklist: ¿PoE con power? ¿IP correcta (reserva DHCP)? "
            "¿WSL puede alcanzar la LAN? Ver docs/contexto/oak-d-integration.md."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Suite de hardware**

Crear `tests/test_oak_d_hw_e2e.py`:

```python
"""Tests de HARDWARE contra la OAK-D real (spec §10, E2E).

Gateo: EOVRT_OAK_D_HW_URL=<ip> pytest tests/test_oak_d_hw_e2e.py -q -x
Sin la env var: SKIP (la suite normal y CI no se ven afectadas).
Con la env var pero cámara inalcanzable: FAIL inmediato en el fixture de
conexión (verificación PRIMERO; ningún test llega a colgarse esperando frames).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from eovrt_media.config.schemas import OakDPrefilterConfig
from eovrt_media.sources.oak_d_source import OakDSource

OAK_URL = os.environ.get("EOVRT_OAK_D_HW_URL")
BLOB = Path(__file__).resolve().parents[1] / "models/edge/person-detection-retail-0013_6shave.blob"

pytestmark = pytest.mark.skipif(
    not OAK_URL, reason="test de hardware: exportar EOVRT_OAK_D_HW_URL=<ip de la OAK-D>"
)


@pytest.fixture(scope="module")
def camera_reachable():
    """Handshake una sola vez ANTES de todos los tests de hardware."""
    dai = pytest.importorskip("depthai", reason="pip install -e '.[edge]'")
    try:
        with dai.Device(dai.Pipeline(), dai.DeviceInfo(OAK_URL)) as dev:
            assert dev.getConnectedCameras(), "device sin cámaras conectadas"
    except Exception as exc:
        pytest.fail(
            f"OAK-D inalcanzable en {OAK_URL}: {exc} — "
            "correr `python scripts/check_oak_d.py` para diagnóstico."
        )
    return OAK_URL


def _collect(source: OakDSource, timeout_s: float = 30.0) -> list:
    """Consume la fuente con presupuesto de tiempo (nunca colgarse)."""
    units = []
    it = iter(source)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            units.append(next(it))
        except StopIteration:
            break
        if source.max_units is not None and len(units) >= source.max_units:
            break
    source.stop()
    return units


def test_raw_stream_yields_frames_with_capture_latency(camera_reachable):
    source = OakDSource(url=camera_reachable, fps=10, max_units=5)
    units = _collect(source)
    assert len(units) == 5
    for u in units:
        assert u.pixel_data is not None and u.width > 0
        # Timesync PoE <0.5 ms; tolerar hasta 2 s por picos de red.
        assert u.capture_to_host_ms is not None
        assert 0.0 <= u.capture_to_host_ms < 2000.0


def test_isp_scale_reduces_transmitted_resolution(camera_reachable):
    source = OakDSource(url=camera_reachable, fps=10, isp_scale=(1, 2), max_units=1)
    units = _collect(source)
    assert len(units) == 1
    assert units[0].width == 960 and units[0].height == 540  # 1080p * 1/2


@pytest.mark.skipif(not BLOB.is_file(), reason="falta el blob: make download-prefilter-blob")
def test_prefilter_gate_streams_and_reports_stats(camera_reachable):
    """Agnóstico de escena: el heartbeat (2 s) garantiza flujo aunque no haya
    nadie; los contadores deben llegar y cerrar la aritmética del gate."""
    source = OakDSource(
        url=camera_reachable, fps=10, max_units=4,
        prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(BLOB)),
    )
    units = _collect(source, timeout_s=40.0)  # peor caso: 4 heartbeats + margen
    assert len(units) == 4, "el fail-open/heartbeat debe garantizar frames"
    assert source.prefilter_stats is not None, "stats del Script no llegaron"
    s = source.prefilter_stats
    assert s["seen"] == s["forwarded"] + s["dropped_no_person"]
    assert s["forwarded"] >= 4
    assert s["nn_results"] > 0, "la NN on-device no produjo resultados (¿blob?)"


@pytest.mark.skipif(not BLOB.is_file(), reason="falta el blob: make download-prefilter-blob")
def test_prefilter_empty_scene_rate_is_heartbeat_bound(camera_reachable):
    """Solo interpretable con la escena VACÍA (sin personas en el FOV): la tasa
    de paso debe colapsar a ~1 frame por heartbeat. Si hay una persona en el
    encuadre el test se auto-SKIPea usando los contadores del gate."""
    source = OakDSource(
        url=camera_reachable, fps=10, max_units=3,
        prefilter=OakDPrefilterConfig(enabled=True, model_blob=str(BLOB),
                                       heartbeat_interval_ms=2000),
    )
    t0 = time.monotonic()
    units = _collect(source, timeout_s=45.0)
    elapsed = time.monotonic() - t0
    stats = source.prefilter_stats or {}
    if stats.get("forwarded_by_reason", {}).get("person", 0) > 0:
        pytest.skip("hay una persona en el FOV: tasa no acotada por heartbeat")
    assert len(units) == 3
    # 3 frames por heartbeat de 2 s: >= ~4 s (warm-up puede acelerar el 1ro).
    assert elapsed >= 3.0, f"pasaron frames de más para escena vacía ({elapsed:.1f}s)"
```

- [ ] **Step 3: Verificar conexión y correr (con la cámara conectada)**

Run: `python scripts/check_oak_d.py` → Expected: `OK: OAK-D en 192.168.1.50 ...`
Run: `EOVRT_OAK_D_HW_URL=192.168.1.50 pytest tests/test_oak_d_hw_e2e.py -q -x`
Expected: 4 tests PASS (el de escena vacía puede SKIPear si hay alguien en el FOV).
Run: `pytest tests/ -q` (sin la env var) → Expected: los 4 aparecen como SKIP; el resto de la suite intacta.

- [ ] **Step 4: Checkpoint (sin commit)**

Run: `make lint`
Expected: limpio.

---

### Task 11: E2E real — servicio con modelo OVD + cámara + prefilter (A/B)

Corrida real de punta a punta: servicio FastAPI con **modelo OVD real** (GDINO-tiny, el
mejor del Sprint 2), cámara real, prefilter on/off. **Siempre verificar conexión
primero** (Step 1); es la corrida de validación que exige la Tabla 57 (§10 del spec).
Manual/operativo (no CI): requiere GPU o paciencia en CPU, cámara y escena controlable.

**Files:**
- Modify: `docs/contexto/oak-d-integration.md` (registrar resultados A/B)

- [ ] **Step 1: Pre-check de conexión (obligatorio antes de todo)**

Run: `python scripts/check_oak_d.py 192.168.1.50`
Expected: `OK: ...`. Si falla: NO seguir; diagnosticar con el checklist del script.

- [ ] **Step 2: Preparar pesos y blob**

Run: `make download-models && make download-prefilter-blob`
Verificar el ref exacto del catálogo: `ls configs/models/` — usar el id de GDINO-tiny
tal como figura ahí (hubo un mismatch de nombre en el pasado; no adivinar).

- [ ] **Step 3: Levantar el servicio con el modelo real**

Run (terminal aparte o background): `EOVRT_MODEL_REF=<ref-gdino-tiny> make serve`
Run: `make smoke`
Expected: `/healthz` y `/readyz` OK (readyz recién cuando el modelo terminó de cargar).

- [ ] **Step 4: Corrida A (baseline EN-0, sin prefilter)**

Disparar con el mismo body verificado en la integración OAK-D (ver
`docs/contexto/oak-d-integration.md`), fuente `oak_d` con `url: 192.168.1.50`,
`fps: 10`, prompts con al menos la clase `person`, SIN bloque `prefilter`. Dejar correr
~60 s con una persona entrando y saliendo del FOV, después `POST /api/runs/<id>/stop`.

Verificaciones sobre `runs/<run_id_A>/`:
```bash
jq '{prefilter, capture_to_host, units_processed, total_detections}' runs/<run_id_A>/summary.json
```
Expected: `prefilter == {"enabled": false}`; `capture_to_host.p50_ms` presente y
plausible (orden 30–60 ms en PoE 1080p; >0 siempre); `units_processed > 0`;
detecciones de `person` cuando hubo persona.

- [ ] **Step 5: Corrida B (EN-2, prefilter on) — mismo escenario**

Mismo body + dentro del config de la fuente:
```json
"prefilter": {"enabled": true}
```
Repetir el mismo guion de escena (~60 s, persona entra/sale, tramos de escena vacía).
`POST /api/runs/<id>/stop`.

Verificaciones sobre `runs/<run_id_B>/summary.json`:
```bash
jq '.prefilter' runs/<run_id_B>/summary.json
```
Expected: `enabled: true`, `counters_available: true`, y en `counters`:
`seen == forwarded + dropped_no_person`, `dropped_no_person > 0` (hubo tramos vacíos),
`forwarded_by_reason.person > 0` (hubo persona) y `heartbeat > 0` (tramos vacíos),
`stats_stale: false`.

- [ ] **Step 6: Comparación A/B y registro (la evidencia EN-2)**

Comparar: (a) `units_processed` B < A (menos frames inferidos) con la MISMA cobertura
de detecciones de `person` en los tramos con persona (fail-open funcionando: la
preselección no perdió evidencia); (b) tasa efectiva de frames al host en tramos
vacíos ≈ 1 por `heartbeat_interval_ms`; (c) `capture_to_host` comparable entre A y B.
Registrar la tabla A/B (run_ids, contadores, conclusión) en
`docs/contexto/oak-d-integration.md` — es el insumo del argumento de la Tabla 57.

- [ ] **Step 7: Cierre**

Parar el servicio. Run: `pytest tests/ -q && make lint` → verde. Informar resultados al
usuario y **esperar su pedido explícito para commitear**.
