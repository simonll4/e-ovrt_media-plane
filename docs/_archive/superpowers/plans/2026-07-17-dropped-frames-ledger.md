# Ledger de frames descartados (Pieza A2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El media-plane registra por-frame cada descarte (`rate_gate` / `queue_full` / `staleness_timeout` / `channel_closed`) en `runs/<id>/dropped_units.jsonl` y lo expone en `GET /api/runs/{id}/dropped`.

**Architecture:** Un builder puro arma el registro desde la unidad descartada (que ya trae identidad completa). Un sink thread-safe de apertura perezosa lo escribe. El transporte y el loop productor reciben un callback `on_drop` inyectado (el transporte no conoce al writer). El endpoint espeja `/detections`.

**Tech Stack:** Python 3.11, pydantic, FastAPI, pytest. Repo: `e-ovrt_media-plane`.

**Spec:** `docs/superpowers/specs/2026-07-17-dropped-frames-ledger-design.md`

## Global Constraints

- **MODO SIN COMMITS** (regla de `projects/CLAUDE.md`): todo en working tree; los pasos "Commit" son puntos de corte, no instrucciones.
- **Aditivo estricto**: `units_dropped` (contador), `detections.jsonl`, `metrics.jsonl`, `summary.json` quedan idénticos. El transporte sigue funcionando igual si `on_drop=None` (default).
- **Thread-safety obligatoria** (spec §5): el sink serializa con lock — recibe escrituras del hilo productor (rate_gate, `offer`) y del consumidor (`request` staleness).
- **Identidad completa en todos los reasons** (D5): `unit_id`, `frame_index`, `timestamp_ms`, `source_clock` del `VisualUnit`/`NormalizedUnit` descartado.
- **Apertura perezosa**: cero descartes → el archivo NO se crea (spec §6: endpoint 200 vacío).
- Tests: `.venv/bin/python -m pytest tests/ -q` desde la raíz del repo (o `make test`). Suite previa verde antes y después.

---

### Task 1: Contrato + builder puro

**Files:**
- Create: `src/eovrt_media/contracts/dropped_unit.py`
- Test: `tests/test_dropped_units.py` (nuevo)

**Interfaces:**
- Produces: `DroppedUnitRecord(BaseModel)` (schema `media.dropped_unit.v1`) y `build_dropped_record(unit, reason, run_id) -> DroppedUnitRecord`, donde `unit` es cualquier objeto con `unit_id`/`frame_index`/`timestamp_ms`/`source_clock` (sirve para `VisualUnit` y `NormalizedUnit` por duck-typing).

- [ ] **Step 1: Test que falla** — `tests/test_dropped_units.py`:

```python
import time

from eovrt_media.contracts.dropped_unit import DroppedUnitRecord, build_dropped_record
from eovrt_media.contracts.visual_unit import VisualUnit


def _visual_unit(frame_index: int = 7) -> VisualUnit:
    return VisualUnit(
        unit_id=f"frame_{frame_index:06d}", source_type="video_frame",
        frame_index=frame_index, timestamp_ms=1234.5, source_clock="media",
        width=640, height=480,
    )


def test_build_dropped_record_carries_full_identity() -> None:
    before = time.time() * 1000.0
    rec = build_dropped_record(_visual_unit(), reason="rate_gate", run_id="run-x")
    assert rec.schema_version == "media.dropped_unit.v1"
    assert (rec.reason, rec.run_id) == ("rate_gate", "run-x")
    assert (rec.unit_id, rec.frame_index) == ("frame_000007", 7)
    assert (rec.timestamp_ms, rec.source_clock) == (1234.5, "media")
    assert rec.dropped_wallclock_ms >= before


def test_build_dropped_record_rejects_unknown_reason() -> None:
    import pytest
    with pytest.raises(ValueError):
        build_dropped_record(_visual_unit(), reason="whatever", run_id="run-x")
```

- [ ] **Step 2: Verificar que falla** — `.venv/bin/python -m pytest tests/test_dropped_units.py -q` → FAIL (ImportError).

- [ ] **Step 3: Implementar** — `src/eovrt_media/contracts/dropped_unit.py`:

```python
"""Contrato del ledger de descartes por-frame (spec dropped-frames-ledger)."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel

DropReason = Literal["rate_gate", "queue_full", "staleness_timeout", "channel_closed"]


class DroppedUnitRecord(BaseModel):
    schema_version: str = "media.dropped_unit.v1"
    run_id: str | None = None
    reason: DropReason
    unit_id: str
    frame_index: int | None = None
    timestamp_ms: float | None = None
    source_clock: str | None = None
    dropped_wallclock_ms: float


def build_dropped_record(unit: Any, reason: str, run_id: str | None) -> DroppedUnitRecord:
    """Arma el registro desde la unidad descartada (VisualUnit o NormalizedUnit).

    Duck-typing a proposito: ambos contratos comparten los campos de identidad.
    """
    return DroppedUnitRecord(
        run_id=run_id,
        reason=reason,  # Literal valida el reason
        unit_id=unit.unit_id,
        frame_index=unit.frame_index,
        timestamp_ms=unit.timestamp_ms,
        source_clock=getattr(unit, "source_clock", None),
        dropped_wallclock_ms=time.time() * 1000.0,
    )
```

Nota: pydantic levanta `ValidationError` (subclase de `ValueError`) ante reason inválido — el test lo captura con `ValueError`.

- [ ] **Step 4: Verificar que pasa** → PASS.
- [ ] **Step 5: Punto de corte (sin commit).**

---

### Task 2: Sink thread-safe de apertura perezosa

**Files:**
- Create: `src/eovrt_media/sinks/dropped_units_sink.py`
- Test: `tests/test_dropped_units.py` (append)

**Interfaces:**
- Produces: `DroppedUnitsSink(path)` con `write(record: DroppedUnitRecord)` y `close()`. Lock interno; el archivo se crea recién en el primer `write`.

- [ ] **Step 1: Tests que fallan** — append:

```python
import json
import threading

from eovrt_media.sinks.dropped_units_sink import DroppedUnitsSink


def test_sink_lazy_no_file_without_drops(tmp_path) -> None:
    sink = DroppedUnitsSink(tmp_path / "dropped_units.jsonl")
    sink.close()
    assert not (tmp_path / "dropped_units.jsonl").exists()


def test_sink_writes_jsonl_lines(tmp_path) -> None:
    path = tmp_path / "dropped_units.jsonl"
    sink = DroppedUnitsSink(path)
    sink.write(build_dropped_record(_visual_unit(1), "queue_full", "run-x"))
    sink.write(build_dropped_record(_visual_unit(2), "rate_gate", "run-x"))
    sink.close()
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert [r["reason"] for r in rows] == ["queue_full", "rate_gate"]


def test_sink_is_thread_safe(tmp_path) -> None:
    path = tmp_path / "dropped_units.jsonl"
    sink = DroppedUnitsSink(path)

    def spam(n0: int) -> None:
        for i in range(200):
            sink.write(build_dropped_record(_visual_unit(n0 + i), "queue_full", "r"))

    threads = [threading.Thread(target=spam, args=(k * 1000,)) for k in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    sink.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 800
    for line in lines:
        json.loads(line)  # ninguna linea intercalada/corrupta
```

- [ ] **Step 2: Verificar que fallan** → FAIL (ImportError).

- [ ] **Step 3: Implementar** — `src/eovrt_media/sinks/dropped_units_sink.py`:

```python
"""Sink JSONL thread-safe para el ledger de descartes.

Serializa con lock: recibe escrituras del hilo productor (rate_gate/offer) y del
consumidor (staleness en request). Apertura perezosa: cero descartes = sin archivo.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from eovrt_media.contracts.dropped_unit import DroppedUnitRecord


class DroppedUnitsSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._fh = None

    def write(self, record: DroppedUnitRecord) -> None:
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=True)
        with self._lock:
            if self._fh is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = self.path.open("w", encoding="utf-8")
            self._fh.write(line + "\n")

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
```

- [ ] **Step 4: Verificar que pasan** → PASS.
- [ ] **Step 5: Punto de corte (sin commit).**

---

### Task 3: Instrumentar el transporte (`on_drop`)

**Files:**
- Modify: `src/eovrt_media/transport/memory.py`, `src/eovrt_media/transport/factory.py`, `src/eovrt_media/transport/network.py`
- Test: `tests/test_dropped_units.py` (append)

**Interfaces:**
- Produces: `MemoryTransportAdapter(..., on_drop: Callable[[NormalizedUnit, str], None] | None = None)`. En cada punto de drop, ANTES o junto a `units_dropped += 1`, llama `on_drop(unit, reason)`. `create_transport(..., on_drop=None)` lo pasa; `NetworkTransportAdapter` lo reenvía a su buffer interno (`network.py:59`).
- Consumes: nada del writer — el callback desacopla (spec §5).

- [ ] **Step 1: Tests que fallan** — append:

```python
from eovrt_media.contracts.normalized_unit import NormalizedUnit  # para type ref
from eovrt_media.transport.memory import MemoryTransportAdapter


class _Spy:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
    def __call__(self, unit, reason: str) -> None:
        self.calls.append((unit.unit_id, reason))


def _norm_unit(i: int, timestamp_ms: float | None = None):
    # NormalizedUnit minima: mirar los tests existentes de transporte
    # (tests/test_transport.py) y reusar SU helper/forma de construccion.
    ...


def test_on_drop_queue_full_bounded_freshness() -> None:
    spy = _Spy()
    t = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=1, on_drop=spy)
    t.offer(_norm_unit(0))
    t.offer(_norm_unit(1))  # desplaza al 0
    assert spy.calls == [("frame_000000", "queue_full")]
    assert t.units_dropped == 1  # el contador NO cambia de semantica


def test_on_drop_staleness_timeout() -> None:
    spy = _Spy()
    t = MemoryTransportAdapter(
        policy="bounded_freshness", buffer_size=2, max_staleness_ms=10.0, on_drop=spy
    )
    t.offer(_norm_unit(0, timestamp_ms=0.0))
    t.close()
    unit = t.request(current_time_ms=lambda: 10_000.0)
    from eovrt_media.contracts.normalized_unit import END
    assert unit is END
    assert spy.calls == [("frame_000000", "staleness_timeout")]


def test_on_drop_channel_closed_deterministic() -> None:
    spy = _Spy()
    t = MemoryTransportAdapter(policy="deterministic", max_queue_size=1, on_drop=spy)
    t.close()
    t.offer(_norm_unit(0))
    assert spy.calls == [("frame_000000", "channel_closed")]


def test_on_drop_none_keeps_behavior() -> None:
    t = MemoryTransportAdapter(policy="bounded_freshness", buffer_size=1)
    t.offer(_norm_unit(0)); t.offer(_norm_unit(1))
    assert t.units_dropped == 1  # sin callback, todo como antes
```

`_norm_unit` se completa copiando el helper de construcción de `NormalizedUnit` que ya usen los tests de transporte existentes (`tests/test_transport.py` / `test_memory_transport_close.py`) — no inventar campos; solo asegurar `unit_id=f"frame_{i:06d}"` y `timestamp_ms` parametrizable.

- [ ] **Step 2: Verificar que fallan** → FAIL (`on_drop` inesperado).

- [ ] **Step 3: Implementar.**

(a) `memory.py`: agregar param `on_drop=None` al `__init__` (`self._on_drop = on_drop`) y helper:

```python
    def _notify_drop(self, unit, reason: str) -> None:
        if self._on_drop is not None:
            try:
                self._on_drop(unit, reason)
            except Exception:  # el ledger jamas voltea el pipeline
                pass
```

En los tres puntos (los `units_dropped += 1` de `offer` cerrado → `"channel_closed"` con `unit`; `popleft` por buffer lleno → `"queue_full"` con la unidad desplazada, capturarla: `dropped = self._buf.popleft()` antes del incremento; staleness en `request` → `"staleness_timeout"` con `unit`): llamar `self._notify_drop(...)` junto al incremento.

(b) `factory.py`: agregar `on_drop=None` a `create_transport` y pasarlo a `MemoryTransportAdapter(...)` y a `NetworkTransportAdapter(...)`.

(c) `network.py`: aceptar `on_drop=None` y pasarlo al `MemoryTransportAdapter` interno (línea 59).

- [ ] **Step 4: Verificar que pasan** — `.venv/bin/python -m pytest tests/test_dropped_units.py tests/test_transport.py tests/test_memory_transport_close.py -q` → PASS, **tests de transporte preexistentes sin tocar** (con `on_drop=None` el comportamiento es idéntico).
- [ ] **Step 5: Punto de corte (sin commit).**

---

### Task 4: Rate-gate + cableado del pipeline

**Files:**
- Modify: `src/eovrt_media/runtime/pipeline.py`
- Test: `tests/test_dropped_units.py` (append)

**Interfaces:**
- Produces: `run_producer_loop(..., on_drop=None)` — emite `("rate_gate", unit)` cuando el gate saltea; el pipeline (zona líneas 490-520) construye `DroppedUnitsSink(run_context.run_dir / "dropped_units.jsonl")`, arma el callback `lambda unit, reason: sink.write(build_dropped_record(unit, reason, run_context.run_id))`, y lo pasa a `create_transport(...)` y a `run_producer_loop(...)`; `close()` del sink al cerrar los demás artefactos.
- Consumes: Tasks 1-3.

- [ ] **Step 1: Test que falla** — append (test directo del productor, con normalize monkeypatcheado — el rate-gate corta ANTES de normalizar, así que el stub solo atiende a los que pasan):

```python
import queue as _queue
from types import SimpleNamespace

from eovrt_media.runtime import pipeline as pipeline_mod
from eovrt_media.transport.rate_gate import RateGate


class _CollectTransport:
    def __init__(self): self.offered = []
    def offer(self, unit): self.offered.append(unit)
    def close(self): pass


def test_producer_emits_rate_gate_drops(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_mod, "normalize_spatial",
        lambda unit, spec, fmt: SimpleNamespace(unit_id=unit.unit_id, run_id=None),
    )
    units = [_visual_unit(i) for i in range(4)]
    spy = _Spy()
    transport = _CollectTransport()
    pipeline_mod.run_producer_loop(
        source=units, rate_gate=RateGate(stride=2), spec=None,
        payload_format=None, transport=transport, run_id="run-x",
        errors_queue=_queue.SimpleQueue(), timings={}, should_continue=None,
        on_drop=spy,
    )
    # stride=2: pasan los indices de enumeracion 0 y 2; se descartan 1 y 3
    assert [u.unit_id for u in transport.offered] == ["frame_000000", "frame_000002"]
    assert spy.calls == [("frame_000001", "rate_gate"), ("frame_000003", "rate_gate")]
```

(Si `run_producer_loop` se invoca posicionalmente en `pipeline.py`, mantener el orden de params y agregar `on_drop` al final con default `None`.)

- [ ] **Step 2: Verificar que falla** → FAIL (`on_drop` inesperado).

- [ ] **Step 3: Implementar.**

(a) `run_producer_loop` (línea 68): agregar param final `on_drop=None`; en el gate (líneas 82-83):

```python
            if not rate_gate.should_pass(source_index):
                if on_drop is not None:
                    try:
                        on_drop(unit, "rate_gate")
                    except Exception:
                        pass  # el ledger jamas voltea el pipeline
                continue
```

(b) Cableado (zona 490-520): crear el sink y el callback antes de `create_transport`:

```python
            from eovrt_media.contracts.dropped_unit import build_dropped_record
            from eovrt_media.sinks.dropped_units_sink import DroppedUnitsSink

            dropped_sink = DroppedUnitsSink(run_context.run_dir / "dropped_units.jsonl")

            def _on_drop(unit, reason: str) -> None:
                dropped_sink.write(build_dropped_record(unit, reason, run_context.run_id))
```

pasar `on_drop=_on_drop` a `create_transport(...)` y agregarlo como último arg del `args=(...)` del thread productor. Cerrar `dropped_sink.close()` en el mismo `finally`/cierre donde se cierran los otros artefactos del run (localizarlo en el propio archivo; si no hay un cierre común accesible, cerrarlo tras el `join` del productor y del consumidor).

Verificar que `run_context.run_dir` existe con ese nombre en `RunContext` (es el mismo que usa `RunArtifactWriter.__init__`); si el atributo real difiere, usar el real.

- [ ] **Step 4: Verificar que pasan** — `.venv/bin/python -m pytest tests/test_dropped_units.py tests/test_pipeline_mock.py tests/test_pipeline_two_threads.py -q` → PASS, pipeline preexistente sin regresión.
- [ ] **Step 5: Punto de corte (sin commit).**

---

### Task 5: Endpoint `/dropped` + gate final

**Files:**
- Modify: `src/eovrt_media/service/routers/runs.py`
- Test: el archivo de tests del servicio que ya cubre `/detections` (localizar con `grep -rn "detections" tests/`) — append ahí.

**Interfaces:**
- Produces: `GET /api/runs/{run_id}/dropped?page=&page_size=`, espejo exacto de `get_detections` (`service/routers/runs.py:81-111`) sobre `dropped_units.jsonl`, con una diferencia: **archivo ausente → 200 `{total: 0, items: []}`** (cero descartes es válido, spec §6), no 404. Run inexistente sigue siendo 404 vía `_require_valid_run_id` + inexistencia del run_dir (usar el mismo mecanismo que el endpoint vecino use para distinguir run inexistente; si `/detections` no distingue, chequear `runs_dir / run_id` explícitamente).

- [ ] **Step 1: Tests que fallan** — append al archivo de tests del servicio, copiando el armado de run_dir del test de `/detections` vecino:

```python
def test_dropped_endpoint_serves_ledger(...) -> None:
    # armar run_dir + dropped_units.jsonl con 3 lineas (reasons distintos),
    # copiando el setup del test de /detections del mismo archivo
    response = client.get(f"/api/runs/{run_id}/dropped?page=1&page_size=2")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert body["items"][0]["reason"] in {"rate_gate", "queue_full", "staleness_timeout", "channel_closed"}


def test_dropped_endpoint_no_file_returns_empty(...) -> None:
    # run_dir valido SIN dropped_units.jsonl
    response = client.get(f"/api/runs/{run_id}/dropped")
    assert response.status_code == 200
    assert response.json() == {"page": 1, "page_size": 100, "total": 0, "items": []}
```

(fixtures/`client` idénticos a los del test de `/detections`; no inventar mecanismos nuevos.)

- [ ] **Step 2: Verificar que fallan** → FAIL (404 ruta nueva).

- [ ] **Step 3: Implementar** — debajo de `get_detections`:

```python
@router.get("/runs/{run_id}/dropped")
def get_dropped_units(
    run_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    _manager(request)  # 503 si no ready
    _require_valid_run_id(run_id)
    run_dir = request.app.state.settings.runs_dir / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run desconocido: {run_id}")
    path = run_dir / "dropped_units.jsonl"
    try:
        text = path.read_text()
    except FileNotFoundError:
        # Cero descartes es un resultado valido y bueno (spec §6): 200 vacio.
        return {"page": page, "page_size": page_size, "total": 0, "items": []}
    records = []
    for line in text.splitlines():
        if not line:
            continue
        try:
            records.append(_json.loads(line))
        except ValueError:
            continue  # linea malformada: se omite en vez de 500
    start = (page - 1) * page_size
    items = records[start : start + page_size]
    return {"page": page, "page_size": page_size, "total": len(records), "items": items}
```

- [ ] **Step 4: Gate final.**
  - `.venv/bin/python -m pytest tests/ -q` → suite completa PASS.
  - No-regresión: `git diff` de `run_artifact_writer.py` vacío (no se tocó); en `memory.py` el único cambio es `on_drop` (los `units_dropped += 1` siguen); smoke real: correr un run corto con `stride>1` (`EOVRT_MODEL_REF=mock make serve` + POST run) y `curl :8080/api/runs/<id>/dropped` → registros `rate_gate` con identidad completa; el criterio 3 del spec (unión procesados ∪ descartados sin huecos sobre lo emitido por la fuente) verificado sobre ese run.
- [ ] **Step 5: Punto de corte (sin commit).**
