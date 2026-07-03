import time
from pathlib import Path
from eovrt_media.service.retention import gc_runs_dir
from eovrt_media.service.settings import ServiceSettings


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
