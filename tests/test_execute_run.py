import threading
import time
from pathlib import Path

from PIL import Image

from eovrt_media.config.loader import load_run_config_data
from eovrt_media.models import create_adapter
from eovrt_media.runtime.pipeline import RunControl, execute_run
from eovrt_media.service.events import EventBroadcaster

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
