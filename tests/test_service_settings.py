from pathlib import Path
import pytest
from eovrt_media.service.settings import ServiceSettings


def test_from_env_minimo():
    s = ServiceSettings.from_env({"EOVRT_MODEL_REF": "mock"})
    assert s.model_ref == "mock"
    assert s.runs_dir == Path("runs")
    assert s.datasets_root is None
    assert s.watchdog_seconds == 120.0


def test_from_env_completo():
    s = ServiceSettings.from_env({
        "EOVRT_MODEL_REF": "grounding-dino/gdino-tiny",
        "EOVRT_MODEL_DEVICE": "cuda",
        "EOVRT_RUNS_DIR": "/data/runs",
        "EOVRT_DATASETS_ROOT": "/data/datasets",
        "EOVRT_WATCHDOG_SECONDS": "30",
        "EOVRT_RUNS_MAX_AGE_DAYS": "7",
    })
    assert s.model_device == "cuda"
    assert s.datasets_root == Path("/data/datasets")
    assert s.retention_max_age_days == 7.0


def test_model_ref_obligatorio():
    with pytest.raises(ValueError, match="EOVRT_MODEL_REF"):
        ServiceSettings.from_env({})
