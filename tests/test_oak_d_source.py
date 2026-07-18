"""OakDSource — fuente viva OAK-D Pro PoE, testeada con un SDK DepthAI falso."""
from __future__ import annotations

import json as _json
import threading
import time
from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from eovrt_media.config.schemas import OakDPrefilterConfig
from eovrt_media.sources.oak_d_source import OakDSource


# ---------------------------------------------------------------------------
# Fake del SDK DepthAI (API v2): suficiente para _build_pipeline y el loop de
# captura. No requiere depthai instalado.
# ---------------------------------------------------------------------------

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
        return _FakeMsg(frame, ts=timedelta(seconds=100.0) - timedelta(milliseconds=42))


class _FakeStatsQueue:
    """Cola prefilter_stats: entrega los payloads dados y después None."""

    def __init__(self, payloads: list[bytes]) -> None:
        self._payloads = list(payloads)

    def tryGet(self):
        if not self._payloads:
            return None
        data = self._payloads.pop(0)
        return SimpleNamespace(getData=lambda: data)


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

    def close(self) -> None:
        self.closed = True


class _FakeNode:
    """Nodo fake: absorbe cualquier llamada de configuración y la registra."""

    def __init__(self, calls: dict) -> None:
        self.video = SimpleNamespace(link=lambda _inp: None)
        _sink = lambda: SimpleNamespace(  # noqa: E731
            setBlocking=lambda *_: None, setQueueSize=lambda *_: None,
            link=lambda *_: None,
        )
        self.input = _sink()
        self.preview = SimpleNamespace(link=lambda _inp: None)
        self.out = SimpleNamespace(link=lambda _inp: None)
        self.inputs = defaultdict(_sink)
        self.outputs = defaultdict(_sink)
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

    def setXLinkChunkSize(self, size: int) -> None:
        self._calls["setXLinkChunkSize"] = size


def _fake_dai(calls: dict | None = None) -> SimpleNamespace:
    """Módulo depthai falso con los símbolos que usa _build_pipeline.

    `calls` recoge las llamadas de configuración hechas sobre los nodos, para
    poder afirmar sobre ellas (p.ej. setImageOrientation).
    """
    calls = calls if calls is not None else {}
    return SimpleNamespace(
        Pipeline=lambda: _FakePipeline(calls),
        node=SimpleNamespace(
            ColorCamera=object, XLinkOut=object,
            MobileNetDetectionNetwork=object, Script=object,
        ),
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
        Clock=SimpleNamespace(now=lambda: timedelta(seconds=100.0)),
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


def test_warmup_frames_descarta_los_primeros(monkeypatch):
    # _FakeQueue marca frame[0,0]=served (0,1,2,...). warmup_frames=2 descarta los
    # dos primeros ANTES de emitir: el primer VisualUnit es el 3er frame (served=2)
    # y lleva frame_index=0 (contador arranca en el primer frame asentado).
    device = _FakeDevice(_FakeQueue(n_frames=10))
    source = _make_source(monkeypatch, [device], max_units=2, warmup_frames=2)
    units = list(source)
    assert len(units) == 2
    assert units[0].unit_id == "frame_000000" and units[0].frame_index == 0
    assert units[1].frame_index == 1
    assert units[0].pixel_data[0, 0, 0] == 2  # se saltearon served 0 y 1
    assert units[1].pixel_data[0, 0, 0] == 3


def test_warmup_frames_cero_no_descarta_nada(monkeypatch):
    device = _FakeDevice(_FakeQueue(n_frames=10))
    source = _make_source(monkeypatch, [device], max_units=1, warmup_frames=0)
    units = list(source)
    assert units[0].pixel_data[0, 0, 0] == 0


def test_warmup_se_reaplica_al_reabrir_el_device(monkeypatch):
    # Reabrir el device reinicia el pipeline dentro de la cámara: el sensor
    # vuelve a asentar exposición/enfoque, así que el warm-up es POR DEVICE.
    # dev1 sirve served=0 (descartado), served=1 (emitido) y falla la lectura;
    # dev2 debe volver a descartar su primer frame (served=0) antes de emitir.
    dev1 = _FakeDevice(_FakeQueue(n_frames=10, fail_after=2))
    dev2 = _FakeDevice(_FakeQueue(n_frames=3))
    source = _make_source(
        monkeypatch, [dev1, dev2], max_units=3, warmup_frames=1,
        reconnect_retries=2, reconnect_delay_ms=0,
    )
    units = list(source)
    assert len(units) == 3
    # dev1 emitió served=1; dev2 re-descartó served=0 y emitió served=1,2.
    assert [u.pixel_data[0, 0, 0] for u in units] == [1, 1, 2]
    # El contador de emisión no se ve afectado por los descartes.
    assert [u.frame_index for u in units] == [0, 1, 2]


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


# ---------------------------------------------------------------------------
# Latency knobs (xlink_chunk_size, isp_scale)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# capture_to_host_ms (spec 2026-07-15 §7.3)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Prefiltrado on-device EN-2 (spec 2026-07-15 §5/§6)
# ---------------------------------------------------------------------------


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


def test_iter_survives_stats_getdata_raising_unexpected_exception(monkeypatch, tmp_path):
    """bytes(stats_msg.getData()) puede lanzar algo distinto de ValueError/
    UnicodeDecodeError (p. ej. TypeError si getData() no es bytes-able); la cola
    prefilter_stats no debe poder tumbar la corrida (spec §9)."""
    blob = tmp_path / "person.blob"
    blob.write_bytes(b"\x00")
    device = _FakeDevice(_FakeQueue(n_frames=1),
                         stats_queue=_FakeStatsQueue([object()]))
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
