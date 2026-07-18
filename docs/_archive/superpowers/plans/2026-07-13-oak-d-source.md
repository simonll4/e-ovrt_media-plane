# OakDSource (OAK-D Pro PoE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completar el plugin `oak_d` del media-plane: la OAK-D Pro PoE como fuente viva RGB vía DepthAI, con conexión por IP fija, parada cooperativa y reconexión.

**Architecture:** Se rellena el stub `OakDSource` siguiendo el patrón de `RtspSource` (fuente viva: `SOURCE_CLOCK="wallclock"`, `pixel_data` BGR en el `VisualUnit`, `threading.Event` para stop, reconexión con reintentos). Se levanta el gate `NotImplementedError` del loader, se flipea `available=True` en el registry y se agrega la rama en `create_source`. Import de `depthai` lazy: el servicio no lo requiere si no se usa la fuente.

**Tech Stack:** Python 3.11, Pydantic, pytest, DepthAI SDK v2 (`depthai>=2.24,<3`), numpy.

**Spec:** `docs/superpowers/specs/2026-07-13-oak-d-source-design.md`

## Global Constraints

- **NO COMMITS**: regla del workspace (`projects/CLAUDE.md`) — nunca commitear salvo pedido explícito del usuario en ese turno. Este plan NO tiene pasos de commit; al terminar se informa que el trabajo está listo para revisión.
- Repo de trabajo: `/home/simonll4/projects/e-ovrt_media-plane` (todas las rutas de abajo son relativas a él).
- Entorno: `source .venv/bin/activate` antes de correr pytest/ruff (venv del repo, Python 3.11).
- SDK pineado: `depthai>=2.24,<3` (API v2). NO usar API v3.
- Conexión SIEMPRE por IP fija (`dai.DeviceInfo(ip)`), nunca autodiscovery (falla en WSL con `X_LINK_DEVICE_NOT_FOUND`).
- Los tests NO requieren hardware ni el SDK instalado: usan un módulo `depthai` falso.
- Recursos del device se abren y cierran solo en el hilo productor (dentro de `__iter__`); `stop()` solo setea un evento.
- Estilo: comentarios/docstrings en español, `ruff` line-length 100, seguir el idioma de `rtsp_source.py`.

---

### Task 1: Implementar `OakDSource`

**Files:**
- Modify: `src/eovrt_media/sources/oak_d_source.py` (reemplazo completo del stub)
- Test: `tests/test_oak_d_source.py` (reemplazo completo)

**Interfaces:**
- Consumes: `BaseSource` (`sources/base.py`), `VisualUnit` (`contracts/visual_unit.py`).
- Produces: `OakDSource(url: str, resolution: str = "1080p", fps: int = 10, reconnect_retries: int = 5, reconnect_delay_ms: int = 1000, max_units: int | None = None, source_id: str | None = None)` con `__iter__() -> Iterator[VisualUnit]`, `stop() -> None`, `__len__() -> raise TypeError`, y seams de test `_load_sdk()` / `_open_device(dai)`. Task 3 (registry) instancia esta clase con esa firma exacta.

- [ ] **Step 1: Escribir los tests que fallan**

Reemplazar `tests/test_oak_d_source.py` completo con:

```python
"""OakDSource — fuente viva OAK-D Pro PoE, testeada con un SDK DepthAI falso."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from eovrt_media.sources.oak_d_source import OakDSource


# ---------------------------------------------------------------------------
# Fake del SDK DepthAI (API v2): suficiente para _build_pipeline y el loop de
# captura. No requiere depthai instalado.
# ---------------------------------------------------------------------------

class _FakeMsg:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def getCvFrame(self) -> np.ndarray:
        return self._frame


class _FakeQueue:
    """Cola que emite `n_frames` y después devuelve None (tryGet)."""

    def __init__(self, n_frames: int, fail_after: int | None = None) -> None:
        self._served = 0
        self._n_frames = n_frames
        self._fail_after = fail_after

    def tryGet(self):
        if self._fail_after is not None and self._served >= self._fail_after:
            raise RuntimeError("X_LINK: lectura falló")
        if self._served >= self._n_frames:
            return None
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[0, 0] = self._served  # marca para distinguir frames
        self._served += 1
        return _FakeMsg(frame)


class _FakeDevice:
    def __init__(self, queue: _FakeQueue) -> None:
        self.queue = queue
        self.closed = False

    def getOutputQueue(self, name: str, maxSize: int, blocking: bool) -> _FakeQueue:
        assert name == "rgb"
        return self.queue

    def close(self) -> None:
        self.closed = True


class _FakeNode:
    """Nodo fake: absorbe cualquier llamada de configuración."""

    def __init__(self) -> None:
        self.video = SimpleNamespace(link=lambda _inp: None)
        self.input = object()

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


class _FakePipeline:
    def create(self, node_cls):
        return _FakeNode()


def _fake_dai() -> SimpleNamespace:
    """Módulo depthai falso con los símbolos que usa _build_pipeline."""
    return SimpleNamespace(
        Pipeline=_FakePipeline,
        node=SimpleNamespace(ColorCamera=object, XLinkOut=object),
        ColorCameraProperties=SimpleNamespace(
            SensorResolution=SimpleNamespace(
                THE_720_P="720p", THE_1080_P="1080p", THE_4_K="4k"
            )
        ),
        CameraBoardSocket=SimpleNamespace(CAM_A="cam_a"),
        DeviceInfo=lambda ip: SimpleNamespace(ip=ip),
    )


def _make_source(monkeypatch, devices: list[_FakeDevice], **kwargs) -> OakDSource:
    """Crea una OakDSource cuyo _open_device devuelve los fakes en orden.

    `devices` también puede contener excepciones: se lanzan en vez de devolverse
    (simula fallo de conexión).
    """
    source = OakDSource(url="192.168.1.50", **kwargs)
    monkeypatch.setattr(OakDSource, "_load_sdk", lambda self: _fake_dai())
    remaining = list(devices)

    def fake_open(self, dai):
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(OakDSource, "_open_device", fake_open)
    return source


# ---------------------------------------------------------------------------
# Construcción / validación
# ---------------------------------------------------------------------------

def test_url_es_requerida():
    with pytest.raises(ValueError, match="url"):
        OakDSource(url="")


def test_resolucion_invalida_falla_en_constructor():
    with pytest.raises(ValueError, match="resolution"):
        OakDSource(url="192.168.1.50", resolution="8k")


def test_fps_invalido_falla_en_constructor():
    with pytest.raises(ValueError, match="fps"):
        OakDSource(url="192.168.1.50", fps=0)


def test_len_es_indefinido():
    source = OakDSource(url="192.168.1.50")
    # Fuente viva sin longitud definida: TypeError (contrato BaseSource).
    with pytest.raises(TypeError):
        len(source)


def test_sin_sdk_da_import_error_claro():
    source = OakDSource(url="192.168.1.50", reconnect_retries=1)
    # Sin fake instalado y sin depthai en el entorno de test, el import lazy
    # debe fallar con un mensaje accionable.
    with pytest.raises(ImportError, match="depthai"):
        next(iter(source))


# ---------------------------------------------------------------------------
# Emisión de VisualUnits
# ---------------------------------------------------------------------------

def test_emite_visual_units_wallclock(monkeypatch):
    device = _FakeDevice(_FakeQueue(n_frames=3))
    source = _make_source(monkeypatch, [device], max_units=3)

    before_ms = time.time() * 1000.0
    units = list(source)
    after_ms = time.time() * 1000.0

    assert len(units) == 3
    for i, unit in enumerate(units):
        assert unit.unit_id == f"frame_{i:06d}"
        assert unit.frame_index == i
        assert unit.source_type == "video_frame"
        assert unit.source_clock == "wallclock"
        assert unit.width == 1280 and unit.height == 720
        assert unit.pixel_data is not None
        assert unit.pixel_data[0, 0, 0] == i  # frame BGR embebido, en orden
        assert before_ms <= unit.timestamp_ms <= after_ms
    assert device.closed  # el device se cierra al terminar la iteración


def test_source_id_se_propaga(monkeypatch):
    device = _FakeDevice(_FakeQueue(n_frames=1))
    source = _make_source(monkeypatch, [device], max_units=1, source_id="oak_lab")
    units = list(source)
    assert units[0].source_id == "oak_lab"


def test_max_units_corta_la_iteracion(monkeypatch):
    device = _FakeDevice(_FakeQueue(n_frames=100))
    source = _make_source(monkeypatch, [device], max_units=5)
    assert len(list(source)) == 5


# ---------------------------------------------------------------------------
# Parada cooperativa
# ---------------------------------------------------------------------------

def test_stop_interrumpe_el_bucle(monkeypatch):
    # Cola infinita: sin stop, iteraría para siempre.
    device = _FakeDevice(_FakeQueue(n_frames=10**9))
    source = _make_source(monkeypatch, [device])

    units = []
    it = iter(source)
    units.append(next(it))
    source.stop()  # como lo haría RunControl.request_stop() desde otro hilo
    units.extend(it)  # el generador debe terminar solo

    assert len(units) >= 1
    assert device.closed


def test_stop_desde_otro_hilo(monkeypatch):
    device = _FakeDevice(_FakeQueue(n_frames=10**9))
    source = _make_source(monkeypatch, [device])
    units = []

    def consume():
        for unit in source:
            units.append(unit)

    t = threading.Thread(target=consume)
    t.start()
    time.sleep(0.05)
    source.stop()
    t.join(timeout=3.0)
    assert not t.is_alive(), "stop() no destrabó el loop de captura"
    assert device.closed


# ---------------------------------------------------------------------------
# Reconexión
# ---------------------------------------------------------------------------

def test_reconecta_tras_fallo_de_conexion(monkeypatch):
    ok_device = _FakeDevice(_FakeQueue(n_frames=2))
    source = _make_source(
        monkeypatch,
        [ConnectionError("no route"), ok_device],
        max_units=2,
        reconnect_retries=3,
        reconnect_delay_ms=0,
    )
    assert len(list(source)) == 2


def test_agotar_reintentos_lanza_connection_error(monkeypatch):
    fails = [ConnectionError("no route")] * 3
    source = _make_source(
        monkeypatch, fails, reconnect_retries=3, reconnect_delay_ms=0
    )
    with pytest.raises(ConnectionError, match="192.168.1.50"):
        list(source)


def test_fallo_de_lectura_reconecta(monkeypatch):
    # El primer device sirve 2 frames y después falla la lectura; el segundo
    # sirve los restantes. Un frame exitoso resetea el contador de fallos.
    dev1 = _FakeDevice(_FakeQueue(n_frames=10, fail_after=2))
    dev2 = _FakeDevice(_FakeQueue(n_frames=3))
    source = _make_source(
        monkeypatch, [dev1, dev2], max_units=5,
        reconnect_retries=2, reconnect_delay_ms=0,
    )
    units = list(source)
    assert len(units) == 5
    assert dev1.closed and dev2.closed
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /home/simonll4/projects/e-ovrt_media-plane && source .venv/bin/activate && pytest tests/test_oak_d_source.py -v`
Expected: FAIL — `TypeError`/`NotImplementedError` (el stub no acepta `resolution`, `__iter__` lanza NotImplementedError).

- [ ] **Step 3: Implementar `OakDSource`**

Reemplazar `src/eovrt_media/sources/oak_d_source.py` completo con:

```python
"""Fuente viva OAK-D Pro PoE vía DepthAI (RGB, conexión por IP fija).

Requiere el SDK DepthAI v2: pip install 'depthai>=2.24,<3' (extra ``edge``).
Conexión SIEMPRE por IP fija/reserva DHCP (dai.DeviceInfo(ip)); el
autodiscovery por broadcast falla bajo WSL (X_LINK_DEVICE_NOT_FOUND).
Ver docs/contexto/oak-d-integration.md.
"""
from __future__ import annotations

import importlib
import logging
import threading
import time
from typing import Any, Iterator

from eovrt_media.contracts import VisualUnit
from eovrt_media.sources.base import BaseSource

logger = logging.getLogger(__name__)

# resolution del config -> atributo de dai.ColorCameraProperties.SensorResolution
_RESOLUTIONS = {"720p": "THE_720_P", "1080p": "THE_1080_P", "4k": "THE_4_K"}

# Espera entre sondeos de la cola cuando no hay frame: corta para que stop()
# tenga latencia baja, sin busy-loop.
_POLL_INTERVAL_S = 0.01


class OakDSource(BaseSource):
    """Lee el stream RGB de una OAK-D Pro PoE y produce VisualUnits.

    Igual que RtspSource: fuente viva con timestamp de reloj de pared (hace
    significativo max_staleness_ms), parada cooperativa vía stop() y
    reconexión con reintentos. El device DepthAI se abre y se cierra SIEMPRE
    dentro de __iter__ (hilo productor): stop() solo setea un evento.
    """

    SOURCE_CLOCK = "wallclock"

    def __init__(
        self,
        url: str,
        resolution: str = "1080p",
        fps: int = 10,
        reconnect_retries: int = 5,
        reconnect_delay_ms: int = 1000,
        max_units: int | None = None,
        source_id: str | None = None,
    ) -> None:
        if not url:
            raise ValueError(
                "OakDSource requiere url = IP de la cámara (ej. '192.168.1.50', "
                "reservada por DHCP en el router)."
            )
        resolution_key = resolution.lower().strip()
        if resolution_key not in _RESOLUTIONS:
            raise ValueError(
                f"resolution {resolution!r} no soportada para oak_d. "
                f"Opciones: {sorted(_RESOLUTIONS)}."
            )
        if fps <= 0:
            raise ValueError(f"fps debe ser > 0 para oak_d (recibido: {fps}).")
        self.url = url
        self.resolution = resolution_key
        self.fps = fps
        self.reconnect_retries = reconnect_retries
        self.reconnect_delay_ms = reconnect_delay_ms
        self.max_units = max_units
        self.source_id = source_id
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Seams (sobreescribibles en tests con un SDK falso)
    # ------------------------------------------------------------------

    def _load_sdk(self) -> Any:
        """Import lazy de depthai: el servicio no lo requiere si no usa oak_d."""
        try:
            return importlib.import_module("depthai")
        except ImportError as exc:
            raise ImportError(
                "OakDSource (source.type=oak_d) requiere el SDK DepthAI: "
                "pip install 'depthai>=2.24,<3' (o pip install -e '.[edge]')."
            ) from exc

    def _open_device(self, dai: Any) -> Any:
        """Conecta por IP fija (nunca autodiscovery: falla bajo WSL)."""
        return dai.Device(self._build_pipeline(dai), dai.DeviceInfo(self.url))

    # ------------------------------------------------------------------

    def _build_pipeline(self, dai: Any) -> Any:
        pipeline = dai.Pipeline()
        cam = pipeline.create(dai.node.ColorCamera)
        cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        cam.setResolution(
            getattr(dai.ColorCameraProperties.SensorResolution, _RESOLUTIONS[self.resolution])
        )
        cam.setFps(self.fps)
        cam.setInterleaved(False)
        xout = pipeline.create(dai.node.XLinkOut)
        xout.setStreamName("rgb")
        cam.video.link(xout.input)
        return pipeline

    def stop(self) -> None:
        """Interrumpe el bucle de captura tras el frame actual."""
        self._stop_event.set()

    def _register_failure(self, failures: int, exc: Exception) -> int:
        """Cuenta un fallo consecutivo; lanza ConnectionError al agotar."""
        failures += 1
        logger.warning(
            "OAK-D no disponible (intento %d/%d) en %s: %s",
            failures, self.reconnect_retries, self.url, exc,
        )
        if failures >= self.reconnect_retries:
            raise ConnectionError(
                f"OAK-D: no se pudo conectar tras {self.reconnect_retries} "
                f"intentos: {self.url}"
            ) from exc
        if self.reconnect_delay_ms > 0:
            time.sleep(self.reconnect_delay_ms / 1000.0)
        return failures

    def __iter__(self) -> Iterator[VisualUnit]:
        dai = self._load_sdk()
        emitted = 0
        failures = 0
        device: Any = None
        queue: Any = None
        try:
            while True:
                if self._stop_event.is_set():
                    return
                if self.max_units is not None and emitted >= self.max_units:
                    return
                if device is None:
                    try:
                        device = self._open_device(dai)
                        queue = device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
                    except ConnectionError:
                        raise  # ya agotó reintentos adentro de _register_failure
                    except Exception as exc:
                        failures = self._register_failure(failures, exc)
                        continue
                try:
                    msg = queue.tryGet()
                except Exception as exc:
                    device.close()
                    device = None
                    failures = self._register_failure(failures, exc)
                    continue
                if msg is None:
                    # Sin frame todavía: esperar respetando el stop event.
                    if self._stop_event.wait(_POLL_INTERVAL_S):
                        return
                    continue
                frame = msg.getCvFrame()  # BGR (mismo convenio que cv2/RTSP)
                failures = 0
                height, width = frame.shape[:2]
                timestamp_ms = time.time() * 1000.0
                yield VisualUnit(
                    unit_id=f"frame_{emitted:06d}",
                    source_id=self.source_id,
                    source_path=self.url,
                    source_type="video_frame",
                    frame_index=emitted,
                    width=width,
                    height=height,
                    timestamp_ms=round(timestamp_ms, 2),
                    pixel_data=frame,  # evita que image_loader reabra la fuente
                    source_clock=self.SOURCE_CLOCK,
                )
                emitted += 1
        finally:
            if device is not None:
                device.close()

    def __len__(self) -> int:
        # Fuente viva sin longitud definida: TypeError deja que list() caiga a
        # iteración pura (mismo razonamiento que RtspSource.__len__).
        raise TypeError("OakDSource is a live camera with no defined length")
```

- [ ] **Step 4: Verificar que pasan**

Run: `pytest tests/test_oak_d_source.py -v`
Expected: PASS (13 tests).

Nota: `test_sin_sdk_da_import_error_claro` asume que `depthai` NO está instalado en el venv de dev (hoy no lo está). Si en el futuro se instala, ese test necesitará un monkeypatch de `importlib.import_module`; por ahora no.

- [ ] **Step 5: Verificar que la suite existente no se rompió**

Run: `pytest tests/test_capture_timestamps.py tests/test_config_deployment.py -q`
Expected: PASS (el gate del loader sigue vigente hasta la Task 2; `test_capture_timestamps.py:87` valida `SOURCE_CLOCK="wallclock"`, que se conserva).

---

### Task 2: Config schema y loader (`resolution`/`fps`, `url` requerida, quitar el gate)

**Files:**
- Modify: `src/eovrt_media/config/schemas.py:141-181` (`SourceSection`)
- Modify: `src/eovrt_media/config/loader.py:156-159` (quitar gate `NotImplementedError`)
- Test: `tests/test_config_deployment.py:225-230` (reemplazar `test_oak_d_source_type_is_gated`)

**Interfaces:**
- Consumes: `SourceSection` y `_check_locator` existentes; `_LIVE_TYPES = {"rtsp", "oak_d"}` del loader (ya derivan `kind=live` + `rate_control.policy=bounded_freshness`).
- Produces: `SourceSection.resolution: str` (default `"1080p"`) y `SourceSection.fps: int` (default `10`), que la Task 3 pasa a `OakDSource`. `oak_d` sin `url` → `ValueError` en validación.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_config_deployment.py`, dentro de `class TestRtspSourceConfig` (o renombrando el bloque final), **reemplazar** `test_oak_d_source_type_is_gated` (líneas 225-230) por:

```python
    def test_oak_d_derives_live_and_bounded_freshness(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            source={"type": "oak_d", "url": "192.168.1.50"},
        )
        assert cfg.source.kind == "live"
        assert cfg.rate_control.policy == "bounded_freshness"

    def test_oak_d_fields_have_defaults(self, tmp_path: Path):
        cfg = _minimal_config(
            tmp_path,
            source={"type": "oak_d", "url": "192.168.1.50"},
        )
        assert cfg.source.resolution == "1080p"
        assert cfg.source.fps == 10
        assert cfg.source.reconnect_retries == 5
        assert cfg.source.reconnect_delay_ms == 1000

    def test_oak_d_requires_url(self, tmp_path: Path):
        with pytest.raises(ValueError, match="url.*oak_d"):
            _minimal_config(tmp_path, source={"type": "oak_d"})
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_config_deployment.py -q -k oak_d`
Expected: FAIL — `NotImplementedError` (el gate del loader sigue activo) y `resolution` no existe en `SourceSection`.

- [ ] **Step 3: Implementar**

En `src/eovrt_media/config/schemas.py`, dentro de `SourceSection`, después del bloque "Fuente viva (RTSP / cámaras IP)" (líneas 168-171), agregar:

```python
    # Fuente viva OAK-D (DepthAI). `url` = IP fija de la cámara.
    # `resolution`/`fps` solo aplican a source.type=oak_d.
    resolution: str = "1080p"
    fps: int = Field(default=10, gt=0)
```

Y en `_check_locator` (líneas 173-181), agregar la rama `oak_d`:

```python
    @model_validator(mode="after")
    def _check_locator(self) -> SourceSection:
        source_type = self.type.lower().strip()
        if source_type == "rtsp":
            if not (self.url or self.path):
                raise ValueError("source.url es requerido para source.type='rtsp'")
        elif source_type == "oak_d":
            if not self.url:
                raise ValueError(
                    "source.url (IP de la cámara, ej. '192.168.1.50') es requerido "
                    "para source.type='oak_d'"
                )
        elif source_type in _PATH_SOURCE_TYPES and not self.path:
            raise ValueError(f"source.path es requerido para source.type={source_type!r}")
        return self
```

En `src/eovrt_media/config/loader.py`, **eliminar** las líneas 156-159:

```python
    if config.source.type.lower() == "oak_d":
        raise NotImplementedError(
            "source.type=oak_d (OAK-D Pro PoE) está declarado pero no implementado."
        )
```

(No hace falta tocar `_LIVE_TYPES` ni `_SUPPORTED_SOURCE_TYPES`: `oak_d` ya está en ambos.)

- [ ] **Step 4: Verificar que pasan**

Run: `pytest tests/test_config_deployment.py -q`
Expected: PASS completo (incluye los 3 tests nuevos).

---

### Task 3: Registry, run request y tests de API

**Files:**
- Modify: `src/eovrt_media/sources/registry.py:29` y `:69-78`
- Test: `tests/test_ingest_registry.py:24-27`, `tests/test_runs_api.py:127-135`, `tests/test_catalog_api.py:34`

**Interfaces:**
- Consumes: `OakDSource` (Task 1, firma exacta del bloque Produces) y `SourceSection.resolution`/`fps` (Task 2).
- Produces: `create_source(config)` devuelve `OakDSource` para `source.type=oak_d`; `PLUGINS["oak_d"].available == True`. `to_raw_run_config` (run_request.py) no requiere cambios: el gate de disponibilidad es genérico y `oak_d` ya está mapeado en `_PLUGIN_TO_SOURCE_TYPE`.

- [ ] **Step 1: Actualizar los tests que asumen `available=False`**

En `tests/test_ingest_registry.py:27`, cambiar:

```python
    assert plugins["oak_d"]["available"] is False
```

por:

```python
    assert plugins["oak_d"]["available"] is True
```

y agregar al final del archivo (usando los helpers/fixtures ya presentes en ese archivo para construir un `RunConfig`; seguir el patrón del test existente de `rtsp`):

```python
def test_create_source_oak_d(tmp_path):
    from eovrt_media.sources.oak_d_source import OakDSource

    cfg = _run_config(  # usar el helper de construcción de config del propio archivo
        source={"type": "oak_d", "url": "192.168.1.50", "fps": 5, "resolution": "720p"},
    )
    source = create_source(cfg)
    assert isinstance(source, OakDSource)
    assert source.url == "192.168.1.50"
    assert source.fps == 5
    assert source.resolution == "720p"
```

**Nota para el implementador:** abrir `tests/test_ingest_registry.py` y reutilizar su helper real de construcción de configs (el nombre `_run_config` de arriba es ilustrativo — usar el que exista en el archivo, p.ej. el que usa el test de `rtsp`). Si no existe helper, construir el config con `_minimal_config` de `tests/test_config_deployment.py` como referencia.

En `tests/test_runs_api.py:127-135`, el test `test_ingest_plugin_no_disponible_es_4xx` usa `oak_d` como ejemplar de plugin no disponible. Conservar el test (la rama 4xx sigue existiendo) haciéndolo independiente del hardware real, con monkeypatch:

```python
def test_ingest_plugin_no_disponible_es_4xx(client, tmp_path, monkeypatch):
    # La rama available:false debe dar un 4xx claro, no un 500. Ya no hay
    # plugins no disponibles de fábrica (oak_d se implementó), así que se
    # simula uno vía monkeypatch del registro.
    from eovrt_media.sources import registry

    monkeypatch.setitem(
        registry.PLUGINS,
        "oak_d",
        registry.IngestPlugin("oak_d", "live", False, "deshabilitado para test"),
    )
    body = _body(_images(tmp_path))
    body["ingest"]["plugin"] = "oak_d"
    r = client.post("/api/runs", json=body)
    assert 400 <= r.status_code < 500
    assert r.status_code != 500
    assert "oak_d" in r.json()["detail"]
```

En `tests/test_catalog_api.py:34`, cambiar `assert plugins["oak_d"]["available"] is False` por `is True`.

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_ingest_registry.py tests/test_runs_api.py tests/test_catalog_api.py -q`
Expected: FAIL — `available` sigue en False y `create_source` no tiene rama `oak_d`.

- [ ] **Step 3: Implementar en el registry**

En `src/eovrt_media/sources/registry.py:29`, cambiar:

```python
    "oak_d": IngestPlugin("oak_d", "live", False, "OAK-D Pro PoE (hardware no disponible)"),
```

por:

```python
    "oak_d": IngestPlugin("oak_d", "live", True, "OAK-D Pro PoE (RGB vía DepthAI, IP fija)"),
```

Y al final de `create_source` (líneas 69-78), reemplazar el bloque final:

```python
    # rtsp (live)
    from eovrt_media.sources import RtspSource

    return RtspSource(
        url=config.source.url or config.source.path,
        reconnect_retries=config.source.reconnect_retries,
        reconnect_delay_ms=config.source.reconnect_delay_ms,
        max_units=config.run.max_units,
        source_id=config.source.source_id,
    )
```

por:

```python
    if plugin_id == "rtsp":
        from eovrt_media.sources import RtspSource

        return RtspSource(
            url=config.source.url or config.source.path,
            reconnect_retries=config.source.reconnect_retries,
            reconnect_delay_ms=config.source.reconnect_delay_ms,
            max_units=config.run.max_units,
            source_id=config.source.source_id,
        )
    # oak_d (live)
    from eovrt_media.sources import OakDSource

    return OakDSource(
        url=config.source.url,
        resolution=config.source.resolution,
        fps=config.source.fps,
        reconnect_retries=config.source.reconnect_retries,
        reconnect_delay_ms=config.source.reconnect_delay_ms,
        max_units=config.run.max_units,
        source_id=config.source.source_id,
    )
```

- [ ] **Step 4: Verificar que pasan**

Run: `pytest tests/test_ingest_registry.py tests/test_runs_api.py tests/test_catalog_api.py -q`
Expected: PASS.

- [ ] **Step 5: Suite completa + lint**

Run: `make test && make lint`
Expected: PASS ambos. Si algún otro test asumía `oak_d` no disponible (buscar con `grep -rn "oak" tests/`), actualizarlo con el mismo criterio de los de arriba.

---

### Task 4: Dependencia `depthai` y config de ejemplo

**Files:**
- Modify: `pyproject.toml:19` (extra `edge`)
- Create: `configs/runs/local/oak_d_camera.yaml` (directorio git-ignoreado)

**Interfaces:**
- Consumes: knobs de `SourceSection` (Task 2).
- Produces: `pip install -e ".[edge]"` instala el SDK; config de ejemplo listo para el run real con hardware.

- [ ] **Step 1: Agregar el extra**

En `pyproject.toml:19`, cambiar:

```toml
edge = []
```

por:

```toml
edge = ["depthai>=2.24,<3"]
```

- [ ] **Step 2: Crear el config de ejemplo**

Crear `configs/runs/local/oak_d_camera.yaml`:

```yaml
# OAK-D Pro PoE — run de prueba con modelo mock.
# La IP es la reserva DHCP de la cámara en el router (ver
# docs/contexto/oak-d-integration.md). Este directorio está git-ignoreado.
source:
  type: oak_d
  url: "192.168.1.50"
  fps: 10
  resolution: 1080p
  reconnect_retries: 3
  reconnect_delay_ms: 1000

model:
  ref: mock

rate_control:
  policy: bounded_freshness
  max_staleness_ms: 1000

run:
  max_units: 50   # run acotado de smoke; quitar para run continuo
```

- [ ] **Step 3: Verificar que el config valida**

Run:
```bash
python3 - <<'EOF'
from pathlib import Path
from eovrt_media.config.loader import load_run_config
cfg = load_run_config(Path("configs/runs/local/oak_d_camera.yaml"))
print(cfg.source.type, cfg.source.url, cfg.source.kind, cfg.rate_control.policy)
EOF
```
Expected: imprime `oak_d 192.168.1.50 live bounded_freshness` sin excepciones.

- [ ] **Step 4: (Opcional, requiere red) Instalar el SDK en el venv**

Run: `pip install -e ".[edge]"`
Expected: instala `depthai` 2.x. Si se instala, correr `pytest tests/test_oak_d_source.py -q`: el test `test_sin_sdk_da_import_error_claro` fallará (el SDK ahora existe) — en ese caso marcar ese test con:

```python
@pytest.mark.skipif(
    importlib.util.find_spec("depthai") is not None,
    reason="depthai instalado: el ImportError lazy no aplica",
)
```

(agregando `import importlib.util` arriba del archivo de test). Si no se instala el SDK en este paso, no tocar nada.

---

### Task 5: Documentación

**Files:**
- Create: `docs/contexto/oak-d-integration.md`
- Modify: `CLAUDE.md` (línea "OakDSource (OAK-D Pro PoE deferred, raises NotImplementedError)")
- Modify: `docs/implementation-status.md`, `docs/usage.md`, `docs/architecture.md` (menciones "diferido/no implementado")
- Modify: `/home/simonll4/projects/docs/operacion/30-runbook-local.md:102,178` (repo `docs`, hermano)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: la referencia `docs/contexto/oak-d-integration.md` citada por el docstring de la fuente deja de ser un enlace roto.

- [ ] **Step 1: Crear `docs/contexto/oak-d-integration.md`**

```markdown
# OAK-D Pro PoE: integración como fuente viva (`oak_d`)

Estado: implementado (2026-07-13). Spec:
`docs/superpowers/specs/2026-07-13-oak-d-source-design.md`.

## Topología de red

La cámara y la PC se conectan por Ethernet al router. La cámara toma IP por
DHCP; se le hace **reserva DHCP** en el router (ej. `192.168.1.50`) para que
nunca cambie. El servicio (en WSL) se conecta directo a esa IP.

    Router (DHCP, 192.168.1.1)
      ├── Ethernet ── PC (WSL2, NAT hacia la LAN)
      └── Ethernet/PoE ── OAK-D Pro PoE (reserva: 192.168.1.50)

**Regla dura: conexión por IP fija (`dai.DeviceInfo(ip)`), nunca
autodiscovery.** El descubrimiento por broadcast falla bajo WSL/Hyper-V con
`X_LINK_DEVICE_NOT_FOUND`; la conexión directa por IP no depende de él.

## SDK

- `pip install -e ".[edge]"` → `depthai>=2.24,<3` (API v2). La import es lazy:
  el servicio arranca sin el SDK si no se usa la fuente.
- Pipeline: `ColorCamera` (CAM_A, `setResolution`/`setFps`) → `XLinkOut("rgb")`;
  frames BGR vía `getCvFrame()`.

## Config

```yaml
source:
  type: oak_d
  url: "192.168.1.50"      # requerido: IP de la cámara
  fps: 10                   # default 10
  resolution: 1080p         # 720p | 1080p | 4k (default 1080p)
  reconnect_retries: 3
  reconnect_delay_ms: 1000
```

Ejemplo completo: `configs/runs/local/oak_d_camera.yaml`. Fuente viva:
`kind=live` y `rate_control.policy=bounded_freshness` se derivan solos;
`source_clock=wallclock` habilita t_capture→alert (spec 40/42).

## Smoke test con hardware

```bash
ping 192.168.1.50
python3 -c "import depthai as dai; print(dai.DeviceInfo('192.168.1.50'))"
# run real (servicio en :8080 con EOVRT_MODEL_REF=mock):
curl -X POST http://localhost:8080/api/runs -H "Content-Type: application/json" -d '{
  "ingest": {"plugin": "oak_d", "config": {"url": "192.168.1.50"}},
  "prompts": {"set_inline": {"id": "demo", "classes": [{"id": "person",
    "phrasings": {"default": ["person"]}}]}, "active_ids": ["person"]},
  "run": {"max_units": 50}
}'
```

Verificar: `runs/<id>/detections.jsonl` con frames 1920×1080,
`capture_wallclock_ms` creciente, y `POST /api/runs/<id>/stop` detiene en <3 s.

## Troubleshooting

- `X_LINK_DEVICE_NOT_FOUND`: se está usando autodiscovery o la IP es
  incorrecta. Verificar `ping` y la reserva DHCP; usar siempre IP directa.
- La cámara no toma IP: revisar que el switch/inyector sea PoE (802.3af).
- Timeouts intermitentes bajo WSL: verificar que Windows no tenga firewall
  bloqueando el rango; la conexión es TCP saliente desde WSL (NAT), no entrante.
```

- [ ] **Step 2: Actualizar menciones "no implementado"**

- `CLAUDE.md` (media-plane, sección Key abstractions): cambiar
  `OakDSource (OAK-D Pro PoE deferred, raises NotImplementedError)` por
  `OakDSource (OAK-D Pro PoE via DepthAI, live RGB, IP fija — ver docs/contexto/oak-d-integration.md)`.
- `docs/implementation-status.md`, `docs/usage.md`, `docs/architecture.md`:
  localizar con `grep -rn -i "oak" docs/*.md` y actualizar cada mención de
  "diferido / no implementado / hardware no disponible" al estado implementado,
  apuntando a `docs/contexto/oak-d-integration.md`.
- Repo `docs` (hermano): `/home/simonll4/projects/docs/operacion/30-runbook-local.md`
  líneas 102 y 178 — quitar "deshabilitado, hasta tener el hardware" / "sin
  hardware", indicando que `oak_d` está disponible y requiere la cámara en la
  LAN (IP fija) + `pip install -e ".[edge]"`.

- [ ] **Step 3: Verificar enlaces**

Run: `grep -rn "oak-d-integration" src docs CLAUDE.md`
Expected: el docstring de `oak_d_source.py` y las menciones de docs apuntan a un archivo que ahora existe (`ls docs/contexto/oak-d-integration.md`).

---

### Task 6: Verificación integral sin hardware

**Files:** ninguno (solo verificación).

- [ ] **Step 1: Suite completa y lint**

Run: `cd /home/simonll4/projects/e-ovrt_media-plane && source .venv/bin/activate && make test && make lint`
Expected: PASS ambos, cero fallos.

- [ ] **Step 2: Servicio con plugin oak_d apuntando a IP inexistente falla limpio**

```bash
EOVRT_MODEL_REF=mock make serve &   # esperar /readyz
sleep 5 && curl -s http://localhost:8080/readyz
curl -s -X POST http://localhost:8080/api/runs -H "Content-Type: application/json" -d '{
  "ingest": {"plugin": "oak_d", "config": {"url": "192.0.2.1", "reconnect_retries": 2, "reconnect_delay_ms": 200}},
  "prompts": {"set_inline": {"id": "demo", "classes": [{"id": "person",
    "phrasings": {"default": ["person"]}}]}, "active_ids": ["person"]},
  "run": {"max_units": 5}
}'
```

Expected: el POST devuelve **201** (el plugin está disponible; la conexión se
intenta dentro del run). Luego `GET /api/runs/<run_id>` termina en estado
`failed` en ~30 s (2 reintentos × delay + timeout de conexión del SDK; el SDK
real puede tardar más que el fake — no debe colgar indefinidamente) con el
`ConnectionError` registrado en `errors.jsonl`. Nunca un 500 en el POST.
Matar el serve al terminar (`kill %1`).

Nota: este paso requiere `depthai` instalado (Task 4 Step 4). Si no se
instaló, el run debe fallar igual de limpio pero con el `ImportError`
accionable en `errors.jsonl` — verificar eso en su lugar.

- [ ] **Step 3: Reporte final**

Informar al usuario: implementación lista SIN COMMITEAR (regla del workspace),
qué se verificó, y el checklist pendiente con hardware (conectar cámara →
reserva DHCP → `ping` → smoke de `docs/contexto/oak-d-integration.md` →
ajustar la IP real en `configs/runs/local/oak_d_camera.yaml`).

> **Nota post-ejecución:** el plan se ejecutó completo. Después se agregaron, fuera de
> plan, el knob `orientation` (hallazgo con hardware real: cámara montada invertida) y
> los endurecimientos de la revisión de código (ver Addendum de la spec). Los tests y
> docs de esos cambios siguen el mismo patrón de las tasks de este plan.
