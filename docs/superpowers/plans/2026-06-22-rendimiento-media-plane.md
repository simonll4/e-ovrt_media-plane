# Optimización de rendimiento del Media Plane — Implementation Plan

> **Registro:** plan ejecutado; los steps implementados quedan marcados con `- [x]`.

**Goal:** Acelerar la inferencia (fp16 + warmup) y reducir el ancho de banda del transporte de red (compresión JPEG) sin tocar contratos ni el modelo de frescura.

**Architecture:** Dos frentes desacoplados. WS1: los adaptadores GDINO/YOLOE reciben flags `half_precision`/`warmup` desde el catálogo de modelo, con helpers puros para resolver device y decidir fp16. WS2: el wire ZeroMQ se hace autodescriptivo (`payload_codec` en el header) y el productor comprime a JPEG según `transport.compression`. El camino single-host (memoria) y el patrón REQ/REP no cambian.

**Tech Stack:** Python 3.11, Pydantic v2, PyTorch, Ultralytics, HF Transformers, OpenCV (`cv2`), ZeroMQ + msgpack, pytest.

## Global Constraints

- Python 3.11; `ruff check src tests` debe quedar limpio.
- Config-driven: sin thresholds/paths hardcodeados; todo nuevo knob va por YAML.
- Commits SIN línea `Co-Authored-By`.
- fp16 debe ser **no-op en CPU** (solo se aplica cuando `device` empieza con `cuda`).
- Compresión JPEG solo afecta el camino de red; el single-host (`transport/memory.py`) NO se toca.
- Frontera Media/Control Plane intacta; contratos (`NormalizedUnit`, etc.) sin cambios de campos.
- Defaults de constructor de adaptador conservadores (`half_precision=False`, `warmup=False`); el factory pasa los valores del config.
- `serialize_unit` mantiene `codec="raw"` por default (compatibilidad con callers y tests existentes); solo el productor de red pide `jpeg` vía config.
- La suite vigente debe seguir verde tras cada tarea.

---

### Task 1: Codec JPEG autodescriptivo en la serialización del wire

**Files:**
- Modify: `src/eovrt_media/transport/serialization.py`
- Test: `tests/test_serialization.py`

**Interfaces:**
- Consumes: `NormalizedUnit`, `PayloadFormat` (existentes).
- Produces:
  - `serialize_unit(unit: NormalizedUnit, codec: str = "raw", quality: int = 90) -> bytes`
  - `deserialize_unit(data: bytes) -> NormalizedUnit` (lee `payload_codec` del header; default `"raw"` si ausente)

- [x] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_serialization.py`:

```python
def test_default_codec_is_raw_lossless():
    unit = _make_unit(PayloadFormat.UINT8_RGB)
    restored = deserialize_unit(serialize_unit(unit))
    assert np.array_equal(restored.payload, unit.payload)


def test_roundtrip_jpeg_uint8():
    unit = _make_unit(PayloadFormat.UINT8_RGB)
    unit.payload[:] = 120  # color sólido: diff acotado bajo compresión lossy
    restored = deserialize_unit(serialize_unit(unit, codec="jpeg", quality=90))
    assert restored.payload.dtype == np.uint8
    assert restored.payload.shape == (640, 640, 3)
    assert restored.payload_format == PayloadFormat.UINT8_RGB
    assert restored.unit_id == unit.unit_id
    assert np.allclose(restored.payload, 120, atol=3)


def test_jpeg_falls_back_to_raw_for_fp32():
    unit = _make_unit(PayloadFormat.FP32)
    restored = deserialize_unit(serialize_unit(unit, codec="jpeg", quality=90))
    assert restored.payload.dtype == np.float32
    assert np.allclose(restored.payload, unit.payload)
```

- [x] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_serialization.py -v`
Expected: FAIL — `serialize_unit() got an unexpected keyword argument 'codec'`.

- [x] **Step 3: Implementar el codec**

Reemplazar el contenido de `serialize_unit` y `deserialize_unit` en `src/eovrt_media/transport/serialization.py`, y agregar imports/logger al tope del archivo (debajo de `import struct`):

```python
import logging

import cv2

logger = logging.getLogger(__name__)
```

`serialize_unit`:

```python
def serialize_unit(unit: NormalizedUnit, codec: str = "raw", quality: int = 90) -> bytes:
    """Empaqueta una NormalizedUnit como header msgpack + payload (raw o JPEG)."""
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
    if codec == "jpeg" and unit.payload_format == PayloadFormat.UINT8_RGB:
        ok, buf = cv2.imencode(".jpg", unit.payload, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise ValueError("cv2.imencode falló al comprimir el payload a JPEG")
        payload_bytes = buf.tobytes()
        meta["payload_codec"] = "jpeg"
    else:
        if codec == "jpeg":
            logger.warning(
                "codec=jpeg ignorado para payload_format=%s; usando raw",
                unit.payload_format.value,
            )
        payload_bytes = np.ascontiguousarray(unit.payload).tobytes()
        meta["payload_codec"] = "raw"
    header = msgpack.packb(meta, use_bin_type=True)
    return struct.pack(">I", len(header)) + header + payload_bytes
```

`deserialize_unit`:

```python
def deserialize_unit(data: bytes) -> NormalizedUnit:
    """Reconstruye una NormalizedUnit desde el formato de wire (raw o JPEG)."""
    (header_len,) = struct.unpack(">I", data[:4])
    header = data[4 : 4 + header_len]
    payload_bytes = data[4 + header_len :]
    meta = msgpack.unpackb(header, raw=False)

    fmt = PayloadFormat(meta["payload_format"])
    target_h, target_w = meta["target_size"]
    codec = meta.get("payload_codec", "raw")

    if codec == "jpeg":
        payload = cv2.imdecode(np.frombuffer(payload_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if payload is None:
            raise ValueError("cv2.imdecode falló al descomprimir el payload JPEG")
    else:
        dtype = _DTYPE_BY_FORMAT[fmt]
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

- [x] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_serialization.py -v`
Expected: PASS (incluidos los tests existentes que validan el default low-level/lossless).

- [x] **Step 5: Commit**

```bash
git add src/eovrt_media/transport/serialization.py tests/test_serialization.py
git commit -m "feat(transport): codec JPEG autodescriptivo en el wire (fallback raw)"
```

---

### Task 2: Config de compresión + cableado por el transporte de red

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (sección `TransportConfig`)
- Modify: `src/eovrt_media/transport/network.py` (`NetworkTransportAdapter`)
- Modify: `src/eovrt_media/transport/factory.py` (`create_transport`)
- Modify: `src/eovrt_media/runtime/two_node.py` (`run_node_a`)
- Test: `tests/test_transport_compression.py` (crear)

**Interfaces:**
- Consumes: `serialize_unit(unit, codec, quality)` (Task 1).
- Produces:
  - `CompressionConfig(codec: str = "jpeg", quality: int = 90)`
  - `TransportConfig.compression: CompressionConfig`
  - `NetworkTransportAdapter(..., codec: str = "jpeg", quality: int = 90)`
  - `create_transport(..., codec=..., quality=...)` (vía `**kwargs`)

- [x] **Step 1: Escribir los tests que fallan**

Crear `tests/test_transport_compression.py`:

```python
from eovrt_media.config.schemas import TransportConfig
import eovrt_media.transport.factory as factory


def test_transport_compression_defaults():
    t = TransportConfig()
    assert t.compression.codec == "jpeg"
    assert t.compression.quality == 90


def test_create_transport_threads_codec_to_network(monkeypatch):
    captured = {}

    class FakeNet:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(factory, "NetworkTransportAdapter", FakeNet)
    factory.create_transport(
        backend="network",
        role="producer",
        endpoint="tcp://127.0.0.1:5599",
        codec="jpeg",
        quality=80,
    )
    assert captured["codec"] == "jpeg"
    assert captured["quality"] == 80
```

- [x] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_transport_compression.py -v`
Expected: FAIL — `TransportConfig` no tiene atributo `compression`; `FakeNet` no recibe `codec`.

- [x] **Step 3: Implementar config + cableado**

En `src/eovrt_media/config/schemas.py`, agregar antes de `class TransportConfig`:

```python
class CompressionConfig(BaseModel):
    """Compresión del payload en el transporte de red."""

    codec: str = "jpeg"  # jpeg | raw
    quality: int = 90  # 1-100, solo si codec=jpeg
```

Y dentro de `class TransportConfig`, agregar el campo:

```python
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
```

En `src/eovrt_media/transport/network.py`, en `NetworkTransportAdapter.__init__`, agregar los parámetros (después de `max_staleness_ms`):

```python
        codec: str = "jpeg",
        quality: int = 90,
```

y guardarlos al inicio del cuerpo del `__init__` (junto a `self.role = role`):

```python
        self.codec = codec
        self.quality = quality
```

En el mismo archivo, en `_serve`, cambiar la línea de envío del frame:

```python
                sock.send(serialize_unit(item, codec=self.codec, quality=self.quality))
```

En `src/eovrt_media/transport/factory.py`, en la rama `backend == "network"`, agregar a la construcción de `NetworkTransportAdapter`:

```python
            codec=kwargs.get("codec", _NETWORK_COMPRESSION_DEFAULTS.codec),
            quality=kwargs.get("quality", _NETWORK_COMPRESSION_DEFAULTS.quality),
```

En `src/eovrt_media/runtime/two_node.py`, en `run_node_a`, agregar a la llamada `create_transport(...)` del productor:

```python
        codec=config.transport.compression.codec,
        quality=config.transport.compression.quality,
```

- [x] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_transport_compression.py tests/test_network_transport.py -v`
Expected: PASS. El default canónico de transporte de red es `jpeg`; `serialize_unit`
mantiene `raw` como default low-level/lossless.

- [x] **Step 5: Commit**

```bash
git add src/eovrt_media/config/schemas.py src/eovrt_media/transport/network.py src/eovrt_media/transport/factory.py src/eovrt_media/runtime/two_node.py tests/test_transport_compression.py
git commit -m "feat(transport): config transport.compression y cableado JPEG en Nodo A"
```

---

### Task 3: Config de runtime del modelo + helpers + factory

**Files:**
- Create: `src/eovrt_media/models/runtime_utils.py`
- Modify: `src/eovrt_media/config/schemas.py` (sección `ModelSection`)
- Modify: `src/eovrt_media/models/__init__.py` (`create_adapter`)
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py` (`__init__`)
- Modify: `src/eovrt_media/models/yoloe_adapter.py` (`__init__`)
- Test: `tests/test_runtime_utils.py` (crear), `tests/test_model_factory_runtime.py` (crear)

**Interfaces:**
- Produces:
  - `resolve_device(requested: str, cuda_available: bool | None = None) -> str`
  - `should_use_half(device: str, half_precision: bool) -> bool`
  - `make_warmup_image(target_size: tuple[int, int]) -> np.ndarray` (uint8, shape `(H, W, 3)`)
  - `ModelRuntimeConfig(half_precision: bool = True, warmup: bool = True)`
  - `ModelSection.runtime: ModelRuntimeConfig`
  - Adaptadores `GroundingDinoHFAdapter` y `YOLOEUltralyticsAdapter` con `half_precision: bool = False`, `warmup: bool = False` en su `__init__` (atributos `self.half_precision`, `self.warmup`).

- [x] **Step 1: Escribir los tests que fallan**

Crear `tests/test_runtime_utils.py`:

```python
import numpy as np

from eovrt_media.models.runtime_utils import (
    make_warmup_image,
    resolve_device,
    should_use_half,
)


def test_resolve_device_cuda_falls_back_to_cpu_without_gpu():
    assert resolve_device("cuda", cuda_available=False) == "cpu"
    assert resolve_device("cuda:0", cuda_available=False) == "cpu"


def test_resolve_device_keeps_cuda_when_available():
    assert resolve_device("cuda", cuda_available=True) == "cuda"


def test_resolve_device_keeps_cpu():
    assert resolve_device("cpu", cuda_available=False) == "cpu"
    assert resolve_device("cpu", cuda_available=True) == "cpu"


def test_should_use_half():
    assert should_use_half("cuda", True) is True
    assert should_use_half("cuda:0", True) is True
    assert should_use_half("cuda", False) is False
    assert should_use_half("cpu", True) is False


def test_make_warmup_image():
    img = make_warmup_image((800, 640))
    assert img.shape == (800, 640, 3)
    assert img.dtype == np.uint8
```

Crear `tests/test_model_factory_runtime.py`:

```python
from eovrt_media.config.schemas import ModelSection
from eovrt_media.models import create_adapter


def test_model_runtime_defaults():
    m = ModelSection(adapter="yoloe")
    assert m.runtime.half_precision is True
    assert m.runtime.warmup is True


def test_factory_passes_runtime_to_yoloe():
    m = ModelSection(adapter="yoloe", device="cpu", runtime={"half_precision": False, "warmup": False})
    adapter = create_adapter(m)
    assert adapter.half_precision is False
    assert adapter.warmup is False


def test_factory_passes_runtime_to_gdino():
    m = ModelSection(adapter="grounding_dino", device="cpu", runtime={"half_precision": True, "warmup": True})
    adapter = create_adapter(m)
    assert adapter.half_precision is True
    assert adapter.warmup is True
```

- [x] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_runtime_utils.py tests/test_model_factory_runtime.py -v`
Expected: FAIL — módulo `runtime_utils` inexistente; `ModelSection` sin `runtime`.

- [x] **Step 3: Implementar helpers, config y factory**

Crear `src/eovrt_media/models/runtime_utils.py`:

```python
"""Helpers de runtime para adaptadores de modelo (device, fp16, warmup)."""
from __future__ import annotations

import logging

import numpy as np
import torch

logger = logging.getLogger(__name__)


def resolve_device(requested: str, cuda_available: bool | None = None) -> str:
    """Normaliza el device: degrada a cpu si se pide cuda y no hay GPU."""
    if cuda_available is None:
        cuda_available = torch.cuda.is_available()
    if requested.startswith("cuda") and not cuda_available:
        logger.warning("device=%s solicitado sin CUDA disponible; usando cpu", requested)
        return "cpu"
    return requested


def should_use_half(device: str, half_precision: bool) -> bool:
    """fp16 solo cuando el flag está activo y el device es CUDA."""
    return bool(half_precision) and device.startswith("cuda")


def make_warmup_image(target_size: tuple[int, int]) -> np.ndarray:
    """Imagen negra uint8 (H, W, 3) para el warmup del modelo."""
    h, w = target_size
    return np.zeros((h, w, 3), dtype=np.uint8)
```

En `src/eovrt_media/config/schemas.py`, agregar antes de `class ModelSection`:

```python
class ModelRuntimeConfig(BaseModel):
    """Knobs de runtime del modelo (rendimiento)."""

    half_precision: bool = True  # fp16 cuando device=cuda; ignorado en cpu
    warmup: bool = True  # inferencia dummy al cargar
```

Y dentro de `class ModelSection`, agregar el campo (después de `device: str = "cpu"`):

```python
    runtime: ModelRuntimeConfig = Field(default_factory=ModelRuntimeConfig)
```

En `src/eovrt_media/models/grounding_dino_adapter.py`, ampliar `__init__` con dos parámetros (después de `local_dir`):

```python
        half_precision: bool = False,
        warmup: bool = False,
```

y guardarlos en el cuerpo (después de `self.local_dir = local_dir`):

```python
        self.half_precision = half_precision
        self.warmup = warmup
```

En `src/eovrt_media/models/yoloe_adapter.py`, ampliar `__init__` con (después de `image_size`):

```python
        half_precision: bool = False,
        warmup: bool = False,
```

y guardarlos (después de `self.image_size = image_size`):

```python
        self.half_precision = half_precision
        self.warmup = warmup
```

En `src/eovrt_media/models/__init__.py`, pasar los flags en el factory. Para `grounding_dino`:

```python
            local_dir=model_config.local_dir,
            half_precision=model_config.runtime.half_precision,
            warmup=model_config.runtime.warmup,
```

Para `yoloe`:

```python
            image_size=model_config.image_size,
            half_precision=model_config.runtime.half_precision,
            warmup=model_config.runtime.warmup,
```

- [x] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_runtime_utils.py tests/test_model_factory_runtime.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/eovrt_media/models/runtime_utils.py src/eovrt_media/config/schemas.py src/eovrt_media/models/__init__.py src/eovrt_media/models/grounding_dino_adapter.py src/eovrt_media/models/yoloe_adapter.py tests/test_runtime_utils.py tests/test_model_factory_runtime.py
git commit -m "feat(models): config runtime (half_precision/warmup) + helpers de device/fp16"
```

---

### Task 4: GDINO — fp16 (autocast) + warmup + resolución de device

**Files:**
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py` (`load`, `predict`)
- Test: `tests/test_gdino_runtime.py` (crear)

**Interfaces:**
- Consumes: `resolve_device`, `should_use_half`, `make_warmup_image` (Task 3); `self.half_precision`, `self.warmup` (Task 3).
- Produces: comportamiento — `load()` resuelve device y opcionalmente hace warmup; `predict()` envuelve el forward en autocast fp16 cuando corresponde.

- [x] **Step 1: Escribir el test que falla**

Crear `tests/test_gdino_runtime.py`:

```python
from unittest.mock import MagicMock

import torch

import eovrt_media.models.grounding_dino_adapter as gd
from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter


def test_gdino_load_resolves_cuda_to_cpu_without_gpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(gd, "AutoProcessor", MagicMock())
    fake_model = MagicMock()
    fake_cls = MagicMock()
    fake_cls.from_pretrained.return_value.to.return_value = fake_model
    monkeypatch.setattr(gd, "AutoModelForZeroShotObjectDetection", fake_cls)

    adapter = GroundingDinoHFAdapter(device="cuda", warmup=False)
    adapter.load()

    assert adapter.device == "cpu"
```

- [x] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_gdino_runtime.py -v`
Expected: FAIL — `adapter.device` sigue siendo `"cuda"` (load aún no resuelve device).

- [x] **Step 3: Implementar autocast + warmup + device en GDINO**

En `src/eovrt_media/models/grounding_dino_adapter.py`, agregar import al tope (después de `import warnings`):

```python
from contextlib import nullcontext
```

y el import de helpers (junto a los otros `from eovrt_media...`):

```python
from eovrt_media.models.runtime_utils import (
    make_warmup_image,
    resolve_device,
    should_use_half,
)
```

Reemplazar el cuerpo de `load()` por:

```python
    def load(self) -> None:
        """Carga el processor y modelo en el dispositivo configurado."""
        self.device = resolve_device(self.device)
        source = self.local_dir if self.local_dir and Path(self.local_dir).exists() else self.model_id
        logger.info(f"Cargando Grounding DINO desde: {source} → {self.device}")

        self.processor = AutoProcessor.from_pretrained(source)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(source).to(self.device)
        self.model.eval()

        if self.warmup:
            from PIL import Image as _Image

            dummy = _Image.fromarray(make_warmup_image(self.input_spec.target_size))
            self.predict(dummy, ["object"])

        logger.info("Grounding DINO cargado correctamente.")
```

En `predict()`, reemplazar el bloque del forward:

```python
        with torch.no_grad():
            outputs = self.model(**inputs)
```

por:

```python
        amp = (
            torch.autocast("cuda", dtype=torch.float16)
            if should_use_half(self.device, self.half_precision)
            else nullcontext()
        )
        with torch.no_grad(), amp:
            outputs = self.model(**inputs)
```

- [x] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_gdino_runtime.py -v`
Expected: PASS.

- [x] **Step 5: Validación manual (GPU/BENCH) — anotar, no automatizable en CI**

En la máquina con RTX 4060: correr un experimento DBE single-host con `runtime.half_precision: true` y comparar `summary.json` (p50/p95/p99, fps_effective) contra una corrida `half_precision: false`. Confirmar contra el BENCH que el AP no se degrada de forma significativa (fijar `half_precision` en la corrida canónica). Documentar el antes/después.

- [x] **Step 6: Commit**

```bash
git add src/eovrt_media/models/grounding_dino_adapter.py tests/test_gdino_runtime.py
git commit -m "perf(gdino): autocast fp16 + warmup + resolución de device"
```

---

### Task 5: YOLOE — fp16 (half) + warmup + validación de device

**Files:**
- Modify: `src/eovrt_media/models/yoloe_adapter.py` (`load`, `predict`)
- Test: `tests/test_yoloe_runtime.py` (crear)

**Interfaces:**
- Consumes: `resolve_device`, `should_use_half`, `make_warmup_image` (Task 3); `self.half_precision`, `self.warmup`.
- Produces: comportamiento — `load()` resuelve device y opcionalmente hace warmup; `predict()` pasa `half=True` a Ultralytics cuando corresponde.

- [x] **Step 1: Escribir los tests que fallan**

Crear `tests/test_yoloe_runtime.py`:

```python
from unittest.mock import MagicMock

from PIL import Image

from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter


def _fake_model():
    fake = MagicMock()
    result = MagicMock()
    result.boxes = None
    fake.predict.return_value = [result]
    return fake


def test_yoloe_passes_half_on_cuda():
    adapter = YOLOEUltralyticsAdapter(device="cuda", half_precision=True)
    adapter.model = _fake_model()
    adapter.predict(Image.new("RGB", (8, 8)), ["person"])
    assert adapter.model.predict.call_args.kwargs["half"] is True


def test_yoloe_no_half_on_cpu():
    adapter = YOLOEUltralyticsAdapter(device="cpu", half_precision=True)
    adapter.model = _fake_model()
    adapter.predict(Image.new("RGB", (8, 8)), ["person"])
    assert adapter.model.predict.call_args.kwargs["half"] is False
```

- [x] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_yoloe_runtime.py -v`
Expected: FAIL — `KeyError: 'half'` (predict_kwargs aún no incluye `half`).

- [x] **Step 3: Implementar half + warmup + device en YOLOE**

En `src/eovrt_media/models/yoloe_adapter.py`, agregar el import de helpers (junto a los otros `from eovrt_media...`):

```python
from eovrt_media.models.runtime_utils import (
    make_warmup_image,
    resolve_device,
    should_use_half,
)
```

Reemplazar el cuerpo de `load()` por:

```python
    def load(self) -> None:
        """Carga el modelo YOLOE desde el checkpoint."""
        from ultralytics import YOLOE

        self.device = resolve_device(self.device)
        logger.info(f"Cargando YOLOE desde: {self.weights} → {self.device}")
        self.model = YOLOE(self.weights)

        if self.warmup:
            dummy = Image.fromarray(make_warmup_image((640, 640)))
            self.predict(dummy, ["object"])

        logger.info("YOLOE cargado correctamente.")
```

En `predict()`, dentro de `predict_kwargs`, agregar la clave `half` (después de `"verbose": False,`):

```python
            "half": should_use_half(self.device, self.half_precision),
```

- [x] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_yoloe_runtime.py -v`
Expected: PASS.

- [x] **Step 5: Validación manual (GPU/BENCH) — anotar**

Igual que Task 4: comparar `summary.json` con `half_precision` on/off en la RTX 4060 y validar AP del BENCH sin regresión. Documentar antes/después.

- [x] **Step 6: Commit**

```bash
git add src/eovrt_media/models/yoloe_adapter.py tests/test_yoloe_runtime.py
git commit -m "perf(yoloe): half=True fp16 + warmup + validación de device"
```

---

### Task 6: (Guarded) Reducción de copia — numpy directo en GDINO

> **Riesgo:** toca el preproceso de la librería. Cambio aislado a propósito para que un revisor lo pueda rechazar sin afectar Tasks 4–5. Si la validación contra el BENCH muestra regresión de AP, **revertir esta tarea**.
>
> **Solo GDINO.** YOLOE queda fuera: Ultralytics interpreta un `np.ndarray` como **BGR**, pero nuestro payload es RGB (`UINT8_RGB`). El path PIL actual de YOLOE (`Image.fromarray`, RGB) ya es correcto en color y la copia es barata; convertir RGB→BGR para alimentar numpy reintroduciría una copia y riesgo de color. El processor de HF para GDINO sí espera RGB, así que ahí el numpy directo es seguro.

**Files:**
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py` (`predict`, `forward`)
- Test: `tests/test_gdino_runtime.py`

**Interfaces:**
- Consumes: `NormalizedUnit.payload` (numpy uint8/float, RGB).
- Produces: `GroundingDinoHFAdapter.predict()` y `forward()` aceptan `np.ndarray` sin pasar por `Image.fromarray`.

- [x] **Step 1: Escribir el test que falla (GDINO acepta numpy en predict)**

Agregar a `tests/test_gdino_runtime.py` (asegurar `import numpy as np` y `import pytest` al tope):

```python
def test_gdino_predict_accepts_numpy():
    adapter = GroundingDinoHFAdapter(device="cpu")
    # processor que explota al ser invocado: confirma que pasamos el guard de tipo
    adapter.processor = MagicMock(side_effect=RuntimeError("reached processor"))
    adapter.model = MagicMock()
    with pytest.raises(RuntimeError, match="reached processor"):
        adapter.predict(np.zeros((8, 8, 3), dtype=np.uint8), ["person"])
```

- [x] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_gdino_runtime.py::test_gdino_predict_accepts_numpy -v`
Expected: FAIL — `TypeError: Tipo de imagen no soportado: <class 'numpy.ndarray'>` (el guard de tipo rechaza numpy antes de llegar al processor).

- [x] **Step 3: Implementar numpy directo en GDINO**

En `src/eovrt_media/models/grounding_dino_adapter.py`, en `predict()`, reemplazar el bloque de validación de imagen:

```python
        # Asegurar que image es PIL
        if isinstance(image, Path):
            image = Image.open(image).convert("RGB")
        elif not isinstance(image, Image.Image):
            raise TypeError(f"Tipo de imagen no soportado: {type(image)}")
```

por:

```python
        # Aceptar Path, PIL o numpy RGB (evita copia PIL en el hot path)
        if isinstance(image, Path):
            image = Image.open(image).convert("RGB")
        elif not isinstance(image, (Image.Image, np.ndarray)):
            raise TypeError(f"Tipo de imagen no soportado: {type(image)}")
```

En el mismo `predict()`, reemplazar el cálculo de `target_sizes`:

```python
                target_sizes=[list(image.size[::-1])],  # [height, width]
```

por:

```python
                target_sizes=[
                    [image.shape[0], image.shape[1]]
                    if isinstance(image, np.ndarray)
                    else [image.size[1], image.size[0]]
                ],  # [height, width]
```

Y reemplazar `forward()` (pasar el payload numpy sin `Image.fromarray`):

```python
    def forward(self, unit: NormalizedUnit, prompts: list[str]) -> list[RawDetection]:
        """Ejecuta la inferencia desde el payload normalizado del canal."""
        payload = unit.payload
        if payload.dtype != np.uint8:
            payload = np.clip(payload * 255.0, 0, 255).astype(np.uint8)
        return self.predict(payload, prompts)
```

(YOLOE no se toca en esta tarea — ver nota de riesgo arriba.)

- [x] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_gdino_runtime.py -v`
Expected: PASS.

- [x] **Step 5: Validación manual (BENCH) — anotar, gate de regresión**

Correr el BENCH single-host antes/después de esta tarea para GDINO. Si el AP@0.5 cae de forma significativa (más allá del ruido de fp16 ya medido), **revertir esta tarea** (`git revert`). Documentar el resultado.

- [x] **Step 6: Commit**

```bash
git add src/eovrt_media/models/grounding_dino_adapter.py tests/test_gdino_runtime.py
git commit -m "perf(gdino): aceptar numpy RGB en predict/forward (evita copia PIL)"
```

---

## Cierre

- [x] **Suite completa + lint**

Run: `make test && make lint`
Expected: toda la suite vigente verde; `ruff` limpio.

- [x] **Documentación**

Actualizar `docs/usage.md` / la sección de evaluación: documentar `model.runtime.half_precision`/`warmup` y `transport.compression`, y la nota de reproducibilidad (fijar `half_precision` en corridas canónicas de BENCH). Commit aparte:

```bash
git add docs/usage.md
git commit -m "docs: documentar knobs de rendimiento (runtime fp16/warmup, transport JPEG)"
```
