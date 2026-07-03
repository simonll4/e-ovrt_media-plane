import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.contracts import VisualUnit
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import (
    PRODUCER_JOIN_TIMEOUT_AFTER_STALL_S,
    STOP_DRAIN_SECONDS,
    RunControl,
    execute_run,
)
from eovrt_media.service.events import EventBroadcaster
from eovrt_media.sources.base import BaseSource

REPO_ROOT = Path(__file__).resolve().parents[1]
SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def _make_images(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (i * 10 % 255, 0, 0)).save(folder / f"img_{i:03d}.png")


def _config(tmp_path, images: Path, run_id: str, max_units=None):
    raw = {
        "run": {"id": run_id, "max_units": max_units},
        "source": {"type": "image_folder", "path": str(images)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
        "outputs": {"run_dir": str(tmp_path / "runs"), "save_previews": False},
    }
    return load_run_config_data(raw, plane_root=REPO_ROOT / "configs")


def test_dos_runs_secuenciales_con_el_mismo_adapter(tmp_path):
    images = tmp_path / "imgs"
    _make_images(images, 3)
    adapter = create_adapter(_config(tmp_path, images, "r1").model)
    adapter.load()
    try:
        rid1 = execute_run(_config(tmp_path, images, "r1"), adapter)
        rid2 = execute_run(_config(tmp_path, images, "r2"), adapter)  # adapter sigue vivo
    finally:
        adapter.close()
    for rid in (rid1, rid2):
        assert (tmp_path / "runs" / rid / "summary.json").exists()
        assert (tmp_path / "runs" / rid / "detections.jsonl").exists()


def test_stop_interrumpe_run_bounded(tmp_path):
    images = tmp_path / "imgs"
    _make_images(images, 300)
    config = _config(tmp_path, images, "r_stop")
    adapter = create_adapter(config.model)
    adapter.load()
    control = RunControl()
    result: dict = {}

    def _run():
        result["rid"] = execute_run(config, adapter, control=control)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.3)
    control.request_stop()
    t.join(timeout=10.0)
    adapter.close()
    assert not t.is_alive(), "execute_run no terminó tras request_stop()"
    assert (tmp_path / "runs" / "r_stop" / "summary.json").exists()


class _HangingSource(BaseSource):
    """Fuente que emite unas pocas unidades y luego bloquea PARA SIEMPRE en el
    iterador, ignorando ``stop()`` — simula un RTSP colgado en un ``recv`` a
    nivel C (el escenario auditado: "Alta"). ``stop()`` es intencionalmente
    un no-op para que ``RunControl.request_stop()`` no logre destrabar al
    productor.
    """

    def __init__(self, n_before_hang: int = 3) -> None:
        self._n = n_before_hang
        self._never_set = threading.Event()  # nunca se setea: cuelga el iterador

    def __iter__(self):
        for index in range(self._n):
            yield VisualUnit(
                unit_id=f"hang-{index}",
                source_id="hanging-cam",
                source_type="video_frame",
                frame_index=index,
                timestamp_ms=float(index),
                width=8,
                height=8,
                pixel_data=np.zeros((8, 8, 3), dtype=np.uint8),
            )
        self._never_set.wait()  # bloquea para siempre — simula el recv() colgado

    def stop(self) -> None:
        pass  # a propósito: ignora stop(), a diferencia de una fuente responsive

    def __len__(self) -> int:
        raise TypeError("fuente en vivo: longitud indefinida")


def test_stop_fuerza_salida_si_productor_ignora_stop_y_nunca_cierra_transporte(
    tmp_path, monkeypatch
):
    """Ancla del bug auditado (Alta): sin el drain-window del consumer, esto
    cuelga para siempre (el productor nunca cierra el transporte porque la
    fuente ignora stop()) y el `t.join(timeout=...)` de abajo expiraría con
    el thread todavía vivo — el assert `not t.is_alive()` fallaría en vez de
    trabar la suite, gracias a los timeouts acotados usados acá.
    """
    images = tmp_path / "imgs"
    _make_images(images, 3)  # config válida; la fuente real se monkeypatchea abajo
    config = _config(tmp_path, images, "r_hang")
    adapter = create_adapter(config.model)
    adapter.load()

    hanging_source = _HangingSource(n_before_hang=3)
    monkeypatch.setattr(
        "eovrt_media.runtime.pipeline.create_source", lambda cfg: hanging_source
    )

    control = RunControl()
    result: dict = {}

    def _run():
        result["rid"] = execute_run(config, adapter, control=control)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.3)  # dejar que el consumer procese las unidades ya encoladas
    control.request_stop()
    # Cota superior determinista: ventana de drenaje + join corto tras stall + margen.
    bound = STOP_DRAIN_SECONDS + PRODUCER_JOIN_TIMEOUT_AFTER_STALL_S + 10.0
    t.join(timeout=bound)
    adapter.close()
    assert not t.is_alive(), "execute_run no terminó tras request_stop() con fuente colgada"
    assert (tmp_path / "runs" / "r_hang" / "summary.json").exists()


def test_event_sink_recibe_metricas(tmp_path):
    images = tmp_path / "imgs"
    _make_images(images, 3)
    config = _config(tmp_path, images, "r_ev")
    adapter = create_adapter(config.model)
    adapter.load()
    broadcaster = EventBroadcaster()
    sub = broadcaster.subscribe()
    execute_run(config, adapter, event_sink=broadcaster)
    adapter.close()
    types = {e["type"] for e in sub.drain()}
    assert "metric" in types and "detection" in types
