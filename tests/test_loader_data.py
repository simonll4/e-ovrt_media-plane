from pathlib import Path

import pytest

from eovrt_media.config.loader import load_run_config_data, resolve_model_ref

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"
FIXTURE_PROMPTS = REPO_ROOT / "tests" / "fixtures"  # contiene prompts/ (fixtures existentes)


def _raw(tmp_path):
    return {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {"ref": "cr01_cr02_v2_short"},  # tests/fixtures/prompts/cr01_cr02_v2_short.yaml
    }


def test_load_run_config_data_valida_dict(tmp_path):
    config = load_run_config_data(
        _raw(tmp_path), plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS
    )
    assert config.model.adapter == "mock"
    assert config.prompts_file is not None
    assert config.rate_control.policy == "deterministic"  # default derivado


def test_load_run_config_data_rechaza_sampling(tmp_path):
    raw = _raw(tmp_path)
    raw["sampling"] = {"every_n": 2}
    with pytest.raises(ValueError, match="sampling"):
        load_run_config_data(raw, plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS)


def test_resolve_model_ref_mock():
    section = resolve_model_ref("mock")
    assert section.ref == "mock"
    assert (section.adapter or section.name) == "mock"


def test_resolve_model_ref_inexistente():
    with pytest.raises(FileNotFoundError):
        resolve_model_ref("no-existe/nada")
