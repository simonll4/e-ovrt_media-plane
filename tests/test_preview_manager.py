import json
import struct
import time

import pytest
from PIL import Image

from eovrt_media.config.loader import resolve_model_ref
from eovrt_media.models import create_adapter
from eovrt_media.service.activity_slot import ActivitySlot, SlotBusyError
from eovrt_media.service.preview_manager import PreviewManager
from eovrt_media.service.preview_request import PreviewRequest
from eovrt_media.service.settings import ServiceSettings

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _images(tmp_path, n=3):
    folder = tmp_path / "imgs"
    # parents=True: test_ocupa_y_libera_slot llama a _images(tmp_path / "b") cuyo
    # padre "b" no existe todavía (deviation del brief, que usaba folder.mkdir()).
    folder.mkdir(parents=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i, 2, 3)).save(folder / f"f{i}.png")
    return folder


@pytest.fixture()
def manager(tmp_path):
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "runs")}
    )
    model_section = resolve_model_ref(settings.model_ref, settings.catalog_root)
    adapter = create_adapter(model_section)
    adapter.load()
    mgr = PreviewManager(adapter, model_section, settings, ActivitySlot())
    yield mgr
    mgr.stop()


def _req(folder, mode="raw", **kw):
    body = {"mode": mode, "ingest": {"plugin": "image_folder", "config": {"path": str(folder)}}}
    if mode == "detect":
        body["prompts"] = {"set_inline": SET_INLINE}
    body.update(kw)
    return PreviewRequest(**body)


def _wait_frame(mgr, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, seq, latest, _ = mgr.snapshot()
        if latest is not None:
            return latest
        if status == "error":
            raise AssertionError(mgr.status())
        time.sleep(0.05)
    raise AssertionError("sin frame")


def _parse(msg):
    hlen = struct.unpack(">I", msg[:4])[0]
    header = json.loads(msg[4 : 4 + hlen].decode("utf-8"))
    jpeg = msg[4 + hlen :]
    return header, jpeg


def test_raw_produce_frames_sin_detecciones(manager, tmp_path):
    manager.start(_req(_images(tmp_path)))
    header, jpeg = _parse(_wait_frame(manager))
    assert header["mode"] == "raw"
    assert header["detections"] == []
    assert header["seq"] >= 1 and header["width"] == 64 and header["height"] == 48
    assert jpeg[:2] == b"\xff\xd8"  # magic JPEG


def test_detect_produce_detecciones_normalizadas(manager, tmp_path):
    manager.start(_req(_images(tmp_path), mode="detect"))
    header, _ = _parse(_wait_frame(manager))
    assert header["mode"] == "detect"
    for d in header["detections"]:
        assert set(d) == {"label", "score", "bbox_norm_xyxy"}
        assert all(0.0 <= v <= 1.0 for v in d["bbox_norm_xyxy"])


def test_threshold_filtra(manager, tmp_path):
    manager.start(_req(_images(tmp_path), mode="detect", params={"score_threshold": 1.0}))
    header, _ = _parse(_wait_frame(manager))
    assert header["detections"] == []


def test_ocupa_y_libera_slot(manager, tmp_path):
    # n=200 (deviation del brief, que usaba el default n=3): con 3 imágenes de
    # 64x48 en modo raw el loop de preview termina y libera el slot antes de
    # que el hilo principal alcance a crear el segundo folder e invocar el
    # segundo start(), volviendo el test flaky-siempre-falla en vez de
    # flaky-a-veces. Más imágenes mantienen la sesión viva el tiempo
    # suficiente para ejercitar el rechazo por slot ocupado.
    manager.start(_req(_images(tmp_path, n=200)))
    with pytest.raises(SlotBusyError):
        manager.start(_req(_images(tmp_path / "b")))
    manager.stop()
    assert manager.status()["status"] == "idle"
    assert not manager.is_active()


def test_slot_ocupado_por_run_rechaza(manager, tmp_path):
    manager._slot.acquire("run", "run_1")
    with pytest.raises(SlotBusyError) as exc:
        manager.start(_req(_images(tmp_path)))
    assert exc.value.owner_kind == "run"
    assert exc.value.owner_id == "run_1"


def test_fuente_invalida_da_valueerror_sin_ocupar_slot(manager, tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        manager.start(_req(tmp_path / "no_existe"))
    assert manager._slot.owner is None


def test_fuente_agotada_termina_en_idle(manager, tmp_path):
    manager.start(_req(_images(tmp_path, n=2)))
    deadline = time.monotonic() + 10
    while manager.is_active() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert manager.status()["status"] == "idle"
    assert manager._slot.owner is None


def test_backlog_no_se_acumula_bajo_procesamiento_lento(manager, tmp_path, monkeypatch):
    """Reproduce el bug real: una fuente rápida (RTSP en la práctica) con un
    consumidor lento no debe hacer que el preview procese en orden desde el
    frame más viejo (eso es exactamente el "cada vez más lento" que se ve con
    cv2.VideoCapture + RTSP sin drenar su buffer). Debe saltar al más reciente.
    """
    n = 300
    folder = _images(tmp_path, n=n)
    original = type(manager)._build_message

    def slow_build_message(self, *args, **kwargs):
        time.sleep(0.02)  # simula un ciclo de proceso lento (resize+encode+detección)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(manager), "_build_message", slow_build_message)

    manager.start(_req(folder))
    time.sleep(0.4)
    manager.stop()

    _, seq, latest, error = manager.snapshot()
    assert error is None
    assert latest is not None
    assert 0 < seq < n  # no le dio tiempo a procesar todo el backlog: perfectamente esperado
    header, _ = _parse(latest)
    # unit_id de ImageFolderSource: "img_{index:06d}". Si el consumo fuera serial
    # (el bug), el último frame publicado en 0.4s a ~20ms/frame rondaría el índice
    # ~20, muy lejos de la cola de 300. Con el fix, el reader ya drenó el backlog
    # y el último publicado está cerca del final.
    last_index = int(header["unit_id"].rsplit("_", 1)[-1])
    assert last_index >= n - 5
