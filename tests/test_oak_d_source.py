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
    def __init__(self, queue: _FakeQueue, queue_fails: bool = False) -> None:
        self.queue = queue
        self.closed = False
        self._queue_fails = queue_fails

    def getOutputQueue(self, name: str, maxSize: int, blocking: bool) -> _FakeQueue:
        assert name == "rgb"
        assert maxSize == 1  # fuente viva: solo el frame más fresco (staleness real)
        if self._queue_fails:
            raise RuntimeError("X_LINK: no se pudo abrir la cola")
        return self.queue

    def close(self) -> None:
        self.closed = True


class _FakeNode:
    """Nodo fake: absorbe cualquier llamada de configuración y la registra."""

    def __init__(self, calls: dict) -> None:
        self.video = SimpleNamespace(link=lambda _inp: None)
        self.input = object()
        self._calls = calls

    def __getattr__(self, name: str):
        def _rec(*args, **kwargs):
            self._calls[name] = args[0] if len(args) == 1 else args
        return _rec


class _FakePipeline:
    def __init__(self, calls: dict) -> None:
        self._calls = calls

    def create(self, node_cls):
        return _FakeNode(self._calls)


def _fake_dai(calls: dict | None = None) -> SimpleNamespace:
    """Módulo depthai falso con los símbolos que usa _build_pipeline.

    `calls` recoge las llamadas de configuración hechas sobre los nodos, para
    poder afirmar sobre ellas (p.ej. setImageOrientation).
    """
    calls = calls if calls is not None else {}
    return SimpleNamespace(
        Pipeline=lambda: _FakePipeline(calls),
        node=SimpleNamespace(ColorCamera=object, XLinkOut=object),
        ColorCameraProperties=SimpleNamespace(
            SensorResolution=SimpleNamespace(
                THE_720_P="720p", THE_1080_P="1080p", THE_4_K="4k"
            )
        ),
        CameraImageOrientation=SimpleNamespace(
            NORMAL="NORMAL",
            ROTATE_180_DEG="ROTATE_180_DEG",
            HORIZONTAL_MIRROR="HORIZONTAL_MIRROR",
            VERTICAL_FLIP="VERTICAL_FLIP",
        ),
        CameraBoardSocket=SimpleNamespace(CAM_A="cam_a"),
        DeviceInfo=lambda ip: SimpleNamespace(ip=ip),
    )


def _make_source(monkeypatch, devices: list, url: str = "192.168.1.50", **kwargs) -> OakDSource:
    """Crea una OakDSource cuyo _open_device devuelve los fakes en orden.

    `devices` también puede contener excepciones: se lanzan en vez de devolverse
    (simula fallo de conexión).
    """
    source = OakDSource(url=url, **kwargs)
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


def test_orientation_invalida_falla_en_constructor():
    with pytest.raises(ValueError, match="orientation"):
        OakDSource(url="192.168.1.50", orientation="de_costado")


def test_orientation_default_es_normal_y_no_toca_el_sensor():
    # Sin knob, no se llama a setImageOrientation: comportamiento inalterado.
    calls: dict = {}
    src = OakDSource(url="192.168.1.50")
    src._build_pipeline(_fake_dai(calls))
    assert "setImageOrientation" not in calls


def test_orientation_rotate_180_configura_el_sensor():
    # La camara del laboratorio esta montada invertida: el ISP rota, no la CPU.
    calls: dict = {}
    src = OakDSource(url="192.168.1.50", orientation="rotate_180")
    src._build_pipeline(_fake_dai(calls))
    assert calls["setImageOrientation"] == "ROTATE_180_DEG"


def test_len_es_indefinido():
    source = OakDSource(url="192.168.1.50")
    # Fuente viva sin longitud definida: TypeError (contrato BaseSource).
    with pytest.raises(TypeError):
        len(source)


def test_sin_sdk_da_import_error_claro():
    source = OakDSource(url="192.168.1.50", reconnect_retries=1)
    # Sin fake instalado y sin depthai en el entorno de test, el import lazy
    # debe fallar con un mensaje accionable.
    try:
        import depthai  # noqa: F401
        pytest.skip("depthai instalado: el ImportError lazy no aplica")
    except ImportError:
        pass
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


def test_fallo_al_abrir_la_cola_cierra_device_y_reconecta(monkeypatch):
    # _open_device tiene éxito pero getOutputQueue lanza: el device recién
    # abierto debe cerrarse y contarse UN solo fallo (no dos, ni livelock
    # con la cola del device anterior).
    bad = _FakeDevice(_FakeQueue(n_frames=0), queue_fails=True)
    good = _FakeDevice(_FakeQueue(n_frames=3))
    source = _make_source(
        monkeypatch, [bad, good], max_units=2,
        reconnect_retries=2, reconnect_delay_ms=0,
    )
    units = list(source)
    assert len(units) == 2
    assert bad.closed and good.closed


def test_stop_durante_backoff_de_reconexion_no_bloquea(monkeypatch):
    # Cámara caída con delay de reconexión largo: stop() debe interrumpir la
    # espera del backoff, no dormir el delay completo.
    fails = [ConnectionError("no route")] * 5
    source = _make_source(
        monkeypatch, fails, reconnect_retries=5, reconnect_delay_ms=60_000
    )
    t = threading.Thread(target=lambda: list(source))
    t.start()
    time.sleep(0.1)
    source.stop()
    t.join(timeout=2.0)
    assert not t.is_alive(), "stop() no interrumpió el backoff de reconexión"


def test_stream_mudo_dispara_reconexion(monkeypatch):
    # Conexión viva pero cola que nunca entrega frames (pipeline colgado en la
    # cámara): el watchdog debe cerrar el device y reconectar, no esperar
    # para siempre.
    import eovrt_media.sources.oak_d_source as mod

    monkeypatch.setattr(mod, "_NO_FRAME_TIMEOUT_S", 0.05)
    mute = _FakeDevice(_FakeQueue(n_frames=0))
    good = _FakeDevice(_FakeQueue(n_frames=3))
    source = _make_source(
        monkeypatch, [mute, good], max_units=3,
        reconnect_retries=3, reconnect_delay_ms=0,
    )
    units = list(source)
    assert len(units) == 3
    assert mute.closed


def test_error_de_conexion_redacta_credenciales(monkeypatch):
    # Paridad con RtspSource: la URL cruda nunca va a logs ni a errors.jsonl
    # (se sirve sin autenticación por la API).
    fails = [ConnectionError("no route")] * 2
    source = _make_source(
        monkeypatch, fails, url="tcp://user:secreto@192.168.1.50",
        reconnect_retries=2, reconnect_delay_ms=0,
    )
    with pytest.raises(ConnectionError) as ei:
        list(source)
    assert "secreto" not in str(ei.value)


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
