import json
import time
from pathlib import Path
from eovrt_media.service.retention import gc_runs_dir, reconcile_orphan_runs
from eovrt_media.service.settings import ServiceSettings


def _settings(tmp_path):
    """Helper para construir ServiceSettings en tests de retención."""
    return ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "mock",
        "EOVRT_RUNS_DIR": str(tmp_path / "runs"),
    })


def _mkrun(runs: Path, name: str, age_days: float = 0.0, size_bytes: int = 10):
    d = runs / name
    d.mkdir(parents=True)
    (d / "summary.json").write_bytes(b"x" * size_bytes)
    old = time.time() - age_days * 86400
    import os
    os.utime(d, (old, old))
    return d


def test_gc_por_edad(tmp_path):
    runs = tmp_path / "runs"
    _mkrun(runs, "viejo", age_days=10)
    _mkrun(runs, "nuevo", age_days=0)
    settings = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs),
        "EOVRT_RUNS_MAX_AGE_DAYS": "7",
    })
    removed = gc_runs_dir(settings)
    assert removed == ["viejo"]
    assert not (runs / "viejo").exists() and (runs / "nuevo").exists()


def test_gc_sin_limites_no_borra(tmp_path):
    runs = tmp_path / "runs"
    _mkrun(runs, "a")
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    assert gc_runs_dir(settings) == []


def test_gc_excluye_run_activo(tmp_path):
    """gc_runs_dir no debe borrar el run que está corriendo ahora mismo,
    aunque sea el más viejo y exceda la retención por edad."""
    runs = tmp_path / "runs"
    _mkrun(runs, "activo", age_days=10)
    settings = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs),
        "EOVRT_RUNS_MAX_AGE_DAYS": "7",
    })
    removed = gc_runs_dir(settings, exclude={"activo"})
    assert removed == []
    assert (runs / "activo").exists()


def _mkrun_sin_summary(runs: Path, name: str):
    """Simula un run huérfano: dir con artefactos parciales pero sin
    summary.json (el proceso murió con el run activo, F1 kill/OOM)."""
    d = runs / name
    d.mkdir(parents=True)
    (d / "detections.jsonl").write_text('{"unit_id": "u1"}\n')
    return d


def test_reconcile_marca_huerfano_como_interrupted(tmp_path):
    runs = tmp_path / "runs"
    _mkrun_sin_summary(runs, "run_huerfano")
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    reconciled = reconcile_orphan_runs(settings)
    assert reconciled == ["run_huerfano"]
    summary = json.loads((runs / "run_huerfano" / "summary.json").read_text())
    assert summary["status"] == "interrupted"
    assert summary["run_id"] == "run_huerfano"


def test_reconcile_no_pisa_summary_existente(tmp_path):
    runs = tmp_path / "runs"
    d = _mkrun(runs, "run_ok")  # ya tiene summary.json (fixture _mkrun)
    (d / "summary.json").write_text('{"run_id": "run_ok", "status": "succeeded"}')
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    reconciled = reconcile_orphan_runs(settings)
    assert reconciled == []
    summary = json.loads((d / "summary.json").read_text())
    assert summary["status"] == "succeeded"


def test_reconcile_es_idempotente(tmp_path):
    runs = tmp_path / "runs"
    _mkrun_sin_summary(runs, "run_huerfano")
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(runs)}
    )
    first = reconcile_orphan_runs(settings)
    second = reconcile_orphan_runs(settings)
    assert first == ["run_huerfano"]
    assert second == []  # la segunda pasada ya encuentra summary.json


def test_reconcile_sin_runs_dir_no_rompe(tmp_path):
    settings = ServiceSettings.from_env(
        {"EOVRT_MODEL_REF": "mock", "EOVRT_RUNS_DIR": str(tmp_path / "no_existe")}
    )
    assert reconcile_orphan_runs(settings) == []


def test_reconcile_saltea_huerfano_two_node(tmp_path):
    """Spec 2026-07-06 §3.3: el servicio no es dueño de los runs two-node;
    un huérfano two-node puede estar vivo y no debe estamparse interrupted."""
    runs = tmp_path / "runs"
    d = runs / "run_ebe_huerfano"
    d.mkdir(parents=True)
    (d / "effective_config.yaml").write_text("topology:\n  mode: two_node\n")
    settings = _settings(tmp_path)

    assert reconcile_orphan_runs(settings) == []
    assert not (d / "summary.json").exists()


def test_reconcile_sigue_marcando_huerfano_single_host(tmp_path):
    runs = tmp_path / "runs"
    d = runs / "run_dbe_huerfano"
    d.mkdir(parents=True)
    (d / "effective_config.yaml").write_text("topology:\n  mode: single_host\n")
    settings = _settings(tmp_path)

    assert reconcile_orphan_runs(settings) == ["run_dbe_huerfano"]
    assert json.loads((d / "summary.json").read_text())["status"] == "interrupted"


def test_reconcile_no_crashea_con_effective_config_mal_formado(tmp_path):
    """Un effective_config.yaml sintácticamente válido pero con topology como
    escalar (no mapping) no debe romper el reconcile completo — degrada a
    reconciliar el huérfano como single-host (comportamiento de 'ilegible')."""
    runs = tmp_path / "runs"
    d = runs / "run_mal_formado"
    d.mkdir(parents=True)
    (d / "effective_config.yaml").write_text("topology: two_node\n")  # topology es un string, no un mapping
    settings = _settings(tmp_path)

    reconciled = reconcile_orphan_runs(settings)  # NO debe lanzar AttributeError

    assert reconciled == ["run_mal_formado"]
    assert json.loads((d / "summary.json").read_text())["status"] == "interrupted"
