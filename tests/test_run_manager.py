import json
import time

import pytest
from PIL import Image

from eovrt_media.config.loader import resolve_model_ref
from eovrt_media.models import create_adapter
from eovrt_media.service import run_manager as run_manager_module
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


def test_watchdog_tick_delega_en_stop_atomico(manager, tmp_path, monkeypatch):
    """El watchdog no debe mutar stop_cause directamente: tiene que pasar por
    stop(), que hace el check-and-set atómico bajo lock (regresión del hallazgo
    de TOCTOU)."""
    folder = _images(tmp_path, n=400)
    run_id = manager.start_run(_request(folder))
    active = manager._active
    assert active is not None
    # Simula estancamiento sin esperar el timeout real del watchdog_seconds.
    active.broadcaster.last_event_monotonic = time.monotonic() - 1_000_000

    calls = []
    original_stop = manager.stop

    def spy_stop(rid, cause="stop"):
        calls.append((rid, cause))
        return original_stop(rid, cause=cause)

    monkeypatch.setattr(manager, "stop", spy_stop)

    manager._watchdog_tick()

    assert calls == [(run_id, "stalled")]
    status = _wait_final(manager, run_id)
    assert status == "failed"  # stop_cause=="stalled" => status "failed" (ver _execute)
    summary = json.loads((tmp_path / "runs" / run_id / "summary.json").read_text())
    assert summary["stop_cause"] == "stalled"


def test_watchdog_tick_no_pisa_stop_cause_existente(manager, tmp_path):
    """Si stop_cause ya quedó asignado (p.ej. un stop() de usuario ganó la
    carrera), el watchdog no debe sobreescribirlo con 'stalled'."""
    folder = _images(tmp_path, n=400)
    run_id = manager.start_run(_request(folder))
    active = manager._active
    assert active is not None
    active.stop_cause = "stop"
    active.broadcaster.last_event_monotonic = time.monotonic() - 1_000_000

    manager._watchdog_tick()

    assert active.stop_cause == "stop"

    manager.stop(run_id, cause="stop")
    status = _wait_final(manager, run_id)
    assert status == "stopped"
    summary = json.loads((tmp_path / "runs" / run_id / "summary.json").read_text())
    assert summary["stop_cause"] == "stop"


def test_stop_es_atomico_primero_gana(manager, tmp_path):
    """Propiedad en la que se apoya el fix: stop() no pisa una stop_cause ya
    asignada, sin importar qué cause llegue después."""
    folder = _images(tmp_path, n=400)
    run_id = manager.start_run(_request(folder))
    manager.stop(run_id, cause="stop")
    manager.stop(run_id, cause="stalled")  # llegada tardía, no debe ganar
    status = _wait_final(manager, run_id)
    assert status == "stopped"
    summary = json.loads((tmp_path / "runs" / run_id / "summary.json").read_text())
    assert summary["stop_cause"] == "stop"


def test_watchdog_invoca_gc_periodicamente(manager, monkeypatch):
    """El GC de retención (gc_runs_dir) sólo se llamaba al startup del
    servicio; con retención configurada nunca se aplicaba en un proceso de
    larga vida. El watchdog debe invocarlo cada `_gc_interval_seconds` de
    wall-clock (medidos vía time.monotonic, sin sleeps largos en el test)."""
    calls = []
    monkeypatch.setattr(
        run_manager_module, "gc_runs_dir", lambda settings, exclude=None: calls.append(exclude) or []
    )

    # Aún no pasó el intervalo: no debe invocar el GC.
    manager._watchdog_tick()
    assert calls == []

    # Forzamos que "ya pasó" el intervalo de GC.
    manager._last_gc_monotonic = time.monotonic() - manager._gc_interval_seconds - 1
    manager._watchdog_tick()
    assert len(calls) == 1
    assert calls[0] is None  # sin run activo, no hay nada que excluir

    # Inmediatamente después no debe volver a invocarlo (intervalo reiniciado).
    manager._watchdog_tick()
    assert len(calls) == 1


def test_watchdog_gc_periodico_excluye_run_activo(manager, tmp_path, monkeypatch):
    """Si hay un run activo cuando toca correr el GC, no debe poder ser
    borrado: se le pasa a gc_runs_dir para que lo excluya explícitamente."""
    folder = _images(tmp_path, n=400)
    run_id = manager.start_run(_request(folder))

    calls = []
    monkeypatch.setattr(
        run_manager_module, "gc_runs_dir", lambda settings, exclude=None: calls.append(exclude) or []
    )
    manager._last_gc_monotonic = time.monotonic() - manager._gc_interval_seconds - 1
    manager._watchdog_tick()

    assert calls == [{run_id}]
    manager.stop(run_id)
    _wait_final(manager, run_id)


def test_watchdog_tick_run_terminado_no_crashea(manager, tmp_path):
    """Si el run ya terminó entre la lectura de staleness y la llamada a
    stop(), el watchdog no debe crashear con UnknownRunError."""
    run_id = manager.start_run(_request(_images(tmp_path)))
    _wait_final(manager, run_id)
    assert manager._active is None
    # No debe lanzar, aunque no haya run activo.
    manager._watchdog_tick()
