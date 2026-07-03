import json
import time

import pytest
from PIL import Image

from eovrt_media.config.loader import resolve_model_ref
from eovrt_media.models import create_adapter
from eovrt_media.service.run_manager import RunBusyError, RunManager, UnknownRunError
from eovrt_media.service.run_request import RunRequest
from eovrt_media.service.settings import ServiceSettings

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


@pytest.fixture()
def manager(tmp_path):
    model_section = resolve_model_ref("mock")
    adapter = create_adapter(model_section)
    adapter.load()
    settings = ServiceSettings.from_env(
        {
            "EOVRT_MODEL_REF": "mock",
            "EOVRT_RUNS_DIR": str(tmp_path / "runs"),
            "EOVRT_WATCHDOG_SECONDS": "60",
        }
    )
    m = RunManager(adapter, model_section, settings)
    yield m
    m.shutdown()
    adapter.close()


def _images(tmp_path, n=3):
    folder = tmp_path / "imgs"
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (64, 48), (10, 20, 30)).save(folder / f"i{i:03d}.png")
    return folder


def _request(folder, **run):
    return RunRequest(
        ingest={"plugin": "image_folder", "config": {"path": str(folder)}},
        prompts={"set_inline": SET_INLINE},
        run=run,
    )


def _wait_final(manager, run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.get(run_id)["status"]
        if status != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("el run no terminó a tiempo")


def test_run_exitoso_y_summary_con_status(manager, tmp_path):
    run_id = manager.start_run(_request(_images(tmp_path)))
    assert _wait_final(manager, run_id) == "succeeded"
    summary = json.loads(
        (tmp_path / "runs" / run_id / "summary.json").read_text()
    )
    assert summary["status"] == "succeeded"


def test_busy_mientras_corre(manager, tmp_path):
    folder = _images(tmp_path, n=400)
    run_id = manager.start_run(_request(folder))
    with pytest.raises(RunBusyError):
        manager.start_run(_request(folder))
    manager.stop(run_id)
    assert _wait_final(manager, run_id) == "stopped"


def test_fallo_en_setup_escribe_summary_failed(manager, tmp_path):
    run_id = manager.start_run(_request(tmp_path / "no_existe"))
    status = _wait_final(manager, run_id)
    assert status == "failed"
    summary = json.loads((tmp_path / "runs" / run_id / "summary.json").read_text())
    assert summary["status"] == "failed" and summary["error"]


def test_get_desconocido(manager):
    with pytest.raises(UnknownRunError):
        manager.get("nope")


def test_list_runs_desde_disco(manager, tmp_path):
    run_id = manager.start_run(_request(_images(tmp_path)))
    _wait_final(manager, run_id)
    runs = manager.list_runs()
    assert any(r["run_id"] == run_id for r in runs)
