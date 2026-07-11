# Instrumentación G2A y timestamps de captura (media-plane)

> **EJECUTADO el 2026-07-10.** Las 4 tareas están completas. Resultados, evidencia y deuda:
> `docs/operacion/39-instrumentacion-g2a-media-plane.md` (repo `docs`).
>
> **El código de referencia de este plan tenía defectos reales**, hallados por la revisión
> adversarial y corregidos durante la ejecución. **No lo copies verbatim**: el código vigente
> es el del working tree. Los defectos: declarar la no-interpretabilidad de G2A en two-node
> solo en el summary no alcanzaba (las filas de `metrics.jsonl` seguían trayendo un número sin
> sentido — ahora `g2a_ms` es `null` por fila); `JSONLSink.write_metric` con `exclude_none=True`
> **borraba** la clave en vez de escribir `null`; la rama `not_interpretable` perdía contra
> "sin muestras" en `summarize()`; el copiado del instante de captura en `normalize_spatial`
> no tenía test (un re-estampado silencioso colapsaba G2A a cero sin que nada falle — se
> agregó el test con `sleep(20ms)`); **la mutación A del gate era vacua** tal como estaba
> escrita (`monotonic_ns() − 0` sigue siendo positivo — se endureció con
> `capture_monotonic_ns > 0`); y un comentario justificaba un import perezoso con un ciclo de
> imports inexistente. Ver doc 39 §6.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el media-plane persista los insumos de `t_capture→alert` (spec 40 §5.2.4): el
instante de captura de cada unidad, la métrica compuesta G2A por unidad, y el tipo de reloj que
emite cada fuente.

**Architecture:** El instante de captura se estampa **donde se lee la unidad** — en el
`VisualUnit`, vía `default_factory`, así ninguna fuente puede olvidarse. Viaja por
`NormalizedUnit` y, en two-node, por el header msgpack del transporte. El consumidor cierra la
compuesta G2A al terminar la inferencia. El summary declara `source_clock` (qué reloj emite la
fuente), los percentiles de G2A contra el presupuesto 50–250 ms, y su **estado de aplicabilidad**
(en two-node los relojes monotónicos de dos hosts no son comparables).

**Tech Stack:** Python 3.11+, Pydantic v2, msgpack (header de wire), pytest, ruff.

## Global Constraints

- **Nunca commitear sin pedido explícito del usuario en ese turno.** Los pasos "Commit" se
  ejecutan sólo si lo pide. Nunca `Co-Authored-By`. Nada en GitHub.
- **Contratos SIEMPRE aditivos, sin bump de `schema_version`.** Los campos nuevos llevan default,
  de modo que un `metrics.jsonl` o un `summary.json` viejo siga validando.
- **`capture_monotonic_ns` marca cuándo el proceso LEYÓ la unidad** (spec 42 §5.1), en los tres
  regímenes de fuente. No es el timestamp de la fuente: ése ya viaja en `timestamp_ms`.
- **`source_clock` por fuente** (spec 42 §5.1), vocabulario cerrado:
  | Fuente | `source_type` | `timestamp_ms` | `source_clock` |
  |---|---|---|---|
  | `RtspSource` | `video_frame` | wall-clock de llegada | `wallclock` |
  | `VideoFileSource` | `video_frame` | **tiempo de medio** | `media` |
  | `ImageFolderSource` | `image` | `None` | `none` |
  | `OakDSource` | `video_frame` | wall-clock | `wallclock` |
- **Presupuesto G2A declarado: 50–250 ms** (spec 40 §5.1). El summary lo reporta y dice si el P95
  entra.
- **Warm-up excluido y declarado** (`warmup_units`, spec 42 §5). Default `0` ⇒ comportamiento actual.
- **En two-node, G2A cruza relojes de dos hosts.** `time.monotonic()` es del sistema, no comparable
  entre máquinas. El summary debe declarar `not_interpretable` con causa `cross_node_monotonic_clock`,
  **no** publicar un número sin sentido (ADR-006).
- `ruff` `line-length = 100`, `target-version = "py311"`. Comentarios/docstrings en español; el
  repo permite tildes en los docstrings existentes, pero **evitá tildes y eñes en el código nuevo**
  para no romper la convención de los módulos vecinos.
- **Entorno:** `/home/simonll4/projects/e-ovrt_media-plane/.venv/bin/python`.
- **Baseline MEDIDA (2026-07-10):** `pytest -q` → **456 passed**; `ruff check src tests` limpio.

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `src/eovrt_media/contracts/visual_unit.py` (mod.) | `capture_monotonic_ns`, `capture_wallclock_ms`, `source_clock`. |
| `src/eovrt_media/contracts/normalized_unit.py` (mod.) | Los mismos tres campos, para que crucen el canal. |
| `src/eovrt_media/preprocessing/normalizer.py` (mod.) | Copiarlos en `normalize_spatial`. |
| `src/eovrt_media/transport/serialization.py` (mod.) | Los tres campos en el header msgpack (two-node). |
| `src/eovrt_media/sources/{base,image_folder_source,video_file_source,rtsp_source,oak_d_source}.py` (mod.) | `SOURCE_CLOCK` por clase; poblar `source_clock` en el `VisualUnit`. |
| `src/eovrt_media/contracts/metrics.py` (mod.) | `MetricSample`: los 3 campos por unidad. |
| `src/eovrt_media/contracts/events.py` (mod.) | `RunSummary`: bloque `g2a` + `source_clock` + `warmup_units`. |
| `src/eovrt_media/config/schemas.py` (mod.) | `RunSection.warmup_units`. |
| `src/eovrt_media/metrics/g2a.py` (nuevo) | Acumulador de G2A + percentiles + aplicabilidad. |
| `src/eovrt_media/runtime/pipeline.py` (mod.) | Cerrar G2A tras la inferencia; alimentar el acumulador. |
| `src/eovrt_media/runtime/two_node.py` (mod.) | Ídem en el Nodo B, con la aplicabilidad correcta. |
| `src/eovrt_media/runtime/run_context.py` (mod.) | Guardar el acumulador y `source_clock`. |
| `src/eovrt_media/sinks/run_artifact_writer.py` (mod.) | Volcar el bloque al summary. |

**Fuera de alcance** (lo hace el plan hermano del control-plane): `ts_receive_ms`,
`first_evidence_unit_id`, `alert_registered_ms`, el pattern set `cr01_cr02_v2`, y el join
`t_capture→alert` propiamente dicho (que necesita ambos lados).

---

## Task 1: El instante de captura viaja de la fuente al consumidor

**Files:**
- Modify: `src/eovrt_media/contracts/visual_unit.py`
- Modify: `src/eovrt_media/contracts/normalized_unit.py`
- Modify: `src/eovrt_media/preprocessing/normalizer.py`
- Modify: `src/eovrt_media/transport/serialization.py`
- Modify: `src/eovrt_media/sources/base.py`, `image_folder_source.py`, `video_file_source.py`, `rtsp_source.py`, `oak_d_source.py`
- Test: `tests/test_capture_timestamps.py` (nuevo)

**Interfaces:**
- Produces:
  - `VisualUnit.capture_monotonic_ns: int` (default_factory `time.monotonic_ns`)
  - `VisualUnit.capture_wallclock_ms: float` (default_factory: `time.time() * 1000.0`)
  - `VisualUnit.source_clock: str = "none"`
  - Los mismos tres en `NormalizedUnit` (mismos defaults).
  - `BaseSource.SOURCE_CLOCK: str = "none"`; `RtspSource.SOURCE_CLOCK = "wallclock"`;
    `VideoFileSource.SOURCE_CLOCK = "media"`; `ImageFolderSource.SOURCE_CLOCK = "none"`;
    `OakDSource.SOURCE_CLOCK = "wallclock"`.

**Por qué `default_factory` y no estampar en cada fuente:** el campo se puebla en el momento en que
el `VisualUnit` se construye, que es exactamente cuando la fuente leyó la unidad. Ninguna fuente
puede olvidarse, y las fuentes futuras lo heredan gratis. `source_clock` sí es una constante de
clase, así que se pasa explícitamente.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_capture_timestamps.py`:

```python
import time

import numpy as np
import pytest

from eovrt_media.contracts.normalized_unit import NormalizedUnit, PayloadFormat, ResizeTransform
from eovrt_media.contracts.visual_unit import VisualUnit
from eovrt_media.transport.serialization import deserialize_unit, serialize_unit


def _visual_unit(**overrides) -> VisualUnit:
    data = {"unit_id": "u1", "source_type": "image", "width": 64, "height": 48}
    data.update(overrides)
    return VisualUnit(**data)


def _normalized_unit(**overrides) -> NormalizedUnit:
    data = {
        "run_id": "r1",
        "unit_id": "u1",
        "source_id": "cam-1",
        "source_path": "cam-1",
        "frame_index": 0,
        "timestamp_ms": 33.3,
        "orig_width": 64,
        "orig_height": 48,
        "payload": np.zeros((8, 8, 3), dtype=np.uint8),
        "payload_format": PayloadFormat.UINT8_RGB,
        "target_size": (8, 8),
        "transform": ResizeTransform(scale_x=1.0, scale_y=1.0, pad_x=0.0, pad_y=0.0),
    }
    data.update(overrides)
    return NormalizedUnit(**data)


def test_visual_unit_stamps_capture_time_at_construction() -> None:
    before = time.monotonic_ns()
    unit = _visual_unit()
    after = time.monotonic_ns()

    assert before <= unit.capture_monotonic_ns <= after
    assert unit.capture_wallclock_ms > 0.0
    # Vocabulario cerrado; una fuente sin declararlo no miente sobre su reloj.
    assert unit.source_clock == "none"


def test_two_visual_units_have_distinct_capture_stamps() -> None:
    """Si el default_factory se evaluara una sola vez, todas las unidades
    compartirian el mismo instante de captura y el G2A seria basura."""
    first = _visual_unit(unit_id="a")
    second = _visual_unit(unit_id="b")

    assert first.capture_monotonic_ns != second.capture_monotonic_ns


def test_visual_unit_accepts_an_explicit_source_clock() -> None:
    assert _visual_unit(source_clock="wallclock").source_clock == "wallclock"


def test_normalized_unit_carries_the_capture_stamps() -> None:
    unit = _normalized_unit(capture_monotonic_ns=123, capture_wallclock_ms=456.0,
                            source_clock="media")

    assert unit.capture_monotonic_ns == 123
    assert unit.capture_wallclock_ms == 456.0
    assert unit.source_clock == "media"


def test_serialization_roundtrip_preserves_the_capture_stamps() -> None:
    """Two-node: si el header msgpack los pierde, el Nodo B no puede calcular G2A."""
    unit = _normalized_unit(capture_monotonic_ns=987654321, capture_wallclock_ms=1700.5,
                            source_clock="wallclock")

    restored = deserialize_unit(serialize_unit(unit, codec="raw"))

    assert restored.capture_monotonic_ns == 987654321
    assert restored.capture_wallclock_ms == 1700.5
    assert restored.source_clock == "wallclock"


@pytest.mark.parametrize(
    ("module", "cls_name", "expected"),
    [
        ("eovrt_media.sources.image_folder_source", "ImageFolderSource", "none"),
        ("eovrt_media.sources.video_file_source", "VideoFileSource", "media"),
        ("eovrt_media.sources.rtsp_source", "RtspSource", "wallclock"),
        ("eovrt_media.sources.oak_d_source", "OakDSource", "wallclock"),
    ],
)
def test_every_source_declares_its_clock(module, cls_name, expected) -> None:
    import importlib

    cls = getattr(importlib.import_module(module), cls_name)
    assert cls.SOURCE_CLOCK == expected
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane
.venv/bin/python -m pytest tests/test_capture_timestamps.py -q
```

Expected: FAIL — `ValidationError`/`AttributeError` por `capture_monotonic_ns` inexistente.

- [ ] **Step 3: Add the fields to `VisualUnit`**

En `src/eovrt_media/contracts/visual_unit.py`, agregar `import time` y `Field` al import de
pydantic, y los campos **después** de `source_type`:

```python
    # Instante en que el PROCESO leyo la unidad (spec 42 SS5.1). El default_factory
    # se evalua al construir el VisualUnit, que es exactamente el momento de lectura:
    # ninguna fuente puede olvidarse de estamparlo.
    capture_monotonic_ns: int = Field(default_factory=time.monotonic_ns)
    capture_wallclock_ms: float = Field(default_factory=lambda: time.time() * 1000.0)
    # Que reloj emite `timestamp_ms` esta fuente: wallclock | media | none.
    # Decide la aplicabilidad de t_capture->alert (spec 40 SS5.2.3).
    source_clock: str = "none"
```

- [ ] **Step 4: Add the fields to `NormalizedUnit` and copy them in `normalize_spatial`**

En `src/eovrt_media/contracts/normalized_unit.py`, agregar `import time`, `Field` al import, y los
campos después de `timestamp_ms`:

```python
    # Cruzan el canal productor->consumidor (y el wire, en two-node).
    capture_monotonic_ns: int = Field(default_factory=time.monotonic_ns)
    capture_wallclock_ms: float = Field(default_factory=lambda: time.time() * 1000.0)
    source_clock: str = "none"
```

En `src/eovrt_media/preprocessing/normalizer.py`, dentro del `return NormalizedUnit(...)` de
`normalize_spatial`, agregar antes de `run_id=unit.run_id`:

```python
        capture_monotonic_ns=unit.capture_monotonic_ns,
        capture_wallclock_ms=unit.capture_wallclock_ms,
        source_clock=unit.source_clock,
```

- [ ] **Step 5: Carry them over the wire (two-node)**

En `src/eovrt_media/transport/serialization.py`, dentro del dict `meta` de `serialize_unit`,
agregar después de `"timestamp_ms": unit.timestamp_ms,`:

```python
        "capture_monotonic_ns": unit.capture_monotonic_ns,
        "capture_wallclock_ms": unit.capture_wallclock_ms,
        "source_clock": unit.source_clock,
```

Y en `deserialize_unit`, dentro del `return NormalizedUnit(...)`, agregar antes de `payload=payload`:

```python
        # `.get` con default: un Nodo A viejo (sin estos campos) sigue interoperando.
        capture_monotonic_ns=meta.get("capture_monotonic_ns", 0),
        capture_wallclock_ms=meta.get("capture_wallclock_ms", 0.0),
        source_clock=meta.get("source_clock", "none"),
```

- [ ] **Step 6: Declare `SOURCE_CLOCK` in every source and populate the unit**

En `src/eovrt_media/sources/base.py`, en `class BaseSource`, agregar como atributo de clase:

```python
    # Reloj que emite `timestamp_ms` esta fuente: wallclock | media | none.
    # El default conservador es "none": una fuente que no lo declara no promete tiempo.
    SOURCE_CLOCK: str = "none"
```

En cada fuente, declarar la constante y pasarla al `VisualUnit`:

- `image_folder_source.py`: `SOURCE_CLOCK = "none"` en la clase; en el `return VisualUnit(...)`
  agregar `source_clock=self.SOURCE_CLOCK,`.
- `video_file_source.py`: `SOURCE_CLOCK = "media"`; en el `yield VisualUnit(...)` agregar
  `source_clock=self.SOURCE_CLOCK,`.
- `rtsp_source.py`: `SOURCE_CLOCK = "wallclock"`; en el `yield VisualUnit(...)` agregar
  `source_clock=self.SOURCE_CLOCK,`.
- `oak_d_source.py`: `SOURCE_CLOCK = "wallclock"` en la clase (no construye unidades: levanta
  `NotImplementedError`).

- [ ] **Step 7: Run the new tests**

```bash
.venv/bin/python -m pytest tests/test_capture_timestamps.py -q
```

Expected: PASS (9 passed: 5 + 4 parametrizados).

- [ ] **Step 8: Full suite — nada cambió de comportamiento**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests
```

Expected: `465 passed` (456 + 9), `All checks passed!`. Los tests sensibles son
`tests/test_network_transport.py`, `tests/test_two_node.py` y `tests/test_normalizer.py`.

- [ ] **Step 9: Commit (sólo si el usuario lo pidió)**

```bash
git add src/eovrt_media/contracts src/eovrt_media/preprocessing/normalizer.py \
        src/eovrt_media/transport/serialization.py src/eovrt_media/sources \
        tests/test_capture_timestamps.py
git commit -m "feat(metrics): instante de captura y source_clock viajan de la fuente al consumidor"
```

---

## Task 2: `g2a_ms` por unidad en `metrics.jsonl`

**Files:**
- Modify: `src/eovrt_media/contracts/metrics.py`
- Modify: `src/eovrt_media/runtime/pipeline.py` (`run_consumer_loop`)
- Test: `tests/test_g2a_metric.py` (nuevo)

**Interfaces:**
- Consumes: `NormalizedUnit.capture_monotonic_ns` (Task 1).
- Produces: `MetricSample.capture_monotonic_ns: int = 0`, `MetricSample.capture_wallclock_ms: float = 0.0`,
  `MetricSample.g2a_ms: float = 0.0`.

**Dónde cierra G2A y por qué.** Spec 40 §5.1: G2A = *captura/lectura del frame → resultado
algorítmico disponible*, y spec 42 §5 la descompone como `t_capture + t_transport + t_preprocess +
t_inference`. Por lo tanto **se cierra justo después de que la inferencia termina**, antes del
postproceso. Se mide con `time.monotonic_ns()`, el mismo reloj que estampó la captura.

- [ ] **Step 1: Write the failing test**

**Verificado: NO existe `tests/conftest.py` ni una fixture de config.** El repo arma el `RunConfig`
a mano en cada test. Copiá el patrón exacto de `tests/test_execute_run.py` (helpers `_make_images`
y `_config`), que es el único que existe. Crear `tests/test_g2a_metric.py`:

```python
import json
import time
from pathlib import Path

from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.contracts.metrics import MetricSample
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import execute_run

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _make_images(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(folder / f"img_{i:03d}.png")


def _config(tmp_path: Path, run_id: str, warmup_units: int = 0):
    images = tmp_path / "images"
    _make_images(images, 6)
    raw = {
        "run": {"id": run_id, "warmup_units": warmup_units},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def _run(config) -> str:
    adapter = create_adapter(config.model)
    adapter.load()
    try:
        return execute_run(config, adapter)
    finally:
        adapter.close()


def test_metric_sample_has_the_capture_and_g2a_fields_with_defaults() -> None:
    """Aditivo: un metrics.jsonl viejo (sin estos campos) sigue validando."""
    sample = MetricSample(run_id="r", unit_id="u")

    assert sample.capture_monotonic_ns == 0
    assert sample.capture_wallclock_ms == 0.0
    assert sample.g2a_ms == 0.0
    assert sample.schema_version == "media.metric.v2"


def test_metric_sample_accepts_the_new_fields() -> None:
    sample = MetricSample(run_id="r", unit_id="u", capture_monotonic_ns=5,
                          capture_wallclock_ms=1.5, g2a_ms=42.0)

    assert (sample.capture_monotonic_ns, sample.capture_wallclock_ms, sample.g2a_ms) == (
        5, 1.5, 42.0
    )


def test_execute_run_writes_g2a_per_unit(tmp_path) -> None:
    """Cada fila de metrics.jsonl trae los tres insumos de t_capture->alert,
    con `unit_id` como clave de join (spec 40 SS5.2.4)."""
    config = _config(tmp_path, "g2a-metric")
    run_id = _run(config)

    metrics_path = tmp_path / "runs" / run_id / "metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    assert rows, "la corrida no escribio metricas"

    now_ns = time.monotonic_ns()
    for row in rows:
        assert row["unit_id"]
        assert 0 < row["capture_monotonic_ns"] <= now_ns
        assert row["capture_wallclock_ms"] > 0.0
        # G2A positivo y acotado: una corrida mock no tarda 60 s por unidad.
        assert 0.0 < row["g2a_ms"] < 60_000.0
```

**Nota:** `run_id` viene de `config.run.id`, así que `runs/<run_id>/` es determinista. Si
`execute_run` devolviera otro id, usá el que devuelve (como acá).

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/python -m pytest tests/test_g2a_metric.py -q
```

Expected: FAIL — `MetricSample` no tiene `g2a_ms`.

- [ ] **Step 3: Add the fields to `MetricSample`**

En `src/eovrt_media/contracts/metrics.py`, dentro de `class MetricSample`, después de
`source_path`:

```python
    # Insumos de t_capture->alert (spec 40 SS5.2.4). El join con el plano de
    # control es por `unit_id`. Aditivos: default 0 para artefactos viejos.
    capture_monotonic_ns: int = 0
    capture_wallclock_ms: float = 0.0
    # Compuesta captura -> resultado algoritmico (cierra al terminar la inferencia).
    g2a_ms: float = 0.0
```

- [ ] **Step 4: Close G2A right after inference, in the consumer loop**

En `src/eovrt_media/runtime/pipeline.py`, en `run_consumer_loop`, **inmediatamente después** de la
línea `timer.end_inference()` que sigue al camino de éxito de la inferencia (la de la línea 228,
no la del `except`), agregar:

```python
        # G2A = captura -> resultado algoritmico disponible (spec 40 SS5.1). Se cierra
        # aca, antes del postproceso: la descomposicion de spec 42 SS5 es
        # t_capture + t_transport + t_preprocess + t_inference. Mismo reloj monotonico
        # que estampo la captura.
        g2a_ms = (time.monotonic_ns() - item.capture_monotonic_ns) / 1_000_000.0
```

Verificá que `import time` ya está en `pipeline.py` (lo usa el productor); si no, agregalo.

Y en la construcción de `MetricSample(...)` (línea ~323), agregar:

```python
                    capture_monotonic_ns=item.capture_monotonic_ns,
                    capture_wallclock_ms=item.capture_wallclock_ms,
                    g2a_ms=round(g2a_ms, 3),
```

**Gotcha:** el `continue` del camino de error de postproceso ocurre **después** de calcular
`g2a_ms`, así que la variable siempre existe cuando se construye el `MetricSample`. Verificalo
leyendo el flujo; si hubiera un camino donde no, inicializá `g2a_ms = 0.0` antes del `try`.

- [ ] **Step 5: Run the new tests**

```bash
.venv/bin/python -m pytest tests/test_g2a_metric.py -q
```

Expected: PASS (3 passed).

- [ ] **Step 6: Full suite + lint**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests
```

Expected: `468 passed`, `All checks passed!`

- [ ] **Step 7: Commit (sólo si el usuario lo pidió)**

```bash
git add src/eovrt_media/contracts/metrics.py src/eovrt_media/runtime/pipeline.py \
        tests/test_g2a_metric.py
git commit -m "feat(metrics): g2a_ms y timestamps de captura por unidad en metrics.jsonl"
```

---

## Task 3: G2A en el summary, con warm-up y estado de aplicabilidad

**Files:**
- Create: `src/eovrt_media/metrics/g2a.py`
- Modify: `src/eovrt_media/contracts/events.py` (`RunSummary`)
- Modify: `src/eovrt_media/config/schemas.py` (`RunSection.warmup_units`)
- Modify: `src/eovrt_media/runtime/run_context.py`
- Modify: `src/eovrt_media/runtime/pipeline.py`, `src/eovrt_media/runtime/two_node.py`
- Modify: `src/eovrt_media/sinks/run_artifact_writer.py`
- Test: `tests/test_g2a_summary.py` (nuevo)

**Interfaces:**
- Produces:
  - `metrics.g2a.G2AAccumulator` con `add(g2a_ms: float) -> None`, `samples: list[float]`,
    `summarize(warmup_units: int, applicability_state: str, causes: list[str]) -> G2ASummary`
  - `contracts.events.G2ASummary` (BaseModel): `state: str`, `causes: list[str]`, `count: int`,
    `warmup_units: int`, `avg_ms: float`, `p50_ms: float`, `p95_ms: float`, `p99_ms: float`,
    `budget_min_ms: float = 50.0`, `budget_max_ms: float = 250.0`, `p95_within_budget: bool`
  - `RunSummary.g2a: G2ASummary | None = None`, `RunSummary.source_clock: str | None = None`
  - `RunSection.warmup_units: int = 0`

**El estado de aplicabilidad no es decorativo.** `time.monotonic()` es del sistema, no comparable
entre hosts. En `topology.mode: two_node` la captura la estampa el Nodo A y el G2A lo cerraría el
Nodo B: **el número no significa nada**. El summary declara
`state: "not_interpretable", causes: ["cross_node_monotonic_clock"]` y **no** publica percentiles
(quedan en 0.0 con `count` de todos modos informado). En `single_host` sale `computed`. Sin unidades
⇒ `applicable_not_computed / no_units_processed` (vocabulario de ADR-006, igual que el control-plane).

- [ ] **Step 1: Write the failing test**

Crear `tests/test_g2a_summary.py`:

```python
import pytest

from eovrt_media.metrics.g2a import G2AAccumulator


def test_percentiles_over_a_known_sample() -> None:
    acc = G2AAccumulator()
    for value in range(1, 101):  # 1..100 ms
        acc.add(float(value))

    summary = acc.summarize(warmup_units=0, applicability_state="computed", causes=[])

    assert summary.state == "computed"
    assert summary.count == 100
    assert summary.p50_ms == pytest.approx(50.5, abs=0.6)
    assert summary.p95_ms == pytest.approx(95.0, abs=1.0)
    assert summary.p99_ms == pytest.approx(99.0, abs=1.0)
    assert summary.avg_ms == pytest.approx(50.5, abs=0.1)


def test_warmup_units_are_excluded_from_the_percentiles() -> None:
    """El warm-up (primeras N unidades) distorsiona el P95: se declara y se excluye."""
    acc = G2AAccumulator()
    acc.add(10_000.0)  # carga de kernels CUDA en la primera unidad
    acc.add(10_000.0)
    for _ in range(50):
        acc.add(20.0)

    summary = acc.summarize(warmup_units=2, applicability_state="computed", causes=[])

    assert summary.warmup_units == 2
    assert summary.count == 50, "las unidades de warm-up no cuentan"
    assert summary.p95_ms == pytest.approx(20.0)
    assert summary.avg_ms == pytest.approx(20.0)


def test_budget_verdict_uses_p95() -> None:
    acc = G2AAccumulator()
    for _ in range(10):
        acc.add(100.0)
    assert acc.summarize(0, "computed", []).p95_within_budget is True

    slow = G2AAccumulator()
    for _ in range(10):
        slow.add(400.0)
    verdict = slow.summarize(0, "computed", [])
    assert verdict.p95_within_budget is False
    assert (verdict.budget_min_ms, verdict.budget_max_ms) == (50.0, 250.0)


def test_two_node_does_not_publish_meaningless_percentiles() -> None:
    """Los relojes monotonicos de dos hosts no son comparables: se declara, no se inventa."""
    acc = G2AAccumulator()
    for _ in range(10):
        acc.add(-5.0)  # basura tipica de restar relojes de hosts distintos

    summary = acc.summarize(
        warmup_units=0,
        applicability_state="not_interpretable",
        causes=["cross_node_monotonic_clock"],
    )

    assert summary.state == "not_interpretable"
    assert summary.causes == ["cross_node_monotonic_clock"]
    assert (summary.p50_ms, summary.p95_ms, summary.p99_ms, summary.avg_ms) == (0.0, 0.0, 0.0, 0.0)
    assert summary.count == 10  # se informa cuantas unidades hubo, sin interpretarlas
    assert summary.p95_within_budget is False


def test_no_units_is_not_a_silent_zero() -> None:
    summary = G2AAccumulator().summarize(0, "computed", [])

    assert summary.state == "applicable_not_computed"
    assert summary.causes == ["no_units_processed"]
    assert summary.count == 0


def test_warmup_larger_than_the_sample_is_not_computed() -> None:
    acc = G2AAccumulator()
    acc.add(20.0)

    summary = acc.summarize(warmup_units=5, applicability_state="computed", causes=[])

    assert summary.state == "applicable_not_computed"
    assert summary.causes == ["all_units_in_warmup"]
    assert summary.count == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/python -m pytest tests/test_g2a_summary.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eovrt_media.metrics.g2a'`.

- [ ] **Step 3: Write `metrics/g2a.py`**

```python
"""Acumulador de la metrica compuesta G2A (spec 40 SS5.1, spec 42 SS5).

G2A = captura/lectura del frame -> resultado algoritmico disponible.
Presupuesto declarado: 50-250 ms. El veredicto se toma sobre el P95.
"""

from __future__ import annotations

import statistics

from eovrt_media.contracts.events import G2ASummary

BUDGET_MIN_MS = 50.0
BUDGET_MAX_MS = 250.0


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Percentil por indice (mismo criterio que `LatencyTracker`, para no mezclar metodos)."""
    if not sorted_values:
        return 0.0
    index = min(int(len(sorted_values) * fraction), len(sorted_values) - 1)
    return sorted_values[index]


class G2AAccumulator:
    def __init__(self) -> None:
        self.samples: list[float] = []

    def add(self, g2a_ms: float) -> None:
        self.samples.append(g2a_ms)

    def summarize(
        self, warmup_units: int, applicability_state: str, causes: list[str]
    ) -> G2ASummary:
        """`applicability_state`/`causes` los decide el runtime (topologia, relojes)."""
        if not self.samples:
            return G2ASummary(
                state="applicable_not_computed",
                causes=["no_units_processed"],
                count=0,
                warmup_units=warmup_units,
            )

        # No interpretable: se informa cuantas unidades hubo, NO se publican
        # percentiles de un numero que no significa nada (ADR-006).
        if applicability_state != "computed":
            return G2ASummary(
                state=applicability_state,
                causes=list(causes),
                count=len(self.samples),
                warmup_units=warmup_units,
            )

        measured = self.samples[warmup_units:] if warmup_units > 0 else list(self.samples)
        if not measured:
            return G2ASummary(
                state="applicable_not_computed",
                causes=["all_units_in_warmup"],
                count=0,
                warmup_units=warmup_units,
            )

        ordered = sorted(measured)
        p95 = _percentile(ordered, 0.95)
        return G2ASummary(
            state="computed",
            causes=[],
            count=len(measured),
            warmup_units=warmup_units,
            avg_ms=round(statistics.mean(measured), 3),
            p50_ms=round(statistics.median(measured), 3),
            p95_ms=round(p95, 3),
            p99_ms=round(_percentile(ordered, 0.99), 3),
            p95_within_budget=p95 <= BUDGET_MAX_MS,
        )
```

- [ ] **Step 4: Add `G2ASummary` and the summary fields**

En `src/eovrt_media/contracts/events.py`, **antes** de `class RunSummary`:

```python
class G2ASummary(BaseModel):
    """Compuesta captura -> resultado algoritmico, con su estado de aplicabilidad."""

    state: str  # computed | applicable_not_computed | not_applicable | not_interpretable
    causes: list[str] = Field(default_factory=list)
    count: int = 0
    warmup_units: int = 0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    budget_min_ms: float = 50.0
    budget_max_ms: float = 250.0
    p95_within_budget: bool = False
```

Y dentro de `class RunSummary`, después de `source_type`:

```python
    # Que reloj emite la fuente: decide la aplicabilidad de t_capture->alert
    # aguas abajo (spec 40 SS5.2.3). None = corridas previas a esta task.
    source_clock: str | None = None
    g2a: G2ASummary | None = None
```

- [ ] **Step 5: Add `warmup_units` to the config**

En `src/eovrt_media/config/schemas.py`, en `class RunSection`, después de `max_units`:

```python
    # Unidades iniciales excluidas de los percentiles de G2A (carga de kernels,
    # cache de cuDNN). Se DECLARA en el summary (spec 42 SS5). 0 = comportamiento actual.
    warmup_units: int = 0
```

- [ ] **Step 6: Accumulate G2A in the run context and wire the applicability**

En `src/eovrt_media/runtime/run_context.py`, en `__init__`, junto a `self.units_dropped`:

```python
        from eovrt_media.metrics.g2a import G2AAccumulator

        self.g2a = G2AAccumulator()
        self.source_clock: str = "none"
```

En `src/eovrt_media/runtime/pipeline.py`:

1. En `run_consumer_loop`, justo después de calcular `g2a_ms` (Task 2):

```python
        run_context.g2a.add(g2a_ms)
        run_context.source_clock = item.source_clock
```

2. En `execute_run`, después de `source = create_source(config)`:

```python
        run_context.source_clock = getattr(source, "SOURCE_CLOCK", "none")
```

En `src/eovrt_media/runtime/two_node.py`, en `run_node_b`, no hay `create_source`: el
`source_clock` llega **por unidad** desde el Nodo A (Task 1), así que el `run_consumer_loop` ya lo
puebla. No agregues nada ahí.

- [ ] **Step 7: Emit the block in the summary**

En `src/eovrt_media/sinks/run_artifact_writer.py`, en `write_summary`, calcular el estado antes de
construir el `RunSummary`:

```python
        config = self.context.config
        # Two-node: la captura la estampa el Nodo A y el G2A lo cerraria el Nodo B.
        # `time.monotonic()` es del sistema: entre hosts distintos la resta no
        # significa nada (spec 40 SS4). Se declara, no se publica un numero falso.
        if config.topology.mode == "two_node":
            g2a_state, g2a_causes = "not_interpretable", ["cross_node_monotonic_clock"]
        else:
            g2a_state, g2a_causes = "computed", []
        g2a_summary = self.context.g2a.summarize(
            warmup_units=config.run.warmup_units,
            applicability_state=g2a_state,
            causes=g2a_causes,
        )
```

Y pasarlo al `RunSummary(...)`:

```python
            source_clock=self.context.source_clock,
            g2a=g2a_summary,
```

- [ ] **Step 8: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_g2a_summary.py -q
```

Expected: PASS (6 passed).

- [ ] **Step 9: Full suite + lint**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests
```

Expected: `474 passed`, `All checks passed!` Prestá atención a `tests/test_two_node.py` (el summary
del Nodo B ahora trae el bloque `g2a` en `not_interpretable`) y a los tests que validan el
`summary.json` (`tests/test_artifacts_api.py`, `tests/test_execute_run.py`).

- [ ] **Step 10: Commit (sólo si el usuario lo pidió)**

```bash
git add src/eovrt_media/metrics/g2a.py src/eovrt_media/contracts/events.py \
        src/eovrt_media/config/schemas.py src/eovrt_media/runtime \
        src/eovrt_media/sinks/run_artifact_writer.py tests/test_g2a_summary.py
git commit -m "feat(metrics): G2A en el summary con warm-up declarado y estado de aplicabilidad"
```

---

## Task 4: **Gate** — corrida real y verificación por mutación

**Files:**
- Test: `tests/test_g2a_gate.py` (nuevo)

- [ ] **Step 1: Write the gate**

Reusá los helpers `_make_images` / `_config` / `_run` que escribiste en `tests/test_g2a_metric.py`
(cópialos; el repo no tiene `conftest.py` y duplica helpers entre tests — seguí esa costumbre).

```python
"""Gate: los tres insumos de t_capture->alert existen y son coherentes (spec 40 SS5.2.4)."""

import json
from pathlib import Path

import pytest
from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import execute_run

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _make_images(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(folder / f"img_{i:03d}.png")


def _config(tmp_path: Path, run_id: str, warmup_units: int = 0):
    images = tmp_path / "images"
    _make_images(images, 6)
    raw = {
        "run": {"id": run_id, "warmup_units": warmup_units},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def _run(config) -> str:
    adapter = create_adapter(config.model)
    adapter.load()
    try:
        return execute_run(config, adapter)
    finally:
        adapter.close()


@pytest.mark.parametrize("warmup", [0, 2])
def test_run_emits_capture_stamps_g2a_and_source_clock(tmp_path, warmup) -> None:
    config = _config(tmp_path, f"gate-{warmup}", warmup_units=warmup)
    run_id = _run(config)

    run_dir = tmp_path / "runs" / run_id
    metrics = [
        json.loads(line) for line in (run_dir / "metrics.jsonl").read_text().splitlines()
        if line.strip()
    ]
    summary = json.loads((run_dir / "summary.json").read_text())

    # 1. Los tres campos por unidad, con `unit_id` como clave de join.
    assert {"unit_id", "capture_monotonic_ns", "capture_wallclock_ms", "g2a_ms"} <= set(metrics[0])
    assert all(row["g2a_ms"] > 0.0 for row in metrics)

    # 2. La fuente declara su reloj (image_folder => fuente no temporal).
    assert summary["source_clock"] == "none"

    # 3. El bloque G2A declara warm-up y estado, y no miente sobre el conteo.
    g2a = summary["g2a"]
    assert g2a["warmup_units"] == warmup
    assert g2a["count"] == max(len(metrics) - warmup, 0)
    assert g2a["state"] == "computed"
    assert g2a["p50_ms"] > 0.0
    assert (g2a["budget_min_ms"], g2a["budget_max_ms"]) == (50.0, 250.0)


def test_g2a_is_monotonic_with_the_unit_latency(tmp_path) -> None:
    """El G2A de una unidad no puede ser MENOR que su propia latencia de inferencia:
    la contiene por construccion. Si lo fuera, el reloj de captura esta mal estampado
    (p.ej. re-estampado despues de la normalizacion en vez de al leer la unidad)."""
    config = _config(tmp_path, "gate-monotonic")
    run_id = _run(config)

    metrics_path = tmp_path / "runs" / run_id / "metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text().splitlines() if line.strip()]
    assert rows
    for row in rows:
        assert row["g2a_ms"] >= row["latency_inference_ms"], row["unit_id"]
```

- [ ] **Step 2: Run the gate**

```bash
.venv/bin/python -m pytest tests/test_g2a_gate.py -q -v
```

Expected: PASS (3 passed).

- [ ] **Step 3: Verificar que el gate es significativo (mutación) — obligatorio**

Un gate que no puede fallar no es un gate. Hacé **dos** mutaciones, una por vez, y reportá la
salida literal de cada una:

1. En `contracts/visual_unit.py`, cambiá `default_factory=time.monotonic_ns` por un valor fijo
   (`default=0`). Esperado: falla `test_g2a_is_monotonic_with_the_unit_latency` o el assert de
   `capture_monotonic_ns > 0` del gate. **Revertí.**
2. En `preprocessing/normalizer.py`, borrá la línea `capture_monotonic_ns=unit.capture_monotonic_ns`
   del `return NormalizedUnit(...)` (el default_factory volvería a estampar, ahora en el
   *normalizado*, no en la lectura). Esperado: `g2a_ms` colapsa a casi 0 y falla
   `test_g2a_is_monotonic_with_the_unit_latency`. **Revertí.**

Si alguna mutación **no** hace fallar el gate, el gate es vacuo: arreglalo antes de seguir y
explicá qué cambiaste.

- [ ] **Step 4: Corrida real end-to-end sobre video**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane
rm -rf /tmp/g2a && mkdir -p /tmp/g2a
EOVRT_MODEL_REF=mock EOVRT_RUNS_DIR=/tmp/g2a/runs \
  .venv/bin/python -m uvicorn --factory eovrt_media.service.app:create_app --port 8096 &
sleep 3
.venv/bin/python - <<'PY'
import json, time, urllib.request
body = {"ingest": {"plugin": "video_file",
                   "config": {"path": "/home/simonll4/projects/e-ovrt_media-plane/data/samples/videos/recorte-1.mp4"}},
        "prompts": {"set_inline": {"id": "p", "classes": [{"id": "person", "phrasings": {"default": ["person"]}}]},
                    "active_ids": ["person"]},
        "run": {"name": "g2a", "max_units": 20, "save_previews": False}}
r = urllib.request.Request("http://localhost:8096/api/runs", data=json.dumps(body).encode(),
                           headers={"Content-Type": "application/json"}, method="POST")
run_id = json.loads(urllib.request.urlopen(r, timeout=60).read())["run_id"]
for _ in range(60):
    with urllib.request.urlopen(f"http://localhost:8096/api/runs/{run_id}", timeout=10) as resp:
        state = json.loads(resp.read())
    if state["status"] != "running":
        break
    time.sleep(1)
s = state["summary"]
print("source_clock:", s["source_clock"], "(video_file => 'media')")
print("g2a:", {k: s["g2a"][k] for k in ("state", "count", "p50_ms", "p95_ms", "p95_within_budget")})
rows = [json.loads(l) for l in open(f"/tmp/g2a/runs/{run_id}/metrics.jsonl") if l.strip()]
print("filas de metrics con los 3 campos:", sum(
    1 for r in rows if r["capture_monotonic_ns"] and r["capture_wallclock_ms"] and r["g2a_ms"]))
PY
pkill -f "port 8096"
```

Expected: `source_clock: media`, `g2a state=computed`, `count=20`, `p50_ms > 0`, y 20 filas con los
tres campos. **Archivá el `summary.json` en `docs/operacion/datos/`.**

- [ ] **Step 5: Full suite + lint**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests
```

Expected: `477 passed`, `All checks passed!`

- [ ] **Step 6: Commit (sólo si el usuario lo pidió)**

```bash
git add tests/test_g2a_gate.py
git commit -m "test(metrics): gate de los insumos de t_capture->alert, verificado por mutacion"
```

---

## Cierre

- [ ] **Step 1: Actualizar `e-ovrt_media-plane/CLAUDE.md`**

En "Architecture", en el párrafo de **Metrics**: `metrics.jsonl` ahora trae, por `unit_id`,
`capture_monotonic_ns` / `capture_wallclock_ms` / `g2a_ms` — los insumos de `t_capture→alert`
(spec 40 §5.2.4), que se joinean por `unit_id` con las alertas del control-plane. El `summary.json`
declara `source_clock` (`wallclock|media|none`, decide la aplicabilidad de la métrica) y el bloque
`g2a` con percentiles, warm-up y presupuesto 50–250 ms. En two-node el bloque sale
`not_interpretable / cross_node_monotonic_clock`: los relojes monotónicos de dos hosts no se restan.

- [ ] **Step 2: Registrar la deuda**

1. **`experiment_id` sigue sin viajar en el `POST /api/runs`** (spec 42 §4.1). El `RunSummary` tiene
   el campo y `run_artifact_writer` lo puebla desde `config.experiment.id`, pero el request no lo
   acepta. La cadena de reconstrucción (spec 40 §2) queda a medias hasta que se agregue.
2. **En two-node, G2A no se puede computar** con este diseño. Para hacerlo habría que declarar la
   sincronización de relojes (chrony/NTP) con su error estimado, o re-estampar la captura en el
   Nodo B (lo que mediría otra cosa). Decisión pendiente, spec 40 §4.
3. **`t_capture→alert` todavía no se puede calcular**: falta el lado del control-plane
   (`first_evidence_unit_id`, `alert_registered_ms`, `ts_receive_ms`). Es el plan hermano.

- [ ] **Step 3: Verificación final**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests
```

No declarar nada listo sin pegar la salida de esos dos comandos, la del paso 4 de la Task 4, y el
resultado de **las dos mutaciones** de la Task 4 Step 3.
