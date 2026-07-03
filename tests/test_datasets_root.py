"""Test rebase_dataset_path y datasets_root integration en load_run_config_data."""
from pathlib import Path

from eovrt_media.config.loader import load_run_config_data, rebase_dataset_path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"

SET_INLINE = {"id": "t", "classes": [{"id": "p", "phrasings": {"default": ["p"]}}]}


def test_rebase_con_root():
    """rebase_dataset_path rebasa ../e-ovrt_datasets/ sobre datasets_root."""
    assert (
        rebase_dataset_path("../e-ovrt_datasets/datasets/raw/chv/images", Path("/data/datasets"))
        == "/data/datasets/datasets/raw/chv/images"
    )


def test_rebase_sin_root_es_identidad():
    """rebase_dataset_path es identidad cuando datasets_root es None."""
    p = "../e-ovrt_datasets/datasets/raw/chv/images"
    assert rebase_dataset_path(p, None) == p


def test_rebase_no_toca_paths_ajenos():
    """rebase_dataset_path no modifica paths que no empiezan con ../e-ovrt_datasets/."""
    assert rebase_dataset_path("/abs/video.mp4", Path("/data/datasets")) == "/abs/video.mp4"


def test_load_run_config_data_rebasa_source_path():
    """load_run_config_data rebasa source.path cuando datasets_root está presente."""
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": "../e-ovrt_datasets/datasets/raw/x"},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE},
    }
    config = load_run_config_data(
        raw, plane_root=PLANE_ROOT, datasets_root=Path("/mnt/ds")
    )
    assert config.source.path == "/mnt/ds/datasets/raw/x"
